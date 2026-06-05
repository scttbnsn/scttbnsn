#!/usr/bin/env python3
"""
NFO-style GitHub profile preview script.
Run this to see what the profile will look like in terminal.

Usage:
    python3 preview.py              # Show preview with cached/placeholder data
    python3 preview.py --fetch      # Fetch fresh GitHub stats (uses gh CLI)
    python3 preview.py --save       # Save stats to cache file

Requires gh CLI to be installed and authenticated for --fetch.
"""

import os
import sys
import json
import subprocess
from datetime import datetime
from pathlib import Path

# ANSI color codes for terminal preview
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # NFO warez colors
    CYAN = "\033[96m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    WHITE = "\033[97m"
    GRAY = "\033[90m"

    # Background
    BG_BLACK = "\033[40m"


def _load_stats_cache():
    """Load the stats cache file, returning the parsed dict or None."""
    cache_file = Path(__file__).parent / "cache" / "stats.json"
    if cache_file.exists():
        try:
            with open(cache_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, KeyError):
            pass
    return None


def merge_with_cache(live_stats, cached_stats, stat_type):
    """Merge live stats with cached stats using max() for cumulative values.

    Cumulative stats should only go up. This protects against session pruning
    (Claude) and inconsistent API responses (GitHub LOC).

    stat_type: 'claude' or 'github'
    """
    if not cached_stats:
        return live_stats

    merged = dict(live_stats)

    if stat_type == 'claude':
        # All Claude stats are cumulative — use max for every numeric field
        for key in ('sessions', 'messages', 'input_tokens', 'output_tokens',
                     'cache_creation', 'cache_read', 'total_tokens', 'cost_estimate'):
            if key in cached_stats:
                merged[key] = max(merged.get(key, 0), cached_stats[key])
    elif stat_type == 'github':
        # Cumulative fields — use max to protect against partial API responses
        for key in ('commits', 'prs', 'issues', 'contributed_repos',
                     'loc_added', 'loc_deleted', 'loc_total'):
            if key in cached_stats:
                merged[key] = max(merged.get(key, 0), cached_stats[key])
        # repos, stars, followers, following use live values (can legitimately decrease)

    return merged


def _load_checkpoint():
    """Load the checkpoint of already-counted JSONL files."""
    checkpoint_file = Path(__file__).parent / "cache" / "claude_checkpoint.json"
    if checkpoint_file.exists():
        try:
            with open(checkpoint_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, KeyError):
            pass
    return {}


def _save_checkpoint(checkpoint):
    """Save the checkpoint of counted JSONL files."""
    cache_dir = Path(__file__).parent / "cache"
    cache_dir.mkdir(exist_ok=True)
    with open(cache_dir / "claude_checkpoint.json", 'w') as f:
        json.dump(checkpoint, f)


def _count_jsonl_file(filepath):
    """Count tokens/messages in a single JSONL file. Returns stats dict."""
    stats = {'input_tokens': 0, 'output_tokens': 0, 'cache_creation': 0,
             'cache_read': 0, 'messages': 0}
    with open(filepath, 'r') as f:
        for line in f:
            try:
                data = json.loads(line)
                if 'message' in data and isinstance(data['message'], dict):
                    usage = data['message'].get('usage', {})
                    if usage:
                        stats['messages'] += 1
                        stats['input_tokens'] += usage.get('input_tokens', 0)
                        stats['output_tokens'] += usage.get('output_tokens', 0)
                        stats['cache_creation'] += usage.get('cache_creation_input_tokens', 0)
                        stats['cache_read'] += usage.get('cache_read_input_tokens', 0)
            except json.JSONDecodeError:
                continue
    return stats


def get_claude_stats():
    """Parse Claude Code JSONL files using incremental checkpoint.

    Tracks which files have been counted and their sizes. On each run:
    - New files: count fully, add to totals
    - Grown files: re-count, add delta to totals
    - Pruned files: ignored (totals preserved)
    """
    claude_dir = Path.home() / ".claude" / "projects"
    cached = _load_stats_cache()

    if not claude_dir.exists():
        if cached and 'claude' in cached:
            return cached['claude']
        return {
            'input_tokens': 0, 'output_tokens': 0, 'cache_creation': 0,
            'cache_read': 0, 'total_tokens': 0, 'sessions': 0,
            'messages': 0, 'cost_estimate': 0,
        }

    checkpoint = _load_checkpoint()
    counted_files = checkpoint.get('files', {})
    bootstrapping = len(counted_files) == 0

    # Start from cached totals (preserves history from pruned files)
    totals = {
        'input_tokens': 0, 'output_tokens': 0, 'cache_creation': 0,
        'cache_read': 0, 'messages': 0, 'sessions': 0,
    }
    if cached and 'claude' in cached:
        for key in totals:
            totals[key] = cached['claude'].get(key, 0)

    for jsonl_file in claude_dir.rglob("*.jsonl"):
        filepath = str(jsonl_file)
        try:
            file_size = jsonl_file.stat().st_size
        except OSError:
            continue

        prev = counted_files.get(filepath)

        if prev and prev['size'] == file_size:
            # Already fully counted, no change
            continue

        # New or grown file — count it
        try:
            file_stats = _count_jsonl_file(filepath)
        except Exception:
            continue

        if bootstrapping:
            # First run: just record files without adding to totals,
            # since the cache already reflects these files
            counted_files[filepath] = {'size': file_size, **file_stats}
            continue

        if prev:
            # File grew — add only the delta
            for key in ('input_tokens', 'output_tokens', 'cache_creation',
                        'cache_read', 'messages'):
                delta = file_stats[key] - prev.get(key, 0)
                if delta > 0:
                    totals[key] += delta
        else:
            # Brand new file
            totals['sessions'] += 1
            for key in ('input_tokens', 'output_tokens', 'cache_creation',
                        'cache_read', 'messages'):
                totals[key] += file_stats[key]

        counted_files[filepath] = {'size': file_size, **file_stats}

    # Save updated checkpoint
    _save_checkpoint({'files': counted_files})

    # Recalculate derived fields
    totals['total_tokens'] = (totals['input_tokens'] + totals['output_tokens']
                              + totals['cache_creation'] + totals['cache_read'])

    # Cost estimate using Claude pricing
    # Sonnet: $3/MTok input, $15/MTok output
    # Opus: $15/MTok input, $75/MTok output (assume mix, use higher)
    # Cache writes cost same as input, cache reads are 90% cheaper
    input_cost = (totals['input_tokens'] + totals['cache_creation']) * 10 / 1_000_000
    output_cost = totals['output_tokens'] * 30 / 1_000_000
    cache_read_cost = totals['cache_read'] * 1 / 1_000_000
    totals['cost_estimate'] = input_cost + output_cost + cache_read_cost

    return totals


def run_gh_api(endpoint, method="GET"):
    """Run a gh api command and return JSON result."""
    try:
        cmd = ['gh', 'api', endpoint]
        if method != "GET":
            cmd.extend(['-X', method])
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return None


def run_gh_graphql(query, variables=None):
    """Run a gh api graphql query and return JSON result."""
    try:
        cmd = ['gh', 'api', 'graphql', '-f', f'query={query}']
        if variables:
            for key, value in variables.items():
                # Use -F for variable values (handles types correctly)
                cmd.extend(['-F', f'{key}={value}'])
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return None


def get_all_repos(username="scttbnsn"):
    """Get all repos (owned, collaborated, org member) with pagination."""
    all_repos = []
    page = 1
    while True:
        repos = run_gh_api(
            f'user/repos?per_page=100&page={page}'
            f'&affiliation=owner,collaborator,organization_member'
        )
        if not repos or not isinstance(repos, list) or len(repos) == 0:
            break
        all_repos.extend(repos)
        if len(repos) < 100:
            break
        page += 1
    return all_repos


def get_loc_stats(repos, username="scttbnsn"):
    """Fetch lines of code stats by iterating through repos using gh CLI."""
    import time

    total_added = 0
    total_deleted = 0

    try:
        for repo in repos:
            if repo.get('fork'):
                continue  # Skip forks
            owner = repo['owner']['login']
            repo_name = repo['name']

            # Retry up to 3 times (GitHub computes stats on first request)
            for attempt in range(3):
                contributors = run_gh_api(f'repos/{owner}/{repo_name}/stats/contributors')
                if contributors is None:
                    time.sleep(1)
                    continue
                if not isinstance(contributors, list):
                    break

                # Find user's contributions
                for contrib in contributors:
                    author = contrib.get('author')
                    if author and author.get('login', '').lower() == username.lower():
                        for week in contrib.get('weeks', []):
                            total_added += week.get('a', 0)
                            total_deleted += week.get('d', 0)
                        break
                break  # Success, move to next repo

    except Exception as e:
        print(f"Error fetching LOC stats: {e}", file=sys.stderr)

    return {
        'loc_added': total_added,
        'loc_deleted': total_deleted,
        'loc_total': total_added - total_deleted,
    }


def get_all_commits(repos, username="scttbnsn"):
    """Get total commits across all repos using gh CLI."""
    total_commits = 0

    # First get the user's node ID for filtering commits
    id_query = "query($login: String!) { user(login: $login) { id } }"
    id_data = run_gh_graphql(id_query, {'login': username})
    if not id_data or 'data' not in id_data:
        return 0
    user_id = id_data['data']['user']['id']

    # Query each repo for commits by this user
    repo_query = """
    query($owner: String!, $name: String!, $authorId: ID!) {
        repository(owner: $owner, name: $name) {
            defaultBranchRef {
                target {
                    ... on Commit {
                        history(first: 0, author: {id: $authorId}) {
                            totalCount
                        }
                    }
                }
            }
        }
    }
    """

    for repo in repos:
        owner = repo['owner']['login']
        name = repo['name']

        commit_data = run_gh_graphql(repo_query, {
            'owner': owner,
            'name': name,
            'authorId': user_id
        })

        if commit_data and 'data' in commit_data:
            repo_data = commit_data['data'].get('repository')
            if repo_data and repo_data.get('defaultBranchRef'):
                target = repo_data['defaultBranchRef'].get('target')
                if target and target.get('history'):
                    total_commits += target['history']['totalCount']

    return total_commits


def get_github_stats(username="scttbnsn"):
    """Fetch GitHub stats via gh CLI GraphQL."""
    # Check if gh CLI is available
    try:
        result = subprocess.run(['gh', 'auth', 'status'], capture_output=True, text=True)
        if result.returncode != 0:
            raise FileNotFoundError("gh not authenticated")
    except FileNotFoundError:
        # Fall back to cached data
        cache_file = Path(__file__).parent / "cache" / "github_stats.json"
        if cache_file.exists():
            with open(cache_file) as f:
                return json.load(f)
        return {
            'repos': 0,
            'commits': 0,
            'stars': 0,
            'followers': 0,
            'following': 0,
            'loc_added': 0,
            'loc_deleted': 0,
            'contributed_repos': 0,
            'prs': 0,
            'issues': 0,
        }

    # GraphQL query for user-level stats (not repo-dependent)
    query = """
    query($login: String!) {
        user(login: $login) {
            followers {
                totalCount
            }
            following {
                totalCount
            }
            repositoriesContributedTo(first: 0, contributionTypes: [COMMIT, PULL_REQUEST]) {
                totalCount
            }
            pullRequests(first: 0) {
                totalCount
            }
            issues(first: 0) {
                totalCount
            }
        }
    }
    """

    data = run_gh_graphql(query, {'login': username})
    if not data or 'errors' in data:
        print(f"GitHub API error: {data.get('errors', 'Unknown error') if data else 'No response'}", file=sys.stderr)
        cache_file = Path(__file__).parent / "cache" / "github_stats.json"
        if cache_file.exists():
            with open(cache_file) as f:
                return json.load(f)
        return {'repos': 0, 'commits': 0, 'stars': 0, 'followers': 0, 'following': 0,
                'loc_added': 0, 'loc_deleted': 0, 'contributed_repos': 0, 'prs': 0, 'issues': 0}

    user = data['data']['user']

    # Fetch all repos with pagination (shared across commits/LOC/stars)
    all_repos = get_all_repos(username)

    # Calculate total stars from all repos
    total_stars = sum(repo.get('stargazers_count', 0) for repo in all_repos)

    # Get ALL commits across all repos (not just contribution graph)
    total_commits = get_all_commits(all_repos, username)

    # Get PRs and issues from user totals
    total_prs = user['pullRequests']['totalCount']
    total_issues = user['issues']['totalCount']

    # Get LOC stats (separate API calls, uses same repo list)
    loc_stats = get_loc_stats(all_repos, username)

    live_stats = {
        'repos': len(all_repos),
        'commits': total_commits,
        'stars': total_stars,
        'followers': user['followers']['totalCount'],
        'following': user['following']['totalCount'],
        'contributed_repos': user['repositoriesContributedTo']['totalCount'],
        'prs': total_prs,
        'issues': total_issues,
        'loc_added': loc_stats['loc_added'],
        'loc_deleted': loc_stats['loc_deleted'],
        'loc_total': loc_stats['loc_total'],
    }

    # Merge with cache — cumulative stats should only go up
    cached = _load_stats_cache()
    return merge_with_cache(live_stats, cached.get('github') if cached else None, 'github')


def save_stats_cache(claude_stats, github_stats):
    """Save stats to cache file."""
    cache_dir = Path(__file__).parent / "cache"
    cache_dir.mkdir(exist_ok=True)

    cache_data = {
        'timestamp': datetime.now().isoformat(),
        'claude': claude_stats,
        'github': github_stats,
    }

    with open(cache_dir / "stats.json", 'w') as f:
        json.dump(cache_data, f, indent=2)

    # Also save GitHub stats separately for when we don't have a token
    with open(cache_dir / "github_stats.json", 'w') as f:
        json.dump(github_stats, f, indent=2)


def format_number(n):
    """Format number with commas."""
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.1f}B"
    elif n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def render_nfo(fetch_github=False):
    """Render the NFO-style profile to terminal."""
    c = Colors

    # Get stats
    claude = get_claude_stats()

    if fetch_github:
        github = get_github_stats()
    else:
        # Load from cache when not fetching
        cache_file = Path(__file__).parent / "cache" / "github_stats.json"
        if cache_file.exists():
            with open(cache_file) as f:
                github = json.load(f)
        else:
            github = {'repos': 0, 'commits': 0, 'stars': 0, 'followers': 0, 'following': 0,
                     'loc_added': 0, 'loc_deleted': 0, 'contributed_repos': 0, 'prs': 0, 'issues': 0}

    # NFO template - 100 chars wide max (matching Andrew6rant's ~985px)
    width = 98

    # Header box characters
    TL, TR, BL, BR = '╔', '╗', '╚', '╝'
    H, V = '═', '║'
    LT, RT = '╠', '╣'

    # Separator
    sep = f"{c.CYAN}{LT}{H * (width-2)}{RT}{c.RESET}"
    top = f"{c.CYAN}{TL}{H * (width-2)}{TR}{c.RESET}"
    bot = f"{c.CYAN}{BL}{H * (width-2)}{BR}{c.RESET}"

    def line(content="", align="left"):
        """Create a bordered line."""
        visible_len = len(content.replace(c.RESET, "").replace(c.CYAN, "").replace(c.BLUE, "")
                         .replace(c.MAGENTA, "").replace(c.GREEN, "").replace(c.RED, "")
                         .replace(c.YELLOW, "").replace(c.WHITE, "").replace(c.GRAY, "")
                         .replace(c.BOLD, "").replace(c.DIM, ""))
        padding = width - 4 - visible_len
        if align == "center":
            left_pad = padding // 2
            right_pad = padding - left_pad
            return f"{c.CYAN}{V}{c.RESET} {' ' * left_pad}{content}{' ' * right_pad} {c.CYAN}{V}{c.RESET}"
        return f"{c.CYAN}{V}{c.RESET} {content}{' ' * padding} {c.CYAN}{V}{c.RESET}"

    def stat_line(key, value, dots=True):
        """Create a stats line with dot leaders."""
        key_str = f"{c.YELLOW}{key}{c.RESET}"
        val_str = f"{c.WHITE}{value}{c.RESET}"
        key_len = len(key)
        val_len = len(str(value))
        if dots:
            dot_count = width - 8 - key_len - val_len
            dots_str = f"{c.GRAY}{'.' * dot_count}{c.RESET}"
            return line(f"{key_str}: {dots_str} {val_str}")
        return line(f"{key_str}: {val_str}")

    # Build the NFO
    output = []

    # Top border
    output.append(top)
    output.append(line())

    # Warez-style ASCII art header with shaded blocks
    header_art = [
        f"{c.GRAY}                          ▄▄▄████████▄▄▄{c.RESET}",
        f"{c.GRAY}                      ▄█████{c.CYAN}▀▀▀▀▀▀▀▀{c.GRAY}█████▄{c.RESET}",
        f"{c.GRAY}                   ▄███{c.CYAN}▀{c.GRAY}▀            ▀{c.CYAN}▀{c.GRAY}███▄{c.RESET}",
        f"{c.GRAY}                 ▄██{c.CYAN}▀  {c.MAGENTA}░▒▓█████████▓▒░{c.CYAN}  ▀{c.GRAY}██▄{c.RESET}",
        f"{c.GRAY}                ▐█{c.CYAN}▀   {c.MAGENTA}▓███████████████▓{c.CYAN}   ▀{c.GRAY}█▌{c.RESET}",
        f"{c.GRAY}               ▐█{c.CYAN}    {c.MAGENTA}████▀▀▀▀▀▀▀▀▀▀████{c.CYAN}    {c.GRAY}█▌{c.RESET}",
        f"{c.GRAY}               █{c.CYAN}    {c.MAGENTA}███▀{c.RESET} S B E N S O N {c.MAGENTA}▀███{c.CYAN}    {c.GRAY}█{c.RESET}",
        f"{c.GRAY}               █{c.CYAN}    {c.MAGENTA}███▄▄▄▄▄▄▄▄▄▄▄▄▄███{c.CYAN}    {c.GRAY}█{c.RESET}",
        f"{c.GRAY}               ▐█{c.CYAN}    {c.MAGENTA}▀███████████████▀{c.CYAN}    {c.GRAY}█▌{c.RESET}",
        f"{c.GRAY}                ▐█{c.CYAN}▄   {c.MAGENTA}▀▓███████████▓▀{c.CYAN}   ▄{c.GRAY}█▌{c.RESET}",
        f"{c.GRAY}                 ▀██{c.CYAN}▄  {c.MAGENTA}░▒▓███████▓▒░{c.CYAN}  ▄{c.GRAY}██▀{c.RESET}",
        f"{c.GRAY}                   ▀███{c.CYAN}▄▄{c.GRAY}            {c.CYAN}▄▄{c.GRAY}███▀{c.RESET}",
        f"{c.GRAY}                      ▀█████{c.CYAN}▄▄▄▄▄▄▄▄{c.GRAY}█████▀{c.RESET}",
        f"{c.GRAY}                          ▀▀▀████████▀▀▀{c.RESET}",
    ]

    for l in header_art:
        output.append(line(l, "center"))

    output.append(line())
    output.append(line(f"{c.CYAN}ai developer  ·  ai whisperer{c.RESET}", "center"))
    output.append(line())

    # Section separator with warez-style header
    output.append(sep)
    output.append(line())
    output.append(line(f"{c.CYAN}▄▀▀  ▀▀▄ ▄▀▀  ▀▀▀█ ▄▀▀  ▄▀▄▀▄    ▀ ▄▀▀▄ ▄▀▀  ▄▀▀▄{c.RESET}", "center"))
    output.append(line(f"{c.CYAN}▀▀█  ▀▀  ▀▀█   ▀▀   ▓▀   █ ▀ █    █ █  ▓ ▓▀   █  ▓{c.RESET}", "center"))
    output.append(line(f"{c.CYAN}▀▀▀  ▀    ▀▀   ▀    ▀▀▀  ▀   ▀    ▀ ▀    ▀▀▀   ▀▀ {c.RESET}", "center"))
    output.append(line())
    output.append(sep)
    output.append(line())

    # System info section
    output.append(stat_line("Location", "Bridge and/or Tunnel"))
    output.append(stat_line("Uptime", "30+ years"))
    output.append(stat_line("Shell", "zsh + tmux + neovim"))
    output.append(stat_line("Languages", "TypeScript, Python, Rust, Go"))
    output.append(stat_line("Focus", "AI/ML, Developer Tools, Infrastructure"))
    output.append(line())

    # Claude Code stats section with warez header
    output.append(sep)
    output.append(line())
    output.append(line(f"{c.MAGENTA}▄▀▀  ▓   ▄▀▀▄ ▓  ▄ ▄▀▀▄ ▄▀▀    ▄▀▀  ▄▀▀▄ ▄▀▀▄ ▄▀▀ {c.RESET}", "center"))
    output.append(line(f"{c.MAGENTA}█    █   █▀▀▓ █  ▓ █  ▓ ▓▀     █    █  ▓ █  ▓ ▓▀  {c.RESET}", "center"))
    output.append(line(f"{c.MAGENTA} ▀▀  ▀▀▀ ▀    ▀▀▀▀ ▀▀▀▀ ▀▀▀     ▀▀   ▀▀  ▀▀▀▀ ▀▀▀ {c.RESET}", "center"))
    output.append(line())
    output.append(sep)
    output.append(line())

    output.append(stat_line("Sessions", format_number(claude['sessions'])))
    output.append(stat_line("Messages", format_number(claude['messages'])))
    output.append(stat_line("Input Tokens", format_number(claude['input_tokens'])))
    output.append(stat_line("Output Tokens", format_number(claude['output_tokens'])))
    output.append(stat_line("Cache Created", format_number(claude['cache_creation'])))
    output.append(stat_line("Cache Read", format_number(claude['cache_read'])))
    output.append(stat_line("Total Tokens", format_number(claude['total_tokens'])))
    output.append(stat_line("Est. API Cost", f"${claude['cost_estimate']:,.2f}"))
    output.append(line())

    # GitHub stats section with warez header
    output.append(sep)
    output.append(line())
    output.append(line(f"{c.GREEN}▄▀▀  ▀ ▀▀▀█ ▓  ▄ ▓  ▄ ▄▀▀   ▄▀▀  ▀▀▀█ ▄▀▀▄ ▀▀▀█ ▄▀▀ {c.RESET}", "center"))
    output.append(line(f"{c.GREEN}█ ▀▓ █  ▀▀  █▀▀▓ █  ▓ ▀▀█   ▀▀█   ▀▀  █▀▀▓  ▀▀  ▀▀█ {c.RESET}", "center"))
    output.append(line(f"{c.GREEN} ▀▀  ▀  ▀   ▀  ▀ ▀▀▀▀ ▀▀▀   ▀▀▀   ▀   ▀  ▀  ▀   ▀▀▀ {c.RESET}", "center"))
    output.append(line())
    output.append(sep)
    output.append(line())

    output.append(stat_line("Repositories", github.get('repos', 0)))
    output.append(stat_line("Contributed To", github.get('contributed_repos', 0)))
    output.append(stat_line("Total Commits", format_number(github.get('commits', 0))))
    output.append(stat_line("Pull Requests", github.get('prs', 0)))
    output.append(stat_line("Stars Earned", github.get('stars', 0)))
    output.append(stat_line("Followers", github.get('followers', 0)))
    output.append(line())

    # Contact section with warez header
    output.append(sep)
    output.append(line())
    output.append(line(f"{c.YELLOW}▄▀▀  ▄▀▀▄ ▄▀▀▄ ▀▀▀█ ▄▀▀▄ ▄▀▀  ▀▀▀█{c.RESET}", "center"))
    output.append(line(f"{c.YELLOW}█    █  ▓ █  ▓  ▀▀  █▀▀▓ █     ▀▀ {c.RESET}", "center"))
    output.append(line(f"{c.YELLOW} ▀▀   ▀▀  ▀  ▀  ▀   ▀  ▀  ▀▀   ▀  {c.RESET}", "center"))
    output.append(line())
    output.append(sep)
    output.append(line())

    output.append(stat_line("GitHub", "github.com/scttbnsn"))
    output.append(stat_line("Location", "Bridge and/or Tunnel"))
    output.append(line())

    # Footer with warez greet
    output.append(sep)
    output.append(line())
    output.append(line(f"{c.GRAY}\" greetz to all the ai pioneers out there \"{c.RESET}", "center"))
    output.append(line())
    output.append(line(f"{c.DIM}Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{c.RESET}", "center"))
    output.append(line())
    output.append(bot)

    return "\n".join(output)


if __name__ == "__main__":
    fetch = "--fetch" in sys.argv
    save = "--save" in sys.argv

    if fetch or save:
        # Get fresh stats
        claude = get_claude_stats()
        github = get_github_stats()

        if save:
            save_stats_cache(claude, github)
            print("Stats cached to cache/stats.json")

    print(render_nfo(fetch_github=fetch))
