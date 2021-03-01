"""Manage data in local git repository."""

from pydriller import RepositoryMining, GitRepository
import time
import os
from datetime import datetime

def get_device_config(directory, hostname, config_type="running"):
    """Get data from text file according to config source."""
    try:
        with open(f"{directory}/{hostname}_{config_type}.txt", "r") as file:
            return file.read()
    except FileNotFoundError:
        return None


def get_days_after_update(directory, hostname, config_type="running"):
    """Get days after last update."""
    try:
        create_time = os.stat(f"{directory}/{hostname}_{config_type}.txt").st_ctime        
        return round((time.time() - create_time) / 86400)
    except:
        return -1


def get_config_update_date(directory, hostname, config_type="running"):
    """Get date of last update device config file."""

    try:
        create_time = os.stat(f"{directory}/{hostname}_{config_type}.txt").st_ctime   
        return datetime.fromtimestamp(create_time).strftime("%Y-%m-%d %H:%M")       
    except:
        return "unknown"


def get_file_repo_state(repository_path, filename):
    """Get commits and diffs for file."""

    git_repo = GitRepository(repository_path)
    repo_state = {}
    repo_state["commits_count"] = 0
    try:
        file_commits_list = git_repo.git.log("--format=%H", filename).split("\n")
        file_commits = list(RepositoryMining(repository_path, only_commits=file_commits_list).traverse_commits())
        file_commits.reverse()
        repo_state["commits_count"] = len(file_commits)
    except:
        pass
        
    if repo_state["commits_count"] > 0:
        repo_state["last_commit_date"] = file_commits[0].author_date.strftime("%d %b %Y %H:%M")
        repo_state["first_commit_date"] = file_commits[-1].author_date.strftime("%d %b %Y %H:%M")
        repo_state["commits"] = []
        for commit in file_commits:
            print(commit.hash)
            for mod in commit.modifications:
                if mod.filename == filename:
                    diff = mod.diff
            repo_state["commits"].append(
                {"hash": commit.hash, "msg": commit.msg, "diff": diff, "date": commit.author_date}
            )
    else:
        repo_state["comment"] = "no commits changes for {filename}"
    return repo_state

if __name__ == "__main__":
    get_file_repo_state("/opt/ipam-data/git/devices_configs", "dv-r1_running.txt")
