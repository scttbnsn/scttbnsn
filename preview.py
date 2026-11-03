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
import hashlib
from datetime import datetime, timezone
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


CLAUDE_TOKEN_KEYS = ('input_tokens', 'output_tokens', 'cache_creation', 'cache_read')
CLAUDE_CHECKPOINT_VERSION = 3


def _empty_claude_stats():
    return {
        'input_tokens': 0, 'output_tokens': 0, 'cache_creation': 0,
        'cache_read': 0, 'total_tokens': 0, 'sessions': 0,
        'messages': 0, 'cost_estimate': 0,
    }


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


def _usage_entry_from_json(data):
    """Return a normalized usage entry from a Claude JSONL object."""
    message = data.get('message')
    if not isinstance(message, dict):
        return None

    usage = message.get('usage', {})
    if not usage:
        return None

    message_id = message.get('id') or data.get('uuid')
    if not message_id:
        return None

    return {
        'message_id': message_id,
        'timestamp': data.get('timestamp', ''),
        'session_id': data.get('sessionId'),
        'input_tokens': usage.get('input_tokens', 0),
        'output_tokens': usage.get('output_tokens', 0),
        'cache_creation': usage.get('cache_creation_input_tokens', 0),
        'cache_read': usage.get('cache_read_input_tokens', 0),
    }


def _checkpoint_entry(entry):
    """Trim scanner-only fields before persisting a message checkpoint."""
    saved = {key: entry.get(key, 0) for key in CLAUDE_TOKEN_KEYS}
    saved['timestamp'] = entry.get('timestamp', '')
    if entry.get('session_id'):
        saved['session_id'] = entry['session_id']
    saved['fingerprint'] = _message_fingerprint(entry)
    return saved


def _message_fingerprint(entry):
    """Return a stable fingerprint for one counted Claude usage record."""
    payload = {
        'message_id': entry.get('message_id'),
        'timestamp': entry.get('timestamp', ''),
        'session_id': entry.get('session_id'),
    }
    for key in CLAUDE_TOKEN_KEYS:
        payload[key] = entry.get(key, 0)

    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def _messages_fingerprint(messages):
    """Return a stable fingerprint for the visible deduped message set."""
    digest = hashlib.sha256()
    for message_id in sorted(messages):
        digest.update(message_id.encode())
        digest.update(b'\0')
        digest.update(_message_fingerprint(messages[message_id]).encode())
        digest.update(b'\0')
    return digest.hexdigest()


def _scan_claude_messages(claude_dir):
    """Scan visible Claude logs, deduping repeated message IDs.

    Claude JSONL logs can contain the same assistant message more than once.
    Keep the latest record for each message ID, matching ccusage's effective
    accounting and avoiding inflated totals from copied or rewritten records.
    """
    messages = {}
    sessions = set()
    order = 0

    for jsonl_file in sorted(claude_dir.rglob("*.jsonl")):
        try:
            with open(jsonl_file, 'r') as f:
                for line in f:
                    order += 1
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    entry = _usage_entry_from_json(data)
                    if not entry:
                        continue

                    session_id = entry.get('session_id')
                    if session_id:
                        sessions.add(session_id)

                    message_id = entry['message_id']
                    previous = messages.get(message_id)
                    if (
                        previous is None
                        or (entry.get('timestamp', ''), order)
                        >= (previous.get('timestamp', ''), previous.get('_order', 0))
                    ):
                        entry['_order'] = order
                        messages[message_id] = entry
        except OSError:
            continue

    return messages, sessions


def _sum_message_entries(messages):
    """Sum deduped message entries into the public Claude stats shape."""
    totals = _empty_claude_stats()
    totals['messages'] = len(messages)

    for entry in messages.values():
        for key in CLAUDE_TOKEN_KEYS:
            totals[key] += entry.get(key, 0)

    return totals


