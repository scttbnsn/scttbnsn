import re
import unittest
import xml.etree.ElementTree as ET

import public_repos
from card import W, build_card, fmt
from card_data import empty_calendar

USAGE = dict(input_tokens=308953046, output_tokens=861943849, cache_creation=6467209567, cache_read=189334950641,
             total_tokens=196973057103, sessions=18105, messages=1469058, cost_estimate=273407.72)
GITHUB = dict(stars=490, repos=629, contributed_repos=104, commits=13821, prs=4132,
              loc_total=30997657, loc_added=63138125, loc_deleted=56452275)
LANGS = [dict(name=n, bytes=b, color=c) for n, b, c in (
    ("TypeScript", 38_000_000, "#3178c6"), ("JavaScript", 16_000_000, "#f1e05a"), ("Go", 12_000_000, "#00add8"),
    ("Python", 10_000_000, "#3572A5"), ("Swift", 8_000_000, "#F05138"), ("Shell", 3_000_000, "#89e051"),
    ("Vue", 1_000_000, "#41b883"), ("QML", 400_000, "#44a51c"))]
STARS = {r: 12345 for r, _, _ in public_repos.REPOS}


def calendar(weeks=53, level=3):
    cal = empty_calendar()
    cal["weeks"] = [[(i + d) % (level + 2) for d in range(7)] for i in range(weeks)]
    cal["dates"] = cal["dates"][:weeks] if weeks <= 53 else cal["dates"] + cal["dates"][: weeks - 53]
    cal["total"] = sum(sum(w) for w in cal["weeks"])
    return cal


def render(mode, cal=None, langs=LANGS, stars=STARS):
    return build_card(mode, USAGE, GITHUB, cal or calendar(), langs, stars)


class CardTests(unittest.TestCase):
    def test_dark_and_light_build_valid_xml(self):
        for mode in ("dark", "light"):
            root = ET.fromstring(render(mode))
            self.assertTrue(root.tag.endswith("svg"))
            self.assertEqual(root.get("width"), str(W))

    def test_modes_differ(self):
        self.assertNotEqual(render("dark"), render("light"))

    def test_size_budget(self):
        for mode in ("dark", "light"):
            self.assertLess(len(render(mode).encode()), 150_000)

    def test_nothing_outside_viewbox(self):
        for mode in ("dark", "light"):
            svg = render(mode, calendar(54))
            h = float(re.search(r'viewBox="0 0 800 (\d+)"', svg).group(1))
            for x in re.findall(r'<(?:text|rect) [^>]*?\bx="(-?[\d.]+)"', svg):
                self.assertTrue(0 <= float(x) <= W, x)
            for x, w in re.findall(r'<rect [^>]*?\bx="(-?[\d.]+)" y="[\d.]+" width="([\d.]+)"', svg):
                self.assertLessEqual(float(x) + float(w), W + 0.01)
            for y in re.findall(r'<(?:text|rect) [^>]*?\by="(-?[\d.]+)"', svg):
                self.assertTrue(0 <= float(y) <= h, y)

    def test_live_values_rendered(self):
        svg = render("dark")
        for needle in (fmt(USAGE["total_tokens"]), "30,997,657", "all repos", "12345",
                       "TypeScript", "htop"):
            self.assertIn(needle, svg)
        self.assertIn("in the last year", svg)

    def test_empty_data_still_renders(self):
        cal = empty_calendar()
        zero_usage = dict(USAGE, total_tokens=0, input_tokens=0, output_tokens=0, cache_creation=0, cache_read=0)
        zero_gh = dict(GITHUB, loc_added=0, loc_deleted=0, loc_total=0)
        svg = build_card("dark", zero_usage, zero_gh, cal, [dict(name="Go", bytes=1, color="#00add8")], {r: None for r, _, _ in public_repos.REPOS})
        ET.fromstring(svg)
        ET.fromstring(build_card("light", USAGE, GITHUB, cal, [], STARS))

    def test_final_frame_needs_no_animation(self):
        # every animation ends visible: reveals fade in to opacity 1, wipes grow to full width
        svg = render("dark")
        self.assertIn("@keyframes show{from{opacity:0}to{opacity:1}}", svg)
        self.assertIn("@keyframes type{from{width:0}to{width:var(--w)}}", svg)
        self.assertEqual(svg.count('class="eq"'), 5)  # one title-bar equalizer only


if __name__ == "__main__":
    unittest.main()
