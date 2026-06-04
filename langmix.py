from __future__ import annotations

import argparse
import collections
import math
import os
from typing import Dict, Iterable, Optional, Tuple
from xml.sax.saxutils import escape

import requests


LANGUAGE_RULES = [
    (("*.tsx", "*.ts"), "TypeScript"),
    (("*.jsx", "*.js", "*.mjs", "*.cjs"), "JavaScript"),
    (("*.go",), "Go"),
    (("*.py",), "Python"),
    (("*.java",), "Java"),
    (("*.cs",), "C#"),
    (("*.rb",), "Ruby"),
    (("*.php",), "PHP"),
    (("*.rs",), "Rust"),
    (("*.kt", "*.kts"), "Kotlin"),
    (("*.swift",), "Swift"),
    (("*.dart",), "Dart"),
    (("*.lua",), "Lua"),
    (("*.sh", "*.bash"), "Shell"),
    (("*.sql",), "SQL"),
    (("*.scala",), "Scala"),
    (("*.c",), "C"),
    (("*.cc", "*.cpp", "*.cxx", "*.hh", "*.hpp", "*.hxx"), "C++"),
    (("*.html", "*.htm"), "HTML"),
    (("*.css",), "CSS"),
    (("*.yml", "*.yaml"), "YAML"),
    (("*.json",), "JSON"),
]

SPECIAL_FILES = {
    "Dockerfile": "Dockerfile",
    "makefile": "Makefile",
    "Makefile": "Makefile",
    "Gemfile": "Ruby",
    "Cargo.toml": "Rust",
    "go.mod": "Go",
    "go.sum": "Go",
    "package.json": "JavaScript",
    "tsconfig.json": "TypeScript",
    "Pipfile": "Python",
    "requirements.txt": "Python",
}

PALETTE = [
    "#f7df1e",
    "#3178c6",
    "#00add8",
    "#3776ab",
    "#b07219",
    "#178600",
    "#c6538c",
    "#4f5d95",
    "#dea584",
    "#a97bff",
    "#ff6b6b",
    "#22c55e",
    "#06b6d4",
    "#8b5cf6",
    "#f97316",
]


def infer_language(path: str) -> Optional[str]:
    base = path.rsplit("/", 1)[-1]
    if base in SPECIAL_FILES:
        return SPECIAL_FILES[base]

    lower = base.lower()
    for patterns, language in LANGUAGE_RULES:
        for pattern in patterns:
            suffix = pattern[1:].lower()
            if lower.endswith(suffix):
                return language
    return None


def github_get(session: requests.Session, url: str, params: Optional[dict] = None) -> requests.Response:
    resp = session.get(url, params=params, timeout=60)
    resp.raise_for_status()
    return resp


def search_commits(session: requests.Session, author: str, max_commits: int) -> Iterable[Tuple[str, str]]:
    page = 1
    seen = 0

    while seen < max_commits:
        resp = github_get(
            session,
            "https://api.github.com/search/commits",
            params={
                "q": f"author:{author}",
                "sort": "author-date",
                "order": "desc",
                "per_page": min(100, max_commits - seen),
                "page": page,
            },
        )
        items = resp.json().get("items", [])
        if not items:
            break

        for item in items:
            repo_full_name = item["repository"]["full_name"]
            sha = item["sha"]
            yield repo_full_name, sha
            seen += 1
            if seen >= max_commits:
                return

        page += 1


def get_commit(session: requests.Session, full_name: str, sha: str) -> dict:
    resp = github_get(session, f"https://api.github.com/repos/{full_name}/commits/{sha}")
    return resp.json()


def polar_to_cartesian(cx: float, cy: float, r: float, angle_deg: float) -> Tuple[float, float]:
    rad = math.radians(angle_deg - 90.0)
    return cx + r * math.cos(rad), cy + r * math.sin(rad)


def arc_path(cx: float, cy: float, r: float, start_deg: float, end_deg: float) -> str:
    end_x, end_y = polar_to_cartesian(cx, cy, r, end_deg)
    start_x, start_y = polar_to_cartesian(cx, cy, r, start_deg)
    large_arc = 1 if -(end_deg - start_deg) > 180 else 0
    return f"M {start_x:.2f} {start_y:.2f} A {r:.2f} {r:.2f} 0 {large_arc} 1 {end_x:.2f} {end_y:.2f}"


def color_for_index(index: int) -> str:
    return PALETTE[index % len(PALETTE)]


