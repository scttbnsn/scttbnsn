#!/usr/bin/env python3
"""
Generate the htop profile card for the GitHub profile README.
Creates dark_mode.svg and light_mode.svg from live stats (see card.py for the design).
"""

from pathlib import Path

import card_data
import public_repos
from card import build_card
from preview import get_claude_stats, get_token_usage_stats, get_github_stats, save_stats_cache


def generate_svg(mode, token_usage, github, calendar, langs, stars):
    """Return the card SVG for the given color mode."""
    return build_card(mode, token_usage, github, calendar, langs, stars)


def main():
    """Fetch everything once and write both dark and light mode SVGs."""
    script_dir = Path(__file__).parent

    claude = get_claude_stats()
    token_usage = get_token_usage_stats(claude)
    github = get_github_stats()

    # Save cache so CI commits fresh values
    save_stats_cache(claude, github, token_usage)

    calendar = card_data.get_calendar()
    langs = card_data.get_languages()
    stars = public_repos.get_stars()

    for mode in ("dark", "light"):
        svg = generate_svg(mode, token_usage, github, calendar, langs, stars)
        path = script_dir / f"{mode}_mode.svg"
        path.write_text(svg, encoding="utf-8")
        print(f"Generated: {path}")


if __name__ == "__main__":
    main()
