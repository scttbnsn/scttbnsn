import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import public_repos


class PublicReposTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = Path(self.tmp.name) / "cache" / "public_repos.json"

    def seed(self, data):
        self.cache.parent.mkdir(exist_ok=True)
        self.cache.write_text(json.dumps(data))

    def test_columns_sorted_by_stars_desc(self):
        stars = {r: 0 for r, _, _ in public_repos.REPOS}
        stars.update({"CodesWhat/portwing": 50, "CodesWhat/drydock": 10, "CodesWhat/sockguard": 30})
        docker = public_repos.grid_columns(stars)[0]
        self.assertEqual([n for n, _, _ in docker], ["portwing", "sockguard", "drydock"])

    def test_missing_stars_sort_last_and_render_without_star(self):
        stars = {"CodesWhat/drydock": 5, "CodesWhat/sockguard": None, "CodesWhat/portwing": 1}
        docker = public_repos.grid_columns(stars)[0]
        self.assertEqual([n for n, _, _ in docker], ["drydock", "portwing", "sockguard"])

    def test_live_values_fetched_and_cached(self):
        with mock.patch.object(public_repos, "_fetch_one", return_value=7):
            stars = public_repos.get_stars(self.cache)
        self.assertTrue(all(v == 7 for v in stars.values()))
        self.assertEqual(json.loads(self.cache.read_text())["CodesWhat/drydock"], 7)

    def test_api_error_falls_back_to_cache_then_none(self):
        self.seed({"CodesWhat/drydock": 274})
        with mock.patch.object(public_repos, "_fetch_one", side_effect=OSError("down")):
            stars = public_repos.get_stars(self.cache)
        self.assertEqual(stars["CodesWhat/drydock"], 274)
        self.assertIsNone(stars["CodesWhat/sockguard"])
        self.assertEqual(json.loads(self.cache.read_text())["CodesWhat/drydock"], 274)

    def test_no_regression_to_zero_over_cached_value(self):
        self.seed({"CodesWhat/drydock": 274})
        with mock.patch.object(public_repos, "_fetch_one", return_value=0):
            stars = public_repos.get_stars(self.cache)
        self.assertEqual(stars["CodesWhat/drydock"], 274)
        self.assertEqual(json.loads(self.cache.read_text())["CodesWhat/drydock"], 274)

    def test_corrupt_cache_does_not_crash(self):
        self.cache.parent.mkdir(exist_ok=True)
        self.cache.write_text("{not json")
        with mock.patch.object(public_repos, "_fetch_one", side_effect=OSError):
            stars = public_repos.get_stars(self.cache)
        self.assertTrue(all(v is None for v in stars.values()))


if __name__ == "__main__":
    unittest.main()
