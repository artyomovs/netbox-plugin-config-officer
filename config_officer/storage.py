"""Device configuration storage: plain files in a directory that is also a Git repository.

Layout (unchanged since 0.1.x, so existing repositories keep working)::

    <CONFIGS_REPO_DIR>/              git work tree, branch GIT_REMOTE.BRANCH ("netbox")
        <CONFIGS_SUBPATH>/           "netbox" by default
            <hostname>_running.txt

:class:`ConfigRepository` is the only code that touches these files or runs git:

* ``write_config`` stores a collected config, but only if it *really* changed
  (lines matching VOLATILE_LINE_PATTERNS, e.g. "! Last configuration change
  at ...", are ignored when comparing);
* ``prepare`` / ``commit`` are called once per collection run: one commit per
  run, then an optional push to ``GIT_REMOTE``;
* ``history`` / ``diff_in_commit`` answer questions for the UI and the webhook.

Git always runs with an explicit environment (safe.directory, author identity,
SSH key) set on the repository object instead of ``os.environ``, so nothing
leaks into other jobs that share the worker process. A local commit is never
thrown away: if a push fails, the next run pushes it again.
"""

from __future__ import annotations

import atexit
import logging
import os
import re
import shlex
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo

from .configuration import GitRemoteSettings, PluginSettings, get_settings

logger = logging.getLogger(__name__)

CONFIG_SUFFIX = "_running.txt"


class StorageError(Exception):
    """The repository cannot be used (missing directory, not a git repository, ...)."""


@dataclass(frozen=True)
class CommitInfo:
    sha: str
    date: datetime
    message: str
    diff: str = ""

    @property
    def short_sha(self) -> str:
        return self.sha[:8]


@dataclass(frozen=True)
class FileHistory:
    """Git history of one device config file, newest commit first."""

    count: int = 0
    first_date: datetime | None = None
    last_date: datetime | None = None
    commits: list[CommitInfo] = field(default_factory=list)


@dataclass
class CommitResult:
    sha: str = ""
    files: list[str] = field(default_factory=list)
    pushed: bool | None = None  # None = no remote configured / nothing to push
    push_error: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def committed(self) -> bool:
        return bool(self.sha)

    def describe(self) -> str:
        if self.committed:
            text = f"committed {self.sha[:8]} ({len(self.files)} file(s))"
        else:
            text = "no configuration changes to commit"
        if self.pushed is True:
            text += ", pushed to remote"
        elif self.pushed is False:
            text += f", PUSH FAILED: {self.push_error}"
        return text


def strip_volatile_lines(text: str, regexes) -> str:
    """Normalise a config for comparison: drop volatile lines and trailing whitespace."""
    lines = [
        line.rstrip() for line in text.splitlines() if not any(r.search(line) for r in regexes)
    ]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _parse_author(author: str) -> tuple[str, str]:
    match = re.match(r"^\s*(.+?)\s*<(.+?)>\s*$", author or "")
    if match:
        return match.group(1), match.group(2)
    return "Netbox", "netbox@example.com"


def _short_error(exc: GitCommandError) -> str:
    text = (exc.stderr or str(exc)).strip().replace("\n", " ")
    return text[:300]


