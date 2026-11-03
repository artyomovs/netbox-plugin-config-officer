"""
Hierarchical diff of Cisco IOS-style configurations (a lightweight replacement for diffios).

Supports:
    Compare(template, config, ignore_lines).missing()
    Compare(template, config, ignore_lines).additional()
    Compare(template, config, ignore_lines).delta()

Template lines may contain {{ variable }} placeholders which match any value.
Inputs can be lists of strings or paths to text files.
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_PLACEHOLDER = re.compile(r"\{\{[^{}]+\}\}")
_COMMENT_OR_EMPTY = re.compile(r"^\s*(!|$|\^C?$)")


def _load(data: list[str] | str) -> list[str]:
    """Accept a list of lines or a file path; return a list of split lines."""
    if isinstance(data, list):
        return data
    path = Path(data)
    if not path.exists():
        raise FileNotFoundError(f"cisco_diff: cannot open '{data}'")
    return path.read_text(encoding="utf-8").splitlines()


def _valid_line(line: str) -> bool:
    """Return True if line is not comment or empty"""
    return not _COMMENT_OR_EMPTY.match(line)


def _matches(template_line: str, config_line: str) -> bool:
    """Return True if config_line matches template_line (with {{ }} wildcards)."""
    if "{{" not in template_line:
        return template_line == config_line
    pattern = re.escape(template_line)
    pattern = re.sub(r"\\\{\\\{[^{}]+\\\}\\\}", "(.+)", pattern)
    m = re.fullmatch(pattern, config_line)
    return m is not None


# ---------------------------------------------------------------------------
# Config - parses a Cisco IOS config into hierarchical groups
# ---------------------------------------------------------------------------


class Config:
    """Parse a Cisco IOS config into hierarchical blocks, respecting ignore list.

    Args:
        data:         List of config lines or path to a config file.
        ignore_lines: List of regex-style patterns (or file path) to ignore.
                      A parent line matching an ignore pattern causes the whole
                      block to be ignored; a child match ignores only that line.
    """

    def __init__(
        self,
        data: list[str] | str,
        ignore_lines: list[str] | str | None = None,
    ) -> None:
        raw = _load(data)
        self._lines = [line.rstrip() for line in raw if _valid_line(line)]

        if ignore_lines is None:
            self._ignores: list[str] = []
        elif isinstance(ignore_lines, list):
            self._ignores = [i.strip() for i in ignore_lines]
        else:
            self._ignores = [line.strip() for line in _load(ignore_lines) if line.strip()]

    # ------------------------------------------------------------------
    # Internal grouping
    # ------------------------------------------------------------------

    def _groups(self) -> list[list[str]]:
        """Split config into parent+children groups sorted by parent (child lines start with space)."""
        groups: list[list[str]] = []
        current: list[str] = []
        for line in self._lines:
            if not line.startswith(" ") and current:
                groups.append(current)
                current = [line]
            else:
                current.append(line)
        if current:
            groups.append(current)
        return sorted(groups)

    def _ignored(self, line: str) -> bool:
        """Return True if line matches any ignore pattern."""
        lo = line.lower().strip()
        for pattern in self._ignores:
            p = pattern.lower()
            # escape regex metacharacters except * which we keep as-is for simple globs
            escaped = re.escape(p)
            if re.search(escaped, lo):
                return True
        return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def included(self) -> list[list[str]]:
        """Return groups of lines NOT covered by the ignore list."""
        result: list[list[str]] = []
        for group in self._groups():
            parent = group[0]
            if self._ignored(parent):
                continue
            kept = [parent] + [c for c in group[1:] if not self._ignored(c)]
            if len(kept) > 1 or not any(c for c in group[1:]):
                result.append(kept)
            else:
                result.append([parent])
        return result

    def ignored(self) -> list[list[str]]:
        """Return groups of lines covered by the ignore list."""
        result: list[list[str]] = []
        for group in self._groups():
            parent = group[0]
            if self._ignored(parent):
                result.append(group)
                continue
            dropped = [c for c in group[1:] if self._ignored(c)]
            if dropped:
                result.append([parent] + dropped)
        return result


# ---------------------------------------------------------------------------
# Compare - diffs template against running config
# ---------------------------------------------------------------------------


class Compare:
    """Diff a Cisco IOS template against a running config.

    Args:
        template:     Template config (list of lines or file path).
                      May contain {{ placeholder }} wildcards.
        config:       Running config (list of lines or file path).
        ignore_lines: Lines / patterns to exclude from comparison.

    Usage::

        diff = Compare(template, config, ignore_lines)
        missing    = diff.missing()    # in template, absent from config
        additional = diff.additional() # in config, absent from template
        print(diff.delta())
    """

    def __init__(
        self,
        template: list[str] | str | Config,
        config: list[str] | str | Config,
        ignore_lines: list[str] | str | None = None,
    ) -> None:
        self.template = template if isinstance(template, Config) else Config(template, ignore_lines)
        self.config = config if isinstance(config, Config) else Config(config, ignore_lines)

    # ------------------------------------------------------------------
    # Core comparison
    # ------------------------------------------------------------------

    def _find_matching_parent(self, tmpl_parent: str, cfg_parents: list[str]) -> str | None:
        """Find a config parent line matching the template parent (with {{ }})."""
        for cp in cfg_parents:
            if _matches(tmpl_parent, cp):
                return cp
        return None

    def _find_matching_child(self, tmpl_child: str, cfg_children: list[str]) -> str | None:
        for cc in cfg_children:
            if _matches(tmpl_child, cc):
                return cc
        return None

    def _compare(self) -> tuple[list[list[str]], list[list[str]]]:
        tmpl_groups = self.template.included()
        cfg_groups = self.config.included()

        # Build a mutable dict: parent -> [children]
        cfg_map: dict[str, list[str]] = {}
        for group in cfg_groups:
            cfg_map[group[0]] = list(group[1:])

        missing: list[list[str]] = []
        additional: list[list[str]] = []

        for tmpl_group in tmpl_groups:
            tmpl_parent = tmpl_group[0]
            tmpl_children = tmpl_group[1:]

            matched_parent = self._find_matching_parent(tmpl_parent, list(cfg_map.keys()))

            if matched_parent is None:
                # Entire block missing from config
                missing.append(tmpl_group)
                continue

            cfg_children = list(cfg_map.pop(matched_parent))
            remaining_cfg = list(cfg_children)

            missing_children: list[str] = []
            for tc in tmpl_children:
                mc = self._find_matching_child(tc, remaining_cfg)
                if mc is not None:
                    remaining_cfg.remove(mc)
                else:
                    missing_children.append(tc)

            if missing_children:
                missing.append([tmpl_parent] + missing_children)
            if remaining_cfg:
                additional.append([matched_parent] + remaining_cfg)

        # Whatever is left in cfg_map has no counterpart in the template
        for parent, children in cfg_map.items():
            additional.append([parent] + children)

        return sorted(missing), sorted(additional)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def missing(self) -> list[list[str]]:
        """Lines present in the template but absent from the running config."""
        return self._compare()[0]

    def additional(self) -> list[list[str]]:
        """Lines present in the running config but absent from the template."""
        return self._compare()[1]

    @staticmethod
    def _fmt(groups: list[list[str]], prefix: str) -> str:
        out = ""
        for i, group in enumerate(groups, 1):
            out += f"\n{prefix} {i:>3}: {group[0]}"
            for child in group[1:]:
                out += f"\n{prefix}      {child}"
        return out

    def delta(self) -> str:
        """Human-readable unified diff (missing = '-', additional = '+')."""
        m, a = self._compare()
        return f"--- template\n+++ config{self._fmt(m, '-')}\n{self._fmt(a, '+')}\n"

    def pprint_missing(self) -> str:
        return "\n\n".join("\n".join(g) for g in self.missing())

    def pprint_additional(self) -> str:
        return "\n\n".join("\n".join(g) for g in self.additional())