def build_svg(counts: Dict[str, int], output: str, title: str) -> None:
    filtered = {k: v for k, v in counts.items() if v > 0}
    if not filtered:
        filtered = {"No code files found": 1}

    items = sorted(filtered.items(), key=lambda kv: kv[1], reverse=True)
    total = sum(v for _, v in items)

    width = 960
    height = 520
    cx = 280
    cy = height // 2
    radius = 220
    stroke_width = 37

    # Larger gap so rounded caps do not overlap
    gap_deg = math.degrees((stroke_width / radius) * 1.15)

    left_x = 590
    top_y = cy - radius
    row_h = max(18, (radius * 2)//len(items))

    svg: list[str] = []
    svg.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{escape(title)}">'
    )
    svg.append(
        """
<defs>
  <style><![CDATA[
    :root {
      color-scheme: light dark;
      --label: #111827;
      --value: #374151;
    }

    @media (prefers-color-scheme: dark) {
      :root {
        --label: #f3f4f6;
        --value: #d1d5db;
      }
    }

    .label {
      font: 600 22px system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      fill: var(--label);
    }
    .value {
      font: 500 18px system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      fill: var(--value);
    }
    .legend-row {
      opacity: 0;
    }
  ]]></style>
</defs>
        """.strip()
    )

    start_angle = -90.0
    delay = 1.02
    for idx, (language, value) in enumerate(items):
        color = color_for_index(idx)

        available = max(1.0, 360.0 - gap_deg * len(items))
        raw_span = max(1.0, available * (value / total))

        seg_start = start_angle + gap_deg / 2.0
        seg_end = seg_start + raw_span

        path_d = arc_path(cx, cy, radius, seg_start, seg_end)
        arc_len = math.radians(seg_end - seg_start) * radius
        dur = (value / total) * 2

        svg.append(
            f'<path d="{path_d}" fill="none" stroke="{color}" '
            f'stroke-width="{stroke_width}" stroke-linecap="round" stroke-linejoin="round" '
            f'stroke-dasharray="{arc_len:.2f} {arc_len:.2f}" stroke-dashoffset="{arc_len:.2f}">'
        )
        svg.append(
            f'  <animate attributeName="stroke-dashoffset" from="{arc_len:.2f}" to="0" '
            f'dur="{dur:.2f}s" begin="{delay:.2f}s" fill="freeze" />'
        )
        svg.append("</path>")

        delay += dur
        start_angle = seg_end + gap_deg / 2.0

    for idx, (language, value) in enumerate(items):
        pct = (value / total) * 100.0
        y = top_y + idx * row_h
        color = color_for_index(idx)
        begin = 1.3 + idx * 0.08

        svg.append(
            f'<g class="legend-row" transform="translate({left_x},{y})">'
        )
        svg.append(
            f'  <animate attributeName="opacity" from="0" to="1" '
            f'dur="0.25s" begin="{begin:.2f}s" fill="freeze" />'
        )
        svg.append(
            f'  <rect x="0" y="0" width="18" height="18" rx="6" ry="6" fill="{color}" />'
        )
        svg.append(
            f'  <text x="30" y="16" class="label">{escape(language)}</text>'
        )
        svg.append(
            f'  <text x="250" y="16" class="value">{pct:.1f}%</text>'
        )
        svg.append("</g>")

    svg.append("</svg>")

    with open(output, "w", encoding="utf-8") as f:
        f.write("\n".join(svg))
        

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a transparent animated SVG doughnut chart from GitHub commit languages."
    )
    parser.add_argument("--author", default=os.environ.get("AUTHOR") or os.environ.get("GITHUB_ACTOR"))
    parser.add_argument("--max-commits", type=int, default=int(os.environ.get("MAX_COMMITS", "200")))
    parser.add_argument("--output", default=os.environ.get("OUTPUT", "language-donut.svg"))
    parser.add_argument("--title", default=os.environ.get("TITLE", "Commit language mix"))
    args = parser.parse_args()

    if not args.author:
        raise SystemExit("AUTHOR or GITHUB_ACTOR must be set.")

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is required.")

    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "commit-language-chart",
        }
    )

    counts = collections.Counter()

    for full_name, sha in search_commits(session, args.author, args.max_commits):
        detail = get_commit(session, full_name, sha)
        seen_files = set()

        for file in detail.get("files", []):
            filename = file.get("filename", "")
            if filename in seen_files:
                continue
            seen_files.add(filename)

            language = infer_language(filename)
            if language:
                counts[language] += 1

    build_svg(dict(counts), args.output, args.title)


if __name__ == "__main__":
    main()
