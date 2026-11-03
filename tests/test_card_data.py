import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import card_data

GOOD_CAL = {"total": 120, "weeks": [[0, 1, 2, 0, 0, 0, 0], [3, 4, 5, 6, 7, 8, 9]], "dates": ["2026-10-25", "2026-11-01"]}
GOOD_LANGS = [{"name": "Go", "bytes": 100, "color": "#00add8"}]


def api_calendar(total, weeks):
    return {"user": {"contributionsCollection": {"contributionCalendar": {
        "totalContributions": total,
        "weeks": [{"firstDay": d, "contributionDays": [{"contributionCount": n} for n in w]} for d, w in weeks]}}}}


def repo(name, langs, fork=False, archived=False):
    return {"name": name, "isFork": fork, "isArchived": archived,
            "languages": {"edges": [{"size": s, "node": {"name": n, "color": f"#{n[:1].lower()}00000"}} for n, s in langs]}}


class TmpCache(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "cache" / "x.json"

    def seed(self, data):
        self.path.parent.mkdir(exist_ok=True)
        self.path.write_text(json.dumps(data))

    def stored(self):
        return json.loads(self.path.read_text())


class CalendarTests(TmpCache):
    def test_live_parsed_and_cached(self):
        raw = api_calendar(5, [("2026-10-25", [0, 1, 0, 0, 2, 0, 0]), ("2026-11-01", [2])])
        with mock.patch.object(card_data, "graphql", return_value=raw):
            cal = card_data.get_calendar(self.path)
        self.assertEqual(cal, {"total": 5, "weeks": [[0, 1, 0, 0, 2, 0, 0], [2]], "dates": ["2026-10-25", "2026-11-01"]})
        self.assertEqual(self.stored(), cal)

    def test_error_falls_back_to_cache(self):
        self.seed(GOOD_CAL)
        with mock.patch.object(card_data, "graphql", side_effect=OSError("down")):
            self.assertEqual(card_data.get_calendar(self.path), GOOD_CAL)
        self.assertEqual(self.stored(), GOOD_CAL)

    def test_empty_live_does_not_overwrite_good_cache(self):
        self.seed(GOOD_CAL)
        blank = api_calendar(0, [("2026-10-25", [0] * 7), ("2026-11-01", [0] * 7)])
        with mock.patch.object(card_data, "graphql", return_value=blank):
            self.assertEqual(card_data.get_calendar(self.path), GOOD_CAL)
        self.assertEqual(self.stored(), GOOD_CAL)

    def test_malformed_live_does_not_overwrite_good_cache(self):
        self.seed(GOOD_CAL)
        with mock.patch.object(card_data, "graphql", return_value={"user": None}):
            self.assertEqual(card_data.get_calendar(self.path), GOOD_CAL)
        self.assertEqual(self.stored(), GOOD_CAL)

    def test_no_cache_and_no_network_gives_empty_calendar(self):
        with mock.patch.object(card_data, "graphql", side_effect=OSError):
            cal = card_data.get_calendar(self.path)
        self.assertEqual(cal["total"], 0)
        self.assertEqual(len(cal["weeks"]), len(cal["dates"]))
        self.assertFalse(self.path.exists())

    def test_corrupt_cache_is_ignored(self):
        self.path.parent.mkdir(exist_ok=True)
        self.path.write_text("{not json")
        with mock.patch.object(card_data, "graphql", side_effect=OSError):
            self.assertEqual(card_data.get_calendar(self.path)["total"], 0)


class LanguageTests(TmpCache):
    def test_aggregation_sums_across_repos_and_sorts(self):
        nodes = [repo("a", [("Go", 100), ("Shell", 5)]), repo("b", [("Go", 50), ("Python", 120)])]
        langs = card_data.aggregate_languages(nodes)
        self.assertEqual([(l["name"], l["bytes"]) for l in langs], [("Go", 150), ("Python", 120), ("Shell", 5)])

    def test_forks_archived_and_excluded_languages_skipped(self):
        nodes = [repo("fork", [("Go", 999)], fork=True), repo("old", [("Go", 999)], archived=True),
                 repo("ok", [("Rust", 10), ("HTML", 5000), ("MDX", 5000)]), None]
        langs = card_data.aggregate_languages(nodes)
        self.assertEqual([(l["name"], l["bytes"]) for l in langs], [("Rust", 10)])

    def test_fetch_paginates_over_every_owner(self):
        pages = {("scttbnsn", None): ([repo("a", [("Go", 1)])], "c1"), ("scttbnsn", "c1"): ([repo("b", [("Go", 2)])], None),
                 ("CodesWhat", None): ([repo("c", [("Go", 4)])], None)}

        def fake(query, variables):
            nodes, nxt = pages[(variables["login"], variables["after"])]
            return {"repositoryOwner": {"repositories": {"pageInfo": {"hasNextPage": nxt is not None, "endCursor": nxt}, "nodes": nodes}}}
        with mock.patch.object(card_data, "graphql", side_effect=fake):
            langs = card_data.get_languages(self.path)
        self.assertEqual(langs[0]["bytes"], 7)
        self.assertEqual(self.stored(), langs)

    def test_error_falls_back_to_cache(self):
        self.seed(GOOD_LANGS)
        with mock.patch.object(card_data, "graphql", side_effect=OSError("down")):
            self.assertEqual(card_data.get_languages(self.path), GOOD_LANGS)

    def test_empty_live_does_not_overwrite_good_cache(self):
        self.seed(GOOD_LANGS)
        empty = {"repositoryOwner": {"repositories": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []}}}
        with mock.patch.object(card_data, "graphql", return_value=empty):
            self.assertEqual(card_data.get_languages(self.path), GOOD_LANGS)
        self.assertEqual(self.stored(), GOOD_LANGS)

    def test_unknown_owner_falls_back_to_cache(self):
        self.seed(GOOD_LANGS)
        with mock.patch.object(card_data, "graphql", return_value={"repositoryOwner": None}):
            self.assertEqual(card_data.get_languages(self.path), GOOD_LANGS)

    def test_no_cache_no_network_is_empty(self):
        with mock.patch.object(card_data, "graphql", side_effect=OSError):
            self.assertEqual(card_data.get_languages(self.path), [])


class GraphqlTests(unittest.TestCase):
    def test_errors_payload_raises(self):
        resp = mock.MagicMock()
        resp.__enter__.return_value = resp
        resp.read.return_value = json.dumps({"errors": [{"message": "bad"}]}).encode()
        with mock.patch.object(card_data, "_auth_token", return_value="t"), \
                mock.patch("urllib.request.urlopen", return_value=resp):
            with self.assertRaises(RuntimeError):
                card_data.graphql("q", {})

    def test_missing_auth_raises(self):
        with mock.patch.object(card_data, "_auth_token", return_value=None):
            with self.assertRaises(RuntimeError):
                card_data.graphql("q", {})


if __name__ == "__main__":
    unittest.main()
