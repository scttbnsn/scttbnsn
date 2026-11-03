import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import preview


def write_usage_line(path, message_id, output_tokens, timestamp):
    data = {
        "timestamp": timestamp,
        "message": {
            "id": message_id,
            "usage": {
                "input_tokens": 10,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": 100,
                "cache_read_input_tokens": 1000,
            },
        },
    }
    with path.open("a") as f:
        f.write(json.dumps(data) + "\n")


class ClaudeStatsTests(unittest.TestCase):
    def test_get_token_usage_stats_adds_non_claude_ccusage_without_double_counting_claude(self):
        claude_all_time = {
            "input_tokens": 1000,
            "output_tokens": 2000,
            "cache_creation": 3000,
            "cache_read": 4000,
            "total_tokens": 10000,
            "sessions": 9,
            "messages": 99,
            "cost_estimate": 123,
        }
        all_ccusage = {
            "inputTokens": 110,
            "outputTokens": 220,
            "cacheCreationTokens": 330,
            "cacheReadTokens": 440,
            "totalTokens": 1100,
            "totalCost": 11,
        }
        claude_ccusage = {
            "inputTokens": 10,
            "outputTokens": 20,
            "cacheCreationTokens": 30,
            "cacheReadTokens": 40,
            "totalTokens": 100,
            "totalCost": 1,
        }

        with (
            mock.patch.object(preview, "get_claude_stats", return_value=claude_all_time),
            mock.patch.object(preview, "_load_stats_cache", return_value=None),
            mock.patch.object(
                preview,
                "_get_ccusage_totals",
                side_effect=[all_ccusage, claude_ccusage],
            ),
        ):
            stats = preview.get_token_usage_stats()

        self.assertEqual(stats["input_tokens"], 1100)
        self.assertEqual(stats["output_tokens"], 2200)
        self.assertEqual(stats["cache_creation"], 3300)
        self.assertEqual(stats["cache_read"], 4400)
        self.assertEqual(stats["total_tokens"], 11000)
        self.assertEqual(stats["cost_estimate"], 133)
        self.assertEqual(stats["sessions"], 9)
        self.assertEqual(stats["messages"], 99)
        self.assertEqual(stats["providers"]["claude"]["total_tokens"], 10000)
        self.assertEqual(stats["providers"]["other"]["total_tokens"], 1000)

    def test_get_claude_stats_dedupes_message_ids_using_latest_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            project_dir = home / ".claude" / "projects" / "example"
            project_dir.mkdir(parents=True)
            write_usage_line(
                project_dir / "a.jsonl",
                "msg_1",
                output_tokens=2,
                timestamp="2026-06-26T10:00:00Z",
            )
            write_usage_line(
                project_dir / "b.jsonl",
                "msg_1",
                output_tokens=7,
                timestamp="2026-06-26T10:00:01Z",
            )

            saved_checkpoints = []
            with (
                mock.patch.object(preview.Path, "home", return_value=home),
                mock.patch.object(preview, "_load_stats_cache", return_value=None),
                mock.patch.object(preview, "_load_checkpoint", return_value={"files": {"old": {}}}),
                mock.patch.object(preview, "_save_checkpoint", side_effect=saved_checkpoints.append),
            ):
                stats = preview.get_claude_stats()

        self.assertEqual(stats["messages"], 1)
        self.assertEqual(stats["input_tokens"], 10)
        self.assertEqual(stats["output_tokens"], 7)
        self.assertEqual(stats["cache_creation"], 100)
        self.assertEqual(stats["cache_read"], 1000)
        self.assertEqual(stats["total_tokens"], 1117)
        self.assertIn("messages", saved_checkpoints[0])
        self.assertIn("msg_1", saved_checkpoints[0]["messages"])

    def test_get_claude_stats_preserves_legacy_all_time_cache_on_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            project_dir = home / ".claude" / "projects" / "example"
            project_dir.mkdir(parents=True)
            write_usage_line(
                project_dir / "a.jsonl",
                "msg_old",
                output_tokens=7,
                timestamp="2026-06-26T10:00:00Z",
            )
            write_usage_line(
                project_dir / "b.jsonl",
                "msg_new",
                output_tokens=11,
                timestamp="2026-06-26T10:10:00Z",
            )

            cached = {
                "timestamp": "2026-06-26T10:05:00+00:00",
                "claude": {
                    "input_tokens": 1000,
                    "output_tokens": 1000,
                    "cache_creation": 1000,
                    "cache_read": 1000,
                    "total_tokens": 4000,
                    "sessions": 99,
                    "messages": 99,
                    "cost_estimate": 99,
                },
            }
            saved_checkpoints = []
            with (
                mock.patch.object(preview.Path, "home", return_value=home),
                mock.patch.object(preview, "_load_stats_cache", return_value=cached),
                mock.patch.object(preview, "_load_checkpoint", return_value={"files": {"old": {}}}),
                mock.patch.object(preview, "_save_checkpoint", side_effect=saved_checkpoints.append),
            ):
                stats = preview.get_claude_stats()

        self.assertEqual(stats["messages"], 100)
        self.assertEqual(stats["sessions"], 99)
        self.assertEqual(stats["input_tokens"], 1010)
        self.assertEqual(stats["output_tokens"], 1011)
        self.assertEqual(stats["cache_creation"], 1100)
        self.assertEqual(stats["cache_read"], 2000)
        self.assertEqual(stats["total_tokens"], 5121)
        self.assertEqual(saved_checkpoints[0]["totals"]["total_tokens"], 5121)

    def test_get_claude_stats_saves_baseline_and_message_fingerprints_on_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            project_dir = home / ".claude" / "projects" / "example"
            project_dir.mkdir(parents=True)
            write_usage_line(
                project_dir / "a.jsonl",
                "msg_1",
                output_tokens=7,
                timestamp="2026-06-26T10:10:00Z",
            )

            cached = {
                "timestamp": "2026-06-26T10:05:00+00:00",
                "claude": {
                    "input_tokens": 1000,
                    "output_tokens": 1000,
                    "cache_creation": 1000,
                    "cache_read": 1000,
                    "total_tokens": 4000,
                    "sessions": 99,
                    "messages": 99,
                    "cost_estimate": 99,
                },
            }
            saved_checkpoints = []
            with (
                mock.patch.object(preview.Path, "home", return_value=home),
                mock.patch.object(preview, "_load_stats_cache", return_value=cached),
                mock.patch.object(preview, "_load_checkpoint", return_value={"files": {"old": {}}}),
                mock.patch.object(preview, "_save_checkpoint", side_effect=saved_checkpoints.append),
            ):
                preview.get_claude_stats()

        saved = saved_checkpoints[0]
        self.assertEqual(saved["version"], 3)
        self.assertEqual(saved["baseline"]["source"], "legacy_cache")
        self.assertEqual(saved["baseline"]["cache_timestamp"], "2026-06-26T10:05:00+00:00")
        self.assertEqual(saved["baseline"]["totals"]["total_tokens"], 5117)
        self.assertRegex(saved["messages"]["msg_1"]["fingerprint"], r"^[0-9a-f]{64}$")

    def test_get_claude_stats_preserves_all_time_message_and_session_totals_from_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            project_dir = home / ".claude" / "projects" / "example"
            project_dir.mkdir(parents=True)
            write_usage_line(
                project_dir / "a.jsonl",
                "msg_1",
                output_tokens=7,
                timestamp="2026-06-26T10:00:01Z",
            )

            checkpoint = {
                "version": 3,
                "messages": {
                    "msg_1": {
                        "timestamp": "2026-06-26T10:00:01Z",
                        "session_id": "session_1",
                        "input_tokens": 10,
                        "output_tokens": 7,
                        "cache_creation": 100,
                        "cache_read": 1000,
                        "fingerprint": "0" * 64,
                    }
                },
                "sessions": ["session_1"],
                "baseline": {
                    "source": "legacy_cache",
                    "cache_timestamp": "2026-06-26T10:00:00+00:00",
                    "totals": {
                        "input_tokens": 1000,
                        "output_tokens": 1000,
                        "cache_creation": 1000,
                        "cache_read": 1000,
                        "total_tokens": 4000,
                        "sessions": 99,
                        "messages": 99,
                        "cost_estimate": 99,
                    },
                },
                "totals": {
                    "input_tokens": 1000,
                    "output_tokens": 1000,
                    "cache_creation": 1000,
                    "cache_read": 1000,
                    "total_tokens": 4000,
                    "sessions": 99,
                    "messages": 99,
                    "cost_estimate": 99,
                },
            }
            saved_checkpoints = []
            with (
                mock.patch.object(preview.Path, "home", return_value=home),
                mock.patch.object(preview, "_load_stats_cache", return_value=None),
                mock.patch.object(preview, "_load_checkpoint", return_value=checkpoint),
                mock.patch.object(preview, "_save_checkpoint", side_effect=saved_checkpoints.append),
            ):
                stats = preview.get_claude_stats()

        self.assertEqual(stats["messages"], 99)
        self.assertEqual(stats["sessions"], 99)
        self.assertEqual(stats["total_tokens"], 4000)
        self.assertEqual(saved_checkpoints[0]["totals"]["messages"], 99)
        self.assertEqual(saved_checkpoints[0]["totals"]["sessions"], 99)

    def test_get_claude_stats_prefers_v2_checkpoint_totals_over_stale_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            project_dir = home / ".claude" / "projects" / "example"
            project_dir.mkdir(parents=True)
            write_usage_line(
                project_dir / "a.jsonl",
                "msg_1",
                output_tokens=7,
                timestamp="2026-06-26T10:00:01Z",
            )

            checkpoint = {
                "version": 2,
                "messages": {
                    "msg_1": {
                        "timestamp": "2026-06-26T10:00:01Z",
                        "session_id": "session_1",
                        "input_tokens": 10,
                        "output_tokens": 7,
                        "cache_creation": 100,
                        "cache_read": 1000,
                    }
                },
                "sessions": ["session_1"],
                "totals": {
                    "input_tokens": 10,
                    "output_tokens": 7,
                    "cache_creation": 100,
                    "cache_read": 1000,
                    "total_tokens": 1117,
                    "sessions": 1,
                    "messages": 1,
                    "cost_estimate": 1.31,
                },
            }
            stale_cache = {
                "claude": {
                    "input_tokens": 1000,
                    "output_tokens": 1000,
                    "cache_creation": 1000,
                    "cache_read": 1000,
                    "total_tokens": 4000,
                    "sessions": 99,
                    "messages": 99,
                    "cost_estimate": 99,
                }
            }

            with (
                mock.patch.object(preview.Path, "home", return_value=home),
                mock.patch.object(preview, "_load_stats_cache", return_value=stale_cache),
                mock.patch.object(preview, "_load_checkpoint", return_value=checkpoint),
                mock.patch.object(preview, "_save_checkpoint"),
            ):
                stats = preview.get_claude_stats()

        self.assertEqual(stats["messages"], 1)
        self.assertEqual(stats["sessions"], 1)
        self.assertEqual(stats["total_tokens"], 1117)

    def test_get_claude_stats_rebuilds_missing_v2_totals_from_checkpoint_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            project_dir = home / ".claude" / "projects" / "example"
            project_dir.mkdir(parents=True)
            write_usage_line(
                project_dir / "a.jsonl",
                "msg_1",
                output_tokens=7,
                timestamp="2026-06-26T10:00:01Z",
            )

            checkpoint = {
                "version": 2,
                "messages": {
                    "msg_1": {
                        "timestamp": "2026-06-26T10:00:01Z",
                        "session_id": "session_1",
                        "input_tokens": 10,
                        "output_tokens": 7,
                        "cache_creation": 100,
                        "cache_read": 1000,
                    }
                },
                "sessions": ["session_1"],
            }
            stale_cache = {
                "claude": {
                    "input_tokens": 1000,
                    "output_tokens": 1000,
                    "cache_creation": 1000,
                    "cache_read": 1000,
                    "total_tokens": 4000,
                    "sessions": 99,
                    "messages": 99,
                    "cost_estimate": 99,
                }
            }

            saved_checkpoints = []
            with (
                mock.patch.object(preview.Path, "home", return_value=home),
                mock.patch.object(preview, "_load_stats_cache", return_value=stale_cache),
                mock.patch.object(preview, "_load_checkpoint", return_value=checkpoint),
                mock.patch.object(preview, "_save_checkpoint", side_effect=saved_checkpoints.append),
            ):
                stats = preview.get_claude_stats()

        self.assertEqual(stats["messages"], 1)
        self.assertEqual(stats["sessions"], 1)
        self.assertEqual(stats["total_tokens"], 1117)
        self.assertEqual(saved_checkpoints[0]["totals"]["total_tokens"], 1117)


