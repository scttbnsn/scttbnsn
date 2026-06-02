#!/usr/bin/env python3
"""
Generate NFO-style SVG files for GitHub profile README.
Creates dark_mode.svg and light_mode.svg with embedded stats.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

# Import stats functions from preview
from preview import get_claude_stats, get_github_stats, format_number, save_stats_cache


def escape_xml(s):
    """Escape XML special characters."""
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def generate_svg(mode="dark", claude=None, github=None):
    """Generate SVG content for the given color mode."""

    # Get stats (use provided or fetch fresh)
    if claude is None:
        claude = get_claude_stats()
    if github is None:
        github = get_github_stats()

    # Color schemes
    if mode == "dark":
        colors = {
            'bg': '#0d1117',
            'text': '#39c5cf',
            'gray': '#8b949e',
            'magenta': '#e879f9',
            'green': '#a3e635',
            'red': '#f87171',
            'orange': '#fb923c',
            'yellow': '#fbbf24',
            'redact': '#c9d1d9',
        }
    else:
        colors = {
            'bg': '#f6f8fa',
            'text': '#0969da',
            'gray': '#57606a',
            'magenta': '#c026d3',
            'green': '#65a30d',
            'red': '#dc2626',
            'orange': '#ea580c',
            'yellow': '#d97706',
            'redact': '#1f2328',
        }

    c = colors
    width = 800
    font_size = 14
    line_height_tight = 14  # For ASCII art blocks (slightly squished)
    line_height_normal = 20  # For stat lines (readable spacing)
    y_start = 30
    content_width = 90  # chars for stat lines

    # Stats formatter with dots (right-aligned values)
    def stat_line(key, value):
        key_str = f"{key}:"
        val_str = str(value)
        dots = '.' * (content_width - len(key_str) - len(val_str) - 2)
        return f"{key_str} {dots} {val_str}"

    # Project line formatter (name + dots + description)
    def project_line(name, desc):
        dots = '.' * (content_width - len(name) - len(desc) - 2)
        return f"{name} {dots} {desc}"

    # Build content lines with spacing type
    # Each entry: (line_text, color, spacing_type)
    # spacing_type: "tight" for ASCII art, "normal" for stats, "blank" for empty
    lines = []

    # Header art - 3D ASCII smiley face
    header_art = [
        "                         ####################                         ",
        "                     #########+++++++++++#########                    ",
        "                #######++--..............----++#######                ",
        "              ######+--.......................--++#######             ",
        "            #####+---............................--++######           ",
        "          #####+--...............................-----+######         ",
        "        #####+-..................................-------+#####        ",
        "       #####+........................................-----+#####      ",
        "     ++###+-......................................-....----+#####     ",
        "     ####+............................................-------+###     ",
        "     ###+-........--........-+....................--....------####    ",
        "    ###+-........+###+-..-+###+-..............--++#++...------+##++  ",
        "    ###-..........-+###++####+............--+#######+-..-------+#### ",
        "   ###+-............-+#####+-..........-+######++--....-.------+##++ ",
        "  ++##-.............-+#####+-.........+########+-.....----------+### ",
        "  ####-...........-+###++####+..........---+######--.----.-.----+### ",
        "  ###+-..........-###+-..-+###+-.............----+++-.-----.--.-+### ",
        "  ###--...........--.......-++......................-.----------+### ",
        "  ###+-...........................................+##+----------+### ",
        "  ###+-......--+##+-..............................-+####+---.---+### ",
        "  ####+--...-+#####--..........................--+######+------++### ",
        "  ++##+----..---+###+--.....................--+######+--------++#### ",
        "  ++###++-......-++####+---.............---+#########+--------++##++ ",
        "    -+##+--..-.....--#######+##+++#+#############+-+###+------+##++ ",
        "    -+###+------......++#################++++++###+--+##+---++##### ",
        "     #+##+----..-........---++++##########------+#++--+##++-+####   ",
        "     --###++----....................----+###------+++++###+####++    ",
        "       -+###++-----..-...............--.--+##++--++++#########++    ",
        "        +++##++------.--.-..-..---..-------+####+++#########++     ",
        "          ++###++---------------------------+###############       ",
        "           +++###++--------------------------+++############       ",
        "             +++###+++-+----------------+-+++++++#######+#         ",
        "               -++######++++++-------+--+-++++########++           ",
        "                 -+##+#######+++++++++++++###########               ",
        "                       --+########################                 ",
        "                           +++##########++                         ",
    ]
    for art in header_art:
        lines.append((art, "yellow", "tight"))

    lines.append(("", "text", "blank"))
    lines.append(("", "text", "blank"))
    lines.append(("ai developer  ·  prompt whisperer", "gray", "normal"))
    lines.append(("", "text", "blank"))
    lines.append(("", "text", "blank"))

    # System info header
    lines.append(("-------------------------------------- SYSTEM INFO ---------------------------------------", "orange", "normal"))

    lines.append(("", "text", "blank"))

    for key, val in [
        ("Location", "NYC, NY"),
        ("Shell", "living tissue over metal endoskeleton"),
        ("Languages", "english, bad english, help files"),
        ("Focus", "AI/ML, Developer Tools, waning"),
    ]:
        lines.append((stat_line(key, val), "gray", "normal"))

    lines.append(("", "text", "blank"))
    lines.append(("", "text", "blank"))

    # Claude Code header
    lines.append(("-------------------------------------- CLAUDE CODE ---------------------------------------", "magenta", "normal"))

    lines.append(("", "text", "blank"))

    for key, val in [
        ("Sessions", format_number(claude['sessions'])),
        ("Messages", format_number(claude['messages'])),
        ("Total Tokens", format_number(claude['total_tokens'])),
        ("Est. API Cost Saved", f"${claude['cost_estimate']:,.0f}"),
    ]:
        lines.append((stat_line(key, val), "gray", "normal"))

    lines.append(("", "text", "blank"))
    lines.append(("", "text", "blank"))

    # GitHub stats header
    lines.append(("-------------------------------------- GITHUB STATS --------------------------------------", "green", "normal"))

    lines.append(("", "text", "blank"))

    for key, val in [
        ("Repositories", github.get('repos', 0)),
        ("Contributed To", github.get('contributed_repos', 0)),
        ("Total Commits", github.get('commits', 0)),
        ("Pull Requests", github.get('prs', 0)),
    ]:
        lines.append((stat_line(key, val), "gray", "normal"))

    # Stars line - special formatting with star unicode
    stars_count = github.get('stars', 0)
    stars_value = f"{stars_count} ★"
    lines.append((f"__STARS__{stars_value}__", "stars", "normal"))

    # LOC line - special formatting with dots
    loc_total = github.get('loc_total', 0)
    loc_added = github.get('loc_added', 0)
    loc_deleted = github.get('loc_deleted', 0)
    loc_value = f"{loc_total:,} ( +{loc_added:,}, -{loc_deleted:,} )"
    lines.append((f"__LOC__{loc_value}__", "loc", "normal"))

    lines.append(("", "text", "blank"))
    lines.append(("", "text", "blank"))

    # Projects header
    lines.append(("--------------------------------------- PROJECTS ----------------------------------------", "text", "normal"))

    lines.append(("", "text", "blank"))

    # Area 51 - classified/obfuscated projects
    redact = "████████"
    lines.append((f"[ AREA 51 ] ............................................................. just trust me", "orange", "normal"))

    lines.append(("", "text", "blank"))

    area51_projects = [
        ("Nexus", f"Enterprise API platform connecting {redact} systems at scale"),
        ("Origami", f"AI-powered {redact} app, concept to launch"),
        ("Foundry", f"AI app builder for rapid {redact} prototyping"),
        ("Beacon", f"Intelligence platform surfacing {redact} insights"),
        ("Meridian", f"Client relationship dashboard for {redact}"),
        ("Exodus", f"Large-scale {redact} migration across platforms"),
    ]
    for name, desc in area51_projects:
        lines.append((project_line(name, desc), "project_redact", "normal"))

    lines.append(("", "text", "blank"))
    lines.append(("", "text", "blank"))

    # Public - open source projects
    lines.append(("[ PUBLIC ] ............................................................... open source", "green", "normal"))

    lines.append(("", "text", "blank"))

    lines.append((project_line("Dry Dock", "Container update monitoring · 23 registries"), "gray", "normal"))
    lines.append(("  github.com/CodesWhat/drydock", "text", "normal"))

    lines.append(("", "text", "blank"))

    lines.append((project_line("Portkey Admin MCP", "Full Portkey Admin API MCP server"), "gray", "normal"))
    lines.append(("  github.com/s-b-e-n-s-o-n/portkey-admin-mcp", "text", "normal"))

    lines.append(("", "text", "blank"))

    lines.append((project_line("Sock Guard", "Default-deny Docker socket proxy · Go"), "gray", "normal"))
    lines.append(("  github.com/CodesWhat/sockguard", "text", "normal"))

    lines.append(("", "text", "blank"))

    # Date stamp rendered separately in top-right corner
    now = datetime.now()
    date_stamp = f"{now.month}/{now.day}/{now.strftime('%y')}"

    # Calculate height based on variable line heights
    total_height = y_start
    for _, _, spacing in lines:
        if spacing == "tight":
            total_height += line_height_tight
        elif spacing == "blank":
            total_height += line_height_normal // 2  # Half height for blanks
        else:
            total_height += line_height_normal
    height = total_height + 30

    # Build SVG
    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<style>
@font-face {{
    src: local('Consolas'), local('Monaco'), local('Menlo');
    font-family: 'MonoFallback';
    font-display: swap;
}}
text {{
    font-family: 'MonoFallback', ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace;
    font-size: {font_size}px;
    white-space: pre;
    dominant-baseline: text-before-edge;
}}
.text {{ fill: {c['text']}; }}
.gray {{ fill: {c['gray']}; }}
.magenta {{ fill: {c['magenta']}; }}
.green {{ fill: {c['green']}; }}
.red {{ fill: {c['red']}; }}
.orange {{ fill: {c['orange']}; }}
.yellow {{ fill: {c['yellow']}; }}
.redact {{ fill: {c['redact']}; }}
</style>
<rect width="{width}" height="{height}" fill="{c['bg']}" rx="10"/>
<text x="{width - 15}" y="12" text-anchor="end" class="gray" font-size="11">{date_stamp}</text>
'''

    # Add centered lines with variable spacing
    y = y_start
    for line, color, spacing in lines:
        # Special handling for LOC line with colored +/-
        if line.startswith('__LOC__'):
            # Extract the value part
            loc_value = line.replace('__LOC__', '').replace('__', '')
            # Build dotted line: Lines of Code: ........ value
            key_str = "Lines of Code:"
            dots_len = content_width - len(key_str) - len(loc_value) - 2
            dots = '.' * max(dots_len, 3)

            # Use separate text elements instead of tspans for mobile compatibility
            match = re.search(r'([\d,]+) \( \+([\d,]+), -([\d,]+) \)', loc_value)
            if match:
                total, added, deleted = match.groups()
                # Build the full line to calculate positions
                # Monospace: ~8.4px per char at 14px font
                char_width = font_size * 0.6
                full_line = f"{key_str} {dots} {total} ( +{added}, -{deleted} )"
                line_width = len(full_line) * char_width
                start_x = (width - line_width) / 2

                # Gray prefix: "Lines of Code: ... total ( "
                prefix = f"{key_str} {dots} {total} ( "
                svg += f'<text x="{start_x}" y="{y}" class="gray">{prefix}</text>\n'

                # Green: "+added"
                green_x = start_x + len(prefix) * char_width
                green_text = f"+{added}"
                svg += f'<text x="{green_x}" y="{y}" class="green">{green_text}</text>\n'

                # Gray: ", "
                comma_x = green_x + len(green_text) * char_width
                svg += f'<text x="{comma_x}" y="{y}" class="gray">, </text>\n'

                # Red: "-deleted"
                red_x = comma_x + 2 * char_width
                red_text = f"-{deleted}"
                svg += f'<text x="{red_x}" y="{y}" class="red">{red_text}</text>\n'

                # Gray: " )"
                suffix_x = red_x + len(red_text) * char_width
                svg += f'<text x="{suffix_x}" y="{y}" class="gray"> )</text>\n'
            else:
                svg += f'<text x="{width // 2}" y="{y}" text-anchor="middle" class="gray">{key_str} {dots} {loc_value}</text>\n'
        elif line.startswith('__STARS__'):
            # Extract the value part: "120 ★"
            stars_value = line.replace('__STARS__', '').replace('__', '')
            key_str = "Stars Earned:"
            dots_len = content_width - len(key_str) - len(stars_value) - 2
            dots = '.' * max(dots_len, 3)

            char_width = font_size * 0.6
            full_line = f"{key_str} {dots} {stars_value}"
            line_width = len(full_line) * char_width
            start_x = (width - line_width) / 2

            # Gray prefix: "Stars Earned: ... 120 "
            num_part = stars_value.split(' ★')[0]
            prefix = f"{key_str} {dots} {num_part} "
            svg += f'<text x="{start_x}" y="{y}" class="gray">{prefix}</text>\n'

            # Yellow star
            star_x = start_x + len(prefix) * char_width
            svg += f'<text x="{star_x}" y="{y}" class="yellow">★</text>\n'
        elif color == "project_redact" and line:
            # Split line into segments around redaction blocks
            char_width = font_size * 0.6
            line_width = len(line) * char_width
            start_x = (width - line_width) / 2
            redact_marker = "████████"
            parts = line.split(redact_marker)
            x_pos = start_x
            for i, part in enumerate(parts):
                if part:
                    escaped = escape_xml(part)
                    svg += f'<text x="{x_pos}" y="{y}" class="gray">{escaped}</text>\n'
                    x_pos += len(part) * char_width
                if i < len(parts) - 1:
                    svg += f'<text x="{x_pos}" y="{y}" class="redact">{escape_xml(redact_marker)}</text>\n'
                    x_pos += len(redact_marker) * char_width
        elif line:  # Non-empty line
            escaped = escape_xml(line)
            svg += f'<text x="{width // 2}" y="{y}" text-anchor="middle" class="{color}">{escaped}</text>\n'
        # else: blank line, just advance y

        # Advance y based on spacing type
        if spacing == "tight":
            y += line_height_tight
        elif spacing == "blank":
            y += line_height_normal // 2
        else:
            y += line_height_normal

    svg += '</svg>'
    return svg


def main():
    """Generate both dark and light mode SVGs."""
    script_dir = Path(__file__).parent

    # Fetch stats once and reuse for both SVGs
    claude = get_claude_stats()
    github = get_github_stats()

    # Save cache so CI commits fresh values
    save_stats_cache(claude, github)

    # Generate dark mode
    dark_svg = generate_svg("dark", claude=claude, github=github)
    dark_path = script_dir / "dark_mode.svg"
    with open(dark_path, 'w', encoding='utf-8') as f:
        f.write(dark_svg)
    print(f"Generated: {dark_path}")

    # Generate light mode
    light_svg = generate_svg("light", claude=claude, github=github)
    light_path = script_dir / "light_mode.svg"
    with open(light_path, 'w', encoding='utf-8') as f:
        f.write(light_svg)
    print(f"Generated: {light_path}")


if __name__ == "__main__":
    main()