def _finalize_claude_totals(totals):
    """Recalculate derived Claude stats."""
    totals['total_tokens'] = sum(totals[key] for key in CLAUDE_TOKEN_KEYS)

    # Cost estimate using Claude pricing
    # Sonnet: $3/MTok input, $15/MTok output
    # Opus: $15/MTok input, $75/MTok output (assume mix, use higher)
    # Cache writes cost same as input, cache reads are 90% cheaper
    input_cost = (totals['input_tokens'] + totals['cache_creation']) * 10 / 1_000_000
    output_cost = totals['output_tokens'] * 30 / 1_000_000
    cache_read_cost = totals['cache_read'] * 1 / 1_000_000
    totals['cost_estimate'] = input_cost + output_cost + cache_read_cost
    return totals


def _empty_usage_stats():
    stats = _empty_claude_stats()
    stats['providers'] = {}
    return stats


def _number(value, default=0):
    return value if isinstance(value, (int, float)) else default


def _normalize_ccusage_totals(totals):
    """Convert ccusage totals JSON into this script's token stat shape."""
    if not isinstance(totals, dict):
        return _empty_claude_stats()

    stats = {
        'input_tokens': _number(totals.get('inputTokens')),
        'output_tokens': _number(totals.get('outputTokens')),
        'cache_creation': _number(totals.get('cacheCreationTokens')),
        'cache_read': _number(totals.get('cacheReadTokens')),
        'sessions': 0,
        'messages': 0,
        'cost_estimate': _number(totals.get('totalCost')),
    }
    stats['total_tokens'] = _number(
        totals.get('totalTokens'),
        sum(stats[key] for key in CLAUDE_TOKEN_KEYS),
    )
    return stats


def _subtract_usage_stats(total_stats, subtract_stats):
    """Return token stats in total_stats that are not in subtract_stats."""
    stats = _empty_claude_stats()
    for key in CLAUDE_TOKEN_KEYS:
        stats[key] = max(total_stats.get(key, 0) - subtract_stats.get(key, 0), 0)
    stats['total_tokens'] = sum(stats[key] for key in CLAUDE_TOKEN_KEYS)
    stats['cost_estimate'] = max(
        total_stats.get('cost_estimate', 0) - subtract_stats.get('cost_estimate', 0),
        0,
    )
    return stats


def _combine_usage_stats(claude_stats, other_stats):
    """Combine the preserved Claude baseline with non-Claude provider usage."""
    combined = dict(claude_stats)
    for key in CLAUDE_TOKEN_KEYS:
        combined[key] = claude_stats.get(key, 0) + other_stats.get(key, 0)
    combined['total_tokens'] = sum(combined[key] for key in CLAUDE_TOKEN_KEYS)
    combined['cost_estimate'] = (
        claude_stats.get('cost_estimate', 0) + other_stats.get('cost_estimate', 0)
    )
    combined['sessions'] = claude_stats.get('sessions', 0) + other_stats.get('sessions', 0)
    combined['messages'] = claude_stats.get('messages', 0) + other_stats.get('messages', 0)
    combined['providers'] = {
        'claude': dict(claude_stats),
        'other': dict(other_stats),
    }
    return combined


def _get_ccusage_totals(agent=None):
    """Return ccusage daily totals, or None when ccusage is unavailable."""
    cmd = ['npx', '-y', 'ccusage@latest']
    if agent:
        cmd.append(agent)
    cmd.extend(['daily', '--json', '--offline'])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    return data.get('totals') if isinstance(data, dict) else None


OTHER_USAGE_KEYS = CLAUDE_TOKEN_KEYS + ('total_tokens', 'sessions', 'messages', 'cost_estimate')


def _cached_other_usage(cached_stats):
    """Return the non-Claude usage recorded in the cache, or zeros.

    Prefers the stored token_usage.providers.other. Older caches only have
    token_usage and claude, so derive other as the difference per key.
    """
    other = _empty_claude_stats()
    if not isinstance(cached_stats, dict):
        return other

    token_usage = cached_stats.get('token_usage')
    if not isinstance(token_usage, dict):
        return other

    providers = token_usage.get('providers')
    stored = providers.get('other') if isinstance(providers, dict) else None
    if isinstance(stored, dict):
        for key in OTHER_USAGE_KEYS:
            other[key] = max(_number(stored.get(key)), 0)
        return other

    cached_claude = cached_stats.get('claude')
    cached_claude = cached_claude if isinstance(cached_claude, dict) else {}
    for key in OTHER_USAGE_KEYS:
        other[key] = max(_number(token_usage.get(key)) - _number(cached_claude.get(key)), 0)
    return other


