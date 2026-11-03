import unittest

from generate_svg import generate_svg


class GenerateSvgTests(unittest.TestCase):
    def test_token_section_uses_generic_token_usage_label(self):
        claude = {
            "sessions": 1,
            "messages": 2,
            "total_tokens": 3000,
            "cost_estimate": 4,
        }
        github = {
            "stars": 0,
            "repos": 0,
            "contributed_repos": 0,
            "commits": 0,
            "prs": 0,
            "loc_total": 0,
            "loc_added": 0,
            "loc_deleted": 0,
        }

        svg = generate_svg("dark", claude=claude, github=github)

        self.assertIn("TOKEN USAGE", svg)
        self.assertNotIn("CLAUDE CODE", svg)


if __name__ == "__main__":
    unittest.main()
