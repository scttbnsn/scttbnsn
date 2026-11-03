#!/usr/bin/env python3
"""Live star counts and the 3x3 grid data for the PUBLIC section of the card."""

import json
import os
import urllib.request
from pathlib import Path

CACHE_FILE = Path(__file__).parent / "cache" / "public_repos.json"

# (owner/repo, category, short description)
REPOS = [
    ("CodesWhat/drydock", "docker", "container updates"),
    ("CodesWhat/sockguard", "docker", "docker socket proxy"),
    ("CodesWhat/portwing", "docker", "remote docker agent"),
    ("CodesWhat/portkey-admin-mcp", "agents", "portkey admin MCP"),
    ("CodesWhat/careerrat", "agents", "job-search workspace"),
    ("scttbnsn/claudeline", "agents", "claude code statusline"),
    ("CodesWhat/idlescreen", "macos", "ASCII screensaver"),
    ("CodesWhat/mouthtype", "macos", "push-to-talk dictation"),
    ("CodesWhat/dilated", "macos", "keeps Mac awake"),
]
CATEGORIES = [("docker", "DOCKER"), ("agents", "AGENTS + AI"), ("macos", "MACOS")]


def _load_cache(path=None):
    try:
        data = json.loads(Path(path or CACHE_FILE).read_text())
        return {k: v for k, v in data.items() if isinstance(v, int) and v >= 0}
    except (OSError, ValueError, AttributeError):
        return {}


def _save_cache(stars, path=None):
    path = Path(path or CACHE_FILE)
    try:
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(stars, indent=2, sort_keys=True) + "\n")
    except OSError:
        pass


def _fetch_one(repo, timeout=10):
    """Return stargazers_count for owner/repo from the GitHub REST API."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "scttbnsn-profile-card"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return int(json.load(resp)["stargazers_count"])


def get_stars(cache_path=None):
    """Return {repo: stars or None}. Live value, else cached, else None. Never raises."""
    cached = _load_cache(cache_path)
    result = {}
    for repo, _, _ in REPOS:
        old = cached.get(repo)
        try:
            live = _fetch_one(repo)
        except Exception:
            live = None
        if live is None or live < 0:
            result[repo] = old
        elif live == 0 and old:
            result[repo] = old  # a 0 over a good cached value is an API glitch
        else:
            result[repo] = live
    to_save = {k: v for k, v in result.items() if v is not None}
    if to_save != cached:
        _save_cache({**cached, **to_save}, cache_path)
    return result


def grid_columns(stars):
    """Per category, [(repo_name, stars_or_None, desc)] sorted by stars descending."""
    cols = []
    for key, _ in CATEGORIES:
        items = [(r.split("/")[1], stars.get(r), d) for r, k, d in REPOS if k == key]
        items.sort(key=lambda t: -(t[1] if t[1] is not None else -1))
        cols.append(items)
    return cols