def get_token_usage_stats(claude_stats=None):
    """Return all-provider token usage for the profile SVG.

    Claude uses this repo's preserved all-time baseline. Non-Claude providers
    come from ccusage by subtracting current visible Claude usage from current
    visible all-provider usage, preventing visible Claude logs from being
    counted twice.

    Non-Claude usage never regresses below the cached value. CI has no ccusage
    or local logs, and local logs can rotate away, so a fresh reading lower
    than the cache (or no reading) must not shrink the card.
    """
    claude_stats = claude_stats or get_claude_stats()

    fresh_other = _empty_claude_stats()
    all_totals = _get_ccusage_totals()
    visible_claude_totals = _get_ccusage_totals('claude')
    if all_totals is not None and visible_claude_totals is not None:
        all_stats = _normalize_ccusage_totals(all_totals)
        visible_claude_stats = _normalize_ccusage_totals(visible_claude_totals)
        fresh_other = _subtract_usage_stats(all_stats, visible_claude_stats)

    cached_other = _cached_other_usage(_load_stats_cache())
    other_stats = {
        key: max(fresh_other.get(key, 0), cached_other.get(key, 0))
        for key in OTHER_USAGE_KEYS
    }
    other_stats['total_tokens'] = sum(other_stats[key] for key in CLAUDE_TOKEN_KEYS)
    return _combine_usage_stats(claude_stats, other_stats)


def _parse_cache_timestamp(cached_stats):
    """Return the cache timestamp in UTC, if available."""
    if not cached_stats:
        return None

    timestamp = cached_stats.get('timestamp')
    if not timestamp:
        return None

    try:
        dt = datetime.fromisoformat(timestamp)
    except ValueError:
        return None

    if dt.tzinfo is None:
        # Cache timestamps are written with datetime.now().isoformat(), so
        # naive values represent the local machine timezone.
        dt = dt.astimezone()

    return dt.astimezone(timezone.utc)


def _parse_usage_timestamp(entry):
    """Return a usage entry timestamp in UTC, if available."""
    timestamp = entry.get('timestamp')
    if not timestamp:
        return None

    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    except ValueError:
        return None

    if dt.tzinfo is None:
        dt = dt.astimezone()

    return dt.astimezone(timezone.utc)


def _legacy_cache_baseline(cached_stats, visible_messages, visible_sessions):
    """Preserve older all-time totals and add only post-cache deduped usage."""
    if not cached_stats or 'claude' not in cached_stats:
        return None

    cached_claude = cached_stats['claude']
    visible_totals = _sum_message_entries(visible_messages)
    visible_totals['sessions'] = len(visible_sessions)
    visible_totals = _finalize_claude_totals(visible_totals)

    if cached_claude.get('total_tokens', 0) <= visible_totals['total_tokens']:
        return visible_totals, 'visible_logs'

    totals = _empty_claude_stats()
    for key in totals.keys():
        totals[key] = cached_claude.get(key, 0)

    cache_time = _parse_cache_timestamp(cached_stats)
    if cache_time is None:
        return _finalize_claude_totals(totals), 'legacy_cache'

    new_sessions = set()
    for entry in visible_messages.values():
        usage_time = _parse_usage_timestamp(entry)
        if usage_time is None or usage_time <= cache_time:
            continue

        totals['messages'] += 1
        if entry.get('session_id'):
            new_sessions.add(entry['session_id'])
        for key in CLAUDE_TOKEN_KEYS:
            totals[key] += entry.get(key, 0)

    totals['sessions'] += len(new_sessions)
    return _finalize_claude_totals(totals), 'legacy_cache'


def _checkpoint_baseline(source, totals, cached_stats, visible_messages):
    """Build metadata describing the all-time baseline the checkpoint extends."""
    baseline = {
        'source': source,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'totals': dict(totals),
        'visible_message_count': len(visible_messages),
        'visible_fingerprint': _messages_fingerprint(visible_messages),
    }
    if cached_stats and cached_stats.get('timestamp'):
        baseline['cache_timestamp'] = cached_stats['timestamp']
    return baseline