class _SshKeyCache:
    """Private 0600 copies of SSH keys, made once per process.

    OpenSSH refuses keys with loose permissions, and keys mounted from Kubernetes
    secrets / Vault may lack the trailing newline it requires.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._directory: str | None = None
        self._copies: dict[tuple, str] = {}

    def get(self, path: str) -> str:
        source = Path(path)
        stat_result = source.stat()  # raises FileNotFoundError if missing
        cache_key = (str(source), stat_result.st_mtime_ns, stat_result.st_size)
        with self._lock:
            copy = self._copies.get(cache_key)
            if copy and os.path.exists(copy):
                return copy
            if self._directory is None:
                self._directory = tempfile.mkdtemp(prefix="config_officer_")
                atexit.register(shutil.rmtree, self._directory, True)
            data = source.read_bytes()
            if not data.endswith(b"\n"):
                data += b"\n"
            copy = os.path.join(self._directory, "git_ssh_key")
            fd = os.open(copy, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            self._copies = {cache_key: copy}
            return copy


_ssh_keys = _SshKeyCache()


class ConfigRepository:
    def __init__(
        self,
        repo_dir: str | os.PathLike,
        subpath: str = "netbox",
        remote: GitRemoteSettings | None = None,
        volatile_regexes=(),
        branch: str | None = None,
    ):
        self.repo_dir = Path(repo_dir)
        self.subpath = subpath
        self.remote = remote
        self.volatile_regexes = tuple(volatile_regexes)
        self.branch = branch or (remote.branch if remote else "netbox")
        self._remote_problem = ""

    @classmethod
    def from_settings(cls, settings: PluginSettings | None = None) -> ConfigRepository:
        settings = settings or get_settings()
        return cls(
            repo_dir=settings.configs_repo_dir,
            subpath=settings.configs_subpath,
            remote=settings.git_remote,
            volatile_regexes=settings.volatile_regexes,
        )

    # ------------------------------------------------------------------
    # Config files
    # ------------------------------------------------------------------

    @property
    def configs_path(self) -> Path:
        return self.repo_dir / self.subpath

    def _relative_path(self, hostname: str) -> str:
        return f"{self.subpath}/{hostname}{CONFIG_SUFFIX}"

    def config_file(self, hostname: str) -> Path:
        return self.configs_path / f"{hostname}{CONFIG_SUFFIX}"

    def read_config(self, hostname: str) -> str | None:
        try:
            return self.config_file(hostname).read_text(errors="replace")
        except FileNotFoundError:
            return None

    def config_updated_at(self, hostname: str) -> datetime | None:
        """When the config was last collected successfully (file modification time)."""
        try:
            return datetime.fromtimestamp(self.config_file(hostname).stat().st_mtime, tz=UTC)
        except OSError:
            return None

    def write_config(self, hostname: str, text: str) -> bool:
        """Store a collected config. Returns True if its content changed meaningfully.

        An unchanged config (ignoring volatile lines) is not rewritten - so git sees
        no change - but its modification time is refreshed to record the collection.
        """
        path = self.config_file(hostname)
        path.parent.mkdir(parents=True, exist_ok=True)
        new_text = text if text.endswith("\n") else text + "\n"
        if path.exists():
            old_text = path.read_text(errors="replace")
            if strip_volatile_lines(old_text, self.volatile_regexes) == strip_volatile_lines(
                new_text, self.volatile_regexes
            ):
                os.utime(path)
                return False
        fd, temp_path = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(new_text)
            os.replace(temp_path, path)
        except BaseException:
            Path(temp_path).unlink(missing_ok=True)
            raise
        return True

    # ------------------------------------------------------------------
    # Git
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """True if this process can see the git repository (used by the web UI)."""
        return (self.repo_dir / ".git").is_dir()

    @property
    def _remote_usable(self) -> bool:
        return bool(self.remote and self.remote.is_configured and not self._remote_problem)

    def _git_environment(self) -> dict[str, str]:
        name, email = _parse_author(self.remote.author if self.remote else "")
        env = {
            # The repository is often owned by another user than the worker (containers).
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "safe.directory",
            "GIT_CONFIG_VALUE_0": str(self.repo_dir),
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
            "GIT_TERMINAL_PROMPT": "0",
        }
        if self.remote and self.remote.is_configured and self.remote.ssh_key_path:
            try:
                key = _ssh_keys.get(self.remote.ssh_key_path)
            except OSError as exc:
                self._remote_problem = (
                    f"SSH key {self.remote.ssh_key_path!r} is not readable ({exc})"
                )
            else:
                env["GIT_SSH_COMMAND"] = (
                    f"ssh -i {shlex.quote(key)} -o IdentitiesOnly=yes -o BatchMode=yes"
                    " -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null"
                    " -o ConnectTimeout=15"
                )
        return env

    def _open(self, create: bool = False) -> Repo:
        try:
            repo = Repo(self.repo_dir)
        except (InvalidGitRepositoryError, NoSuchPathError):
            if not create:
                raise StorageError(
                    f"{self.repo_dir} is not a git repository (no collection has run yet)"
                ) from None
            try:
                self.repo_dir.mkdir(parents=True, exist_ok=True)
                repo = Repo.init(self.repo_dir)
            except (OSError, GitCommandError) as exc:
                raise StorageError(
                    f"cannot create a git repository in {self.repo_dir}: {exc}"
                ) from exc
            logger.info("Initialised config repository in %s", self.repo_dir)
        repo.git.update_environment(**self._git_environment())
        return repo

    def _remote_ref(self) -> str:
        return f"{self.remote.name}/{self.branch}"

    @staticmethod
    def _has_ref(repo: Repo, ref: str) -> bool:
        try:
            repo.git.rev_parse("--verify", "--quiet", ref)
            return True
        except GitCommandError:
            return False

    def prepare(self) -> list[str]:
        """Make sure the repository exists, is on the right branch and is in sync with the remote.

        Returns human-readable notes for the job log. Raises StorageError only when
        the repository cannot be used at all.
        """
        notes: list[str] = []
        repo = self._open(create=True)
        self.configs_path.mkdir(parents=True, exist_ok=True)
        if self._remote_problem:
            notes.append(f"remote disabled for this run: {self._remote_problem}")
        remote_ref = self._fetch_remote(repo, notes)
        if repo.head.is_valid():
            self._checkout_branch(repo, notes)
            if remote_ref:
                self._follow_remote(repo, remote_ref, notes)
        else:
            self._start_branch(repo, remote_ref, notes)
        return notes

    def _fetch_remote(self, repo: Repo, notes: list[str]) -> str | None:
        """Configure the remote and fetch our branch. Returns the remote ref, or None."""
        if not self._remote_usable:
            return None
        remote_names = [r.name for r in repo.remotes]
        if self.remote.name not in remote_names:
            repo.create_remote(self.remote.name, self.remote.url)
        elif repo.remotes[self.remote.name].url != self.remote.url:
            repo.git.remote("set-url", self.remote.name, self.remote.url)
        try:
            repo.git.fetch(self.remote.name, self.branch)
        except GitCommandError as exc:
            notes.append(
                f"fetch from {self._remote_ref()} failed (continuing locally): {_short_error(exc)}"
            )
            return None
        remote_ref = self._remote_ref()
        return remote_ref if self._has_ref(repo, f"refs/remotes/{remote_ref}") else None

    def _start_branch(self, repo: Repo, remote_ref: str | None, notes: list[str]) -> None:
        """Brand-new repository without commits: adopt the remote history, if there is one."""
        if remote_ref:
            try:
                repo.git.checkout("-B", self.branch, remote_ref)
                notes.append(f"checked out existing history from {remote_ref}")
                return
            except GitCommandError as exc:
                notes.append(f"could not check out {remote_ref}: {_short_error(exc)}")
        repo.git.symbolic_ref("HEAD", f"refs/heads/{self.branch}")

    def _checkout_branch(self, repo: Repo, notes: list[str]) -> None:
        try:
            current = repo.active_branch.name
        except TypeError:  # detached HEAD
            current = None
        if current == self.branch:
            return
        if self.branch in [head.name for head in repo.heads]:
            repo.git.checkout(self.branch)
        else:
            repo.git.checkout("-b", self.branch)
        notes.append(f"switched to branch {self.branch}")

    def _follow_remote(self, repo: Repo, remote_ref: str, notes: list[str]) -> None:
        """Fast-forward to the remote if it is ahead. Local commits are never discarded."""
        local_sha = repo.head.commit.hexsha
        remote_sha = repo.commit(remote_ref).hexsha
        if local_sha == remote_sha:
            return
        if repo.is_ancestor(local_sha, remote_sha):
            try:
                repo.git.merge("--ff-only", remote_ref)
                notes.append(f"fast-forwarded to {remote_ref}")
            except GitCommandError as exc:
                notes.append(f"could not fast-forward to {remote_ref}: {_short_error(exc)}")
        elif repo.is_ancestor(remote_sha, local_sha):
            notes.append(
                f"local branch has commits not yet pushed to {remote_ref}; they will be pushed"
            )
        else:
            notes.append(
                f"WARNING: local branch and {remote_ref} have diverged; nothing is overwritten, "
                "but pushes will fail until the histories are reconciled manually"
            )

    def _needs_push(self, repo: Repo) -> bool:
        if not repo.head.is_valid():
            return False
        remote_ref = self._remote_ref()
        if not self._has_ref(repo, f"refs/remotes/{remote_ref}"):
            return True
        return int(repo.git.rev_list("--count", f"{remote_ref}..HEAD")) > 0

    def commit(self, message: str) -> CommitResult:
        """Commit all changed config files (one commit per run) and push if configured."""
        repo = self._open()
        result = CommitResult()
        repo.git.add("--all", "--", self.subpath)
        staged = [line for line in repo.git.diff("--cached", "--name-only").splitlines() if line]
        if staged:
            repo.git.commit("-m", message)
            result.sha = repo.head.commit.hexsha
            result.files = staged

        if self._remote_usable and self._needs_push(repo):
            try:
                repo.git.push(self.remote.name, f"HEAD:refs/heads/{self.branch}")
                result.pushed = True
            except GitCommandError as exc:
                result.pushed = False
                result.push_error = _short_error(exc)
        elif self._remote_problem:
            result.notes.append(f"not pushed: {self._remote_problem}")
        return result

    def history(self, hostname: str, limit: int = 50) -> FileHistory:
        """Commits that changed the device's config, newest first, with their diffs."""
        try:
            repo = self._open()
        except StorageError:
            return FileHistory()
        if not repo.head.is_valid():
            return FileHistory()
        path = self._relative_path(hostname)
        dates = repo.git.log("--format=%cI", "--", path).split()
        if not dates:
            return FileHistory()

        # One `git log -p` call: \x1e starts a commit record, \x1f separates its fields.
        raw = repo.git.log(f"-n{limit}", "-p", "--format=%x1e%H%x1f%cI%x1f%s%x1f", "--", path)
        commits = []
        for record in raw.split("\x1e")[1:]:
            sha, date, subject, patch = record.split("\x1f", 3)
            commits.append(
                CommitInfo(
                    sha=sha,
                    date=datetime.fromisoformat(date),
                    message=subject,
                    diff=patch.strip("\n"),
                )
            )
        return FileHistory(
            count=len(dates),
            first_date=datetime.fromisoformat(dates[-1]),
            last_date=datetime.fromisoformat(dates[0]),
            commits=commits,
        )

    def diff_in_commit(self, sha: str, hostname: str) -> str:
        """Patch of the device's config file in commit ``sha`` (empty if untouched)."""
        repo = self._open()
        return repo.git.show("--format=", sha, "--", self._relative_path(hostname)).strip("\n")


def device_config_snapshot(repo: ConfigRepository, hostname: str, history_limit: int = 50) -> dict:
    """Config text + history of one device as plain JSON-able data (for the UI)."""
    updated = repo.config_updated_at(hostname)
    history = repo.history(hostname, limit=history_limit)
    return {
        "config": repo.read_config(hostname),
        "updated": updated.isoformat() if updated else None,
        "history": {
            "count": history.count,
            "first_date": history.first_date.isoformat() if history.first_date else None,
            "last_date": history.last_date.isoformat() if history.last_date else None,
            "commits": [
                {"sha": c.sha, "date": c.date.isoformat(), "message": c.message, "diff": c.diff}
                for c in history.commits
            ],
        },
    }
