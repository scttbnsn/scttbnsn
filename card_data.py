#!/usr/bin/env python3
"""Live data for the htop card: the contribution calendar and aggregated language bytes.

Both fetchers use stdlib urllib against the GitHub GraphQL API, cache to cache/*.json, and never
raise. A failed fetch returns the cached value, and a live result that is empty never overwrites a
good cache (two writers share the cache, so a blank run must not blank the heatmap).
"""

import datetime
import json
import os
import subprocess
import urllib.request
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "cache"
CALENDAR_CACHE = CACHE_DIR / "contributions.json"
LANGUAGES_CACHE = CACHE_DIR / "languages.json"

USER = "scttbnsn"
LANGUAGE_OWNERS = ("scttbnsn", "CodesWhat")
LANGUAGE_SCOPE_NOTE = "all repos"
# Generated or vendored languages that would drown the real ones (HTML in particular is mostly
# generated reports and vendored assets). Kept to the languages that are obviously skewed.
EXCLUDED_LANGUAGES = frozenset({"HTML", "MDX", "Jupyter Notebook", "Roff"})

API_URL = "https://api.github.com/graphql"

CALENDAR_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { firstDay contributionDays { contributionCount } }
      }
    }
  }
}
"""

REPOS_QUERY = """
query($login: String!, $after: String) {
  repositoryOwner(login: $login) {
    repositories(first: 50, after: $after, ownerAffiliations: OWNER, isFork: false) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        isFork
        isArchived
        languages(first: 20, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""


def _auth_token():
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    try:  # local runs: borrow the gh CLI login
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        if out.returncode == 0:
            return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def graphql(query, variables, timeout=30):
    """POST a GraphQL query and return its `data`. Raises on transport, auth or GraphQL errors."""
    token = _auth_token()
    if not token:
        raise RuntimeError("no GitHub auth available")
    req = urllib.request.Request(
        API_URL,
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "scttbnsn-profile-card",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.load(resp)
    if payload.get("errors") or not payload.get("data"):
        raise RuntimeError(f"GraphQL error: {payload.get('errors')}")
    return payload["data"]


def _load(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def _save(path, data):
    try:
        path = Path(path)
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(data, indent=1) + "\n")
    except OSError:
        pass


# ---- contribution calendar ----------------------------------------------------------------------

def _valid_calendar(cal):
    try:
        weeks, dates = cal["weeks"], cal["dates"]
        return (isinstance(cal["total"], int) and len(weeks) > 0 and len(weeks) == len(dates)
                and all(isinstance(w, list) and 0 < len(w) <= 7 and all(isinstance(v, int) and v >= 0 for v in w) for w in weeks))
    except (KeyError, TypeError):
        return False


def empty_calendar(today=None):
    """53 weeks of zeros, only used when there is neither a live fetch nor a cache."""
    today = today or datetime.date.today()
    start = today - datetime.timedelta(days=today.weekday() + 1 if today.weekday() != 6 else 0) - datetime.timedelta(weeks=52)
    return {"total": 0, "weeks": [[0] * 7 for _ in range(53)],
            "dates": [(start + datetime.timedelta(weeks=i)).isoformat() for i in range(53)]}


def fetch_calendar(login=USER):
    cal = graphql(CALENDAR_QUERY, {"login": login})["user"]["contributionsCollection"]["contributionCalendar"]
    weeks = [[d["contributionCount"] for d in w["contributionDays"]] for w in cal["weeks"]]
    return {"total": cal["totalContributions"], "weeks": weeks, "dates": [w["firstDay"] for w in cal["weeks"]]}


def get_calendar(cache_path=None):
    """Live calendar, else cached, else an empty one. Never raises, never regresses a good cache."""
    path = cache_path or CALENDAR_CACHE
    cached = _load(path)
    if not _valid_calendar(cached):
        cached = None
    try:
        live = fetch_calendar()
    except Exception:
        live = None
    if live is not None and _valid_calendar(live) and (live["total"] > 0 or cached is None):
        if live != cached:
            _save(path, live)
        return live
    return cached or empty_calendar()


# ---- languages ------------------------------------------------------------------------------------

def aggregate_languages(repo_nodes, excluded=EXCLUDED_LANGUAGES):
    """Sum language bytes over non-fork, non-archived repos. Returns [{name, bytes, color}] by bytes desc."""
    totals = {}
    for repo in repo_nodes:
        if not repo or repo.get("isFork") or repo.get("isArchived"):
            continue
        for edge in (repo.get("languages") or {}).get("edges") or []:
            name = edge["node"]["name"]
            if name in excluded:
                continue
            entry = totals.setdefault(name, {"name": name, "bytes": 0, "color": edge["node"].get("color") or "#8b949e"})
            entry["bytes"] += int(edge["size"])
    return sorted(totals.values(), key=lambda e: (-e["bytes"], e["name"]))


def fetch_repo_nodes(owners=LANGUAGE_OWNERS):
    nodes = []
    for owner in owners:
        after = None
        while True:
            data = graphql(REPOS_QUERY, {"login": owner, "after": after})
            if data["repositoryOwner"] is None:
                raise RuntimeError(f"unknown owner {owner}")
            repos = data["repositoryOwner"]["repositories"]
            nodes.extend(repos["nodes"])
            if not repos["pageInfo"]["hasNextPage"]:
                break
            after = repos["pageInfo"]["endCursor"]
    return nodes


def _valid_languages(langs):
    return (isinstance(langs, list) and len(langs) > 0
            and all(isinstance(l, dict) and {"name", "bytes", "color"} <= l.keys() and l["bytes"] > 0 for l in langs))


def get_languages(cache_path=None):
    """Aggregated language list. Live, else cached, else []. Never raises, never regresses a good cache."""
    path = cache_path or LANGUAGES_CACHE
    cached = _load(path)
    if not _valid_languages(cached):
        cached = None
    try:
        live = aggregate_languages(fetch_repo_nodes())
    except Exception:
        live = None
    if _valid_languages(live):
        if live != cached:
            _save(path, live)
        return live
    return cached or []
