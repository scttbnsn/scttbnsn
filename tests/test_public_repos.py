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
        text = json.dumps(public_repos.build_lines(stars))
        self.assertNotIn("★None", text)

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

    def test_grid_fits_card_width(self):
        stars = {r: 12345 for r, _, _ in public_repos.REPOS}
        card_chars = int(800 / (14 * 0.6))
        for line, _, _ in public_repos.build_lines(stars):
            if line.startswith("__SEG__"):
                parts = json.loads(line[len("__SEG__"):])
                self.assertLessEqual(sum(len(t) for t, _ in parts), card_chars)
                self.assertLessEqual(sum(len(t) for t, _ in parts), 90)

    def test_rendered_svg_contains_grid_within_bounds(self):
        import re
        from generate_svg import generate_svg
        gh = dict(stars=1, repos=1, contributed_repos=1, commits=1, prs=1,
                  loc_total=1, loc_added=1, loc_deleted=0)
        tok = dict(sessions=1, messages=1, total_tokens=1, cost_estimate=1)
        stars = {r: 99 for r, _, _ in public_repos.REPOS}
        with mock.patch.object(public_repos, "_memo", stars):
            svg = generate_svg("dark", tok, gh)
        self.assertIn("DOCKER", svg)
        for x in re.findall(r'<text x="([\d.]+)" y="\d+" class="(?:orange|text|gray|yellow)">', svg):
            self.assertLess(float(x), 800)


if __name__ == "__main__":
    unittest.main()