CLAUDE_BASELINE = {
    "input_tokens": 1000,
    "output_tokens": 2000,
    "cache_creation": 3000,
    "cache_read": 4000,
    "total_tokens": 10000,
    "sessions": 9,
    "messages": 99,
    "cost_estimate": 123,
}


def ccusage_pair(extra_scale):
    """(all, claude) ccusage totals where non-Claude usage is extra_scale * 1000."""
    claude = {
        "inputTokens": 10, "outputTokens": 20, "cacheCreationTokens": 30,
        "cacheReadTokens": 40, "totalTokens": 100, "totalCost": 1,
    }
    extra = extra_scale
    all_totals = {
        "inputTokens": 10 + extra, "outputTokens": 20 + extra,
        "cacheCreationTokens": 30 + extra, "cacheReadTokens": 40 + extra,
        "totalTokens": 100 + 4 * extra, "totalCost": 1 + extra,
    }
    return all_totals, claude


def cache_with_other(other_scale):
    other = {
        "input_tokens": other_scale, "output_tokens": other_scale,
        "cache_creation": other_scale, "cache_read": other_scale,
        "total_tokens": 4 * other_scale, "sessions": 0, "messages": 0,
        "cost_estimate": other_scale,
    }
    return {
        "claude": dict(CLAUDE_BASELINE),
        "token_usage": {"providers": {"claude": dict(CLAUDE_BASELINE), "other": other}},
    }