def get_claude_stats():
    """Parse Claude Code JSONL files using message-ID dedupe.

    Tracks which message IDs have been counted. On each run:
    - Repeated message IDs: count only the latest usage record
    - New messages: add full usage to cached cumulative totals
    - Updated messages: add only positive token deltas
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
    checkpoint_messages = checkpoint.get('messages')
    visible_messages, visible_sessions = _scan_claude_messages(claude_dir)

    # Migrate old file-size checkpoints, or create a first checkpoint, from
    # the currently visible logs. When an older cache already has a larger
    # all-time total than the retained logs can reproduce, preserve that
    # baseline and only add deduped usage newer than the cache timestamp.
    if not isinstance(checkpoint_messages, dict):
        baseline_result = _legacy_cache_baseline(cached, visible_messages, visible_sessions)
        if baseline_result is None:
            totals = _sum_message_entries(visible_messages)
            totals['sessions'] = len(visible_sessions)
            totals = _finalize_claude_totals(totals)
            baseline_source = 'visible_logs'
        else:
            totals, baseline_source = baseline_result
        _save_checkpoint({
            'version': CLAUDE_CHECKPOINT_VERSION,
            'messages': {
                message_id: _checkpoint_entry(entry)
                for message_id, entry in visible_messages.items()
            },
            'sessions': sorted(visible_sessions),
            'totals': totals,
            'baseline': _checkpoint_baseline(
                baseline_source, totals, cached, visible_messages
            ),
        })
        return totals

    # Start from v2 checkpoint totals to preserve already-counted pruned logs,
    # rebuilding from message entries if needed and falling back to cache only
    # for older checkpoints. Then add only new message IDs or positive deltas
    # for messages that grew.
    totals = _empty_claude_stats()
    known_sessions = set(checkpoint.get('sessions', []))
    checkpoint_totals = checkpoint.get('totals')
    if isinstance(checkpoint_totals, dict):
        for key in totals.keys():
            totals[key] = checkpoint_totals.get(key, 0)
    elif checkpoint_messages:
        totals = _sum_message_entries(checkpoint_messages)
        totals['sessions'] = len(known_sessions)
    elif cached and 'claude' in cached:
        for key in totals.keys():
            totals[key] = cached['claude'].get(key, 0)

    for message_id, entry in visible_messages.items():
        current = _checkpoint_entry(entry)
        previous = checkpoint_messages.get(message_id)

        if previous:
            if current.get('fingerprint') != previous.get('fingerprint'):
                for key in CLAUDE_TOKEN_KEYS:
                    delta = current.get(key, 0) - previous.get(key, 0)
                    if delta > 0:
                        totals[key] += delta
            if current.get('session_id'):
                known_sessions.add(current['session_id'])
        else:
            totals['messages'] += 1
            for key in CLAUDE_TOKEN_KEYS:
                totals[key] += current.get(key, 0)
            if current.get('session_id') and current['session_id'] not in known_sessions:
                totals['sessions'] += 1
                known_sessions.add(current['session_id'])
        checkpoint_messages[message_id] = current

    totals = _finalize_claude_totals(totals)

    _save_checkpoint({
        'version': CLAUDE_CHECKPOINT_VERSION,
        'messages': checkpoint_messages,
        'sessions': sorted(known_sessions),
        'totals': totals,
        'baseline': checkpoint.get('baseline') or _checkpoint_baseline(
            'checkpoint_totals', totals, cached, visible_messages
        ),
    })

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


def save_stats_cache(claude_stats, github_stats, token_usage_stats=None):
    """Save stats to cache file."""
    cache_dir = Path(__file__).parent / "cache"
    cache_dir.mkdir(exist_ok=True)
    token_usage_stats = token_usage_stats or claude_stats

    cache_data = {
        'timestamp': datetime.now().isoformat(),
        'claude': claude_stats,
        'token_usage': token_usage_stats,
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
        token_usage = get_token_usage_stats(claude)
        github = get_github_stats()

        if save:
            save_stats_cache(claude, github, token_usage)
            print("Stats cached to cache/stats.json")

    print(render_nfo(fetch_github=fetch))