class TokenUsageNoRegressionTests(unittest.TestCase):
    def run_usage(self, ccusage, cache, claude=None):
        claude = claude or dict(CLAUDE_BASELINE)
        with (
            mock.patch.object(preview, "get_claude_stats", return_value=claude),
            mock.patch.object(preview, "_load_stats_cache", return_value=cache),
            mock.patch.object(preview.subprocess, "run", side_effect=FileNotFoundError) as run,
            mock.patch.object(preview, "_get_ccusage_totals", side_effect=ccusage),
        ):
            stats = preview.get_token_usage_stats()
        run.assert_not_called()
        return stats

    def test_ccusage_unavailable_keeps_cached_other(self):
        stats = self.run_usage([None, None], cache_with_other(500))
        self.assertEqual(stats["total_tokens"], 10000 + 2000)
        self.assertEqual(stats["providers"]["other"]["total_tokens"], 2000)
        self.assertEqual(stats["cost_estimate"], 123 + 500)

    def test_fresh_other_lower_than_cached_does_not_regress(self):
        stats = self.run_usage(list(ccusage_pair(100)), cache_with_other(500))
        self.assertEqual(stats["total_tokens"], 12000)
        self.assertEqual(stats["input_tokens"], 1500)

    def test_fresh_other_higher_than_cached_is_used(self):
        stats = self.run_usage(list(ccusage_pair(900)), cache_with_other(500))
        self.assertEqual(stats["total_tokens"], 10000 + 3600)
        self.assertEqual(stats["input_tokens"], 1900)
        self.assertEqual(stats["cost_estimate"], 123 + 900)

    def test_no_cache_falls_back_to_claude_only(self):
        stats = self.run_usage([None, None], None)
        self.assertEqual(stats["total_tokens"], 10000)
        self.assertEqual(stats["providers"]["other"]["total_tokens"], 0)
        self.assertEqual(stats["sessions"], 9)
        self.assertEqual(stats["messages"], 99)

    def test_cache_with_claude_but_no_token_usage_does_not_crash(self):
        cache = {"claude": dict(CLAUDE_BASELINE), "github": {}}
        stats = self.run_usage([None, None], cache)
        self.assertEqual(stats["total_tokens"], 10000)
        self.assertEqual(stats["providers"]["other"]["total_tokens"], 0)

    def test_cache_without_providers_derives_other_from_difference(self):
        cached_total = dict(CLAUDE_BASELINE)
        for key in ("input_tokens", "output_tokens", "cache_creation", "cache_read"):
            cached_total[key] += 250
        cached_total["total_tokens"] += 1000
        cached_total["cost_estimate"] += 77
        cache = {"claude": dict(CLAUDE_BASELINE), "token_usage": cached_total}
        stats = self.run_usage([None, None], cache)
        self.assertEqual(stats["total_tokens"], 11000)
        self.assertEqual(stats["cost_estimate"], 123 + 77)

    def test_cached_other_applies_on_top_of_grown_claude_baseline(self):
        grown = dict(CLAUDE_BASELINE, input_tokens=2000, total_tokens=11000)
        stats = self.run_usage([None, None], cache_with_other(500), claude=grown)
        self.assertEqual(stats["total_tokens"], 11000 + 2000)


if __name__ == "__main__":
    unittest.main()
