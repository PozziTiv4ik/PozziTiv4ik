#!/usr/bin/env python3
"""Generate the profile README and SVG assets from public GitHub activity."""

from __future__ import annotations

import hashlib
import html
import json
import os
import random
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

USERNAME = "PozziTiv4ik"
ROOT = Path(__file__).resolve().parents[1]
API_ROOT = "https://api.github.com"
GRAPHQL_URL = "https://api.github.com/graphql"


@dataclass(frozen=True)
class Metrics:
    merged_prs: int
    open_prs: int
    public_repos: int
    contributions: int
    active_days: int
    recent_merges: tuple[dict[str, str], ...]
    refreshed_at: str


def request_json(url: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{USERNAME}-profile-generator",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body = None
    method = "GET"
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"

    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def search_pull_requests(qualifiers: str) -> dict[str, Any]:
    query = f"is:pr author:{USERNAME} is:public {qualifiers}".strip()
    params = urllib.parse.urlencode(
        {"q": query, "sort": "updated", "order": "desc", "per_page": 100}
    )
    return request_json(f"{API_ROOT}/search/issues?{params}")


def fetch_metrics() -> Metrics:
    merged = search_pull_requests("is:merged")
    opened = search_pull_requests("is:open")
    user = request_json(f"{API_ROOT}/users/{USERNAME}")

    now = datetime.now(UTC)
    start = now - timedelta(days=364)
    query = """
      query($login: String!, $from: DateTime!, $to: DateTime!) {
        user(login: $login) {
          contributionsCollection(from: $from, to: $to) {
            restrictedContributionsCount
            contributionCalendar {
              totalContributions
              weeks {
                contributionDays { date contributionCount }
              }
            }
          }
        }
      }
    """
    contribution_data = request_json(
        GRAPHQL_URL,
        payload={
            "query": query,
            "variables": {
                "login": USERNAME,
                "from": start.isoformat().replace("+00:00", "Z"),
                "to": now.isoformat().replace("+00:00", "Z"),
            },
        },
    )
    collection = contribution_data["data"]["user"]["contributionsCollection"]
    calendar = collection["contributionCalendar"]
    restricted = int(collection.get("restrictedContributionsCount", 0))
    public_contributions = max(0, int(calendar["totalContributions"]) - restricted)
    days = [
        day
        for week in calendar["weeks"]
        for day in week["contributionDays"]
        if int(day["contributionCount"]) > 0
    ]

    recent: list[dict[str, str]] = []
    seen_repositories: set[str] = set()
    for item in merged.get("items", []):
        repository = str(item["repository_url"]).split("/repos/", 1)[-1]
        if repository.lower().startswith(f"{USERNAME.lower()}/"):
            continue
        if repository in seen_repositories:
            continue
        seen_repositories.add(repository)
        recent.append(
            {
                "repository": repository,
                "title": str(item["title"]),
                "url": str(item["html_url"]),
                "date": str(item.get("closed_at") or item.get("updated_at") or "")[:10],
            }
        )
        if len(recent) == 6:
            break

    return Metrics(
        merged_prs=int(merged["total_count"]),
        open_prs=int(opened["total_count"]),
        public_repos=int(user["public_repos"]),
        contributions=public_contributions,
        active_days=len(days),
        recent_merges=tuple(recent),
        refreshed_at=now.strftime("%Y-%m-%d UTC"),
    )


def markdown_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def render_recent_merges(metrics: Metrics) -> str:
    if not metrics.recent_merges:
        return "_The first upstream merge is loading…_"

    rows = ["| Project | Merged contribution | Date |", "|---|---|---:|"]
    for merge in metrics.recent_merges:
        project = markdown_escape(merge["repository"])
        title = markdown_escape(merge["title"])
        rows.append(
            f"| [{project}](https://github.com/{merge['repository']}) "
            f"| [{title}]({merge['url']}) | {merge['date']} |"
        )
    return "\n".join(rows)


def render_readme(metrics: Metrics) -> str:
    template = (ROOT / "README.template.md").read_text(encoding="utf-8")
    replacements = {
        "{{RECENT_MERGES}}": render_recent_merges(metrics),
        "{{UPDATED_AT}}": metrics.refreshed_at,
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    if "{{" in template or "}}" in template:
        raise ValueError("README template still contains an unresolved marker")
    return template


def render_signal_svg(metrics: Metrics) -> str:
    cards = (
        ("MERGED UPSTREAM", metrics.merged_prs, "#4ade80"),
        ("OPEN PULL REQUESTS", metrics.open_prs, "#22d3ee"),
        ("PUBLIC REPOSITORIES", metrics.public_repos, "#a78bfa"),
        ("CONTRIBUTIONS / 12MO", metrics.contributions, "#fbbf24"),
    )
    card_markup: list[str] = []
    for index, (label, value, color) in enumerate(cards):
        x = 30 + index * 290
        card_markup.append(
            f'<g transform="translate({x} 47)">'
            '<rect width="270" height="94" rx="14" fill="#111827" stroke="#293548"/>'
            f'<rect width="5" height="94" rx="2.5" fill="{color}"/>'
            f'<text x="24" y="34" class="label">{html.escape(label)}</text>'
            f'<text x="24" y="73" class="value" fill="{color}">{value:,}</text>'
            "</g>"
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="165" viewBox="0 0 1200 165" role="img" aria-labelledby="title desc">
  <title id="title">Live GitHub signal for {USERNAME}</title>
  <desc id="desc">{metrics.merged_prs} merged pull requests, {metrics.open_prs} open pull requests, {metrics.public_repos} public repositories, and {metrics.contributions} public contributions in the last twelve months.</desc>
  <style>
    .mono{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}
    .label{{font:700 13px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;letter-spacing:1.1px;fill:#8190a8}}
    .value{{font:900 31px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}
  </style>
  <rect width="1200" height="165" rx="20" fill="#0b1020"/>
  <rect x="1" y="1" width="1198" height="163" rx="19" fill="none" stroke="#293548"/>
  <text x="30" y="29" class="mono" font-size="13" font-weight="700" fill="#64748b">LIVE GITHUB SIGNAL · {html.escape(metrics.refreshed_at)}</text>
  {"".join(card_markup)}
</svg>
"""


def mine_positions(
    cols: int, rows: int, count: int, seed_text: str
) -> set[tuple[int, int]]:
    seed = int.from_bytes(hashlib.sha256(seed_text.encode("utf-8")).digest()[:8], "big")
    rng = random.Random(seed)
    protected = {(x, y) for x in range(3) for y in range(3)}
    candidates = [
        (x, y) for y in range(rows) for x in range(cols) if (x, y) not in protected
    ]
    rng.shuffle(candidates)
    return set(candidates[:count])


def neighboring_mines(
    x: int, y: int, mines: set[tuple[int, int]], cols: int, rows: int
) -> int:
    return sum(
        (nx, ny) in mines
        for ny in range(max(0, y - 1), min(rows, y + 2))
        for nx in range(max(0, x - 1), min(cols, x + 2))
        if (nx, ny) != (x, y)
    )


def render_minesweeper_svg(metrics: Metrics) -> str:
    cols, rows = 28, 7
    cell, gap = 31, 4
    board_width = cols * cell + (cols - 1) * gap
    board_x = (1200 - board_width) // 2
    board_y = 152
    mine_count = min(34, max(18, metrics.merged_prs + metrics.active_days + 12))
    mines = mine_positions(
        cols, rows, mine_count, f"{USERNAME}:{datetime.now(UTC).year}"
    )
    number_colors = {
        1: "#22d3ee",
        2: "#4ade80",
        3: "#fbbf24",
        4: "#a78bfa",
        5: "#fb7185",
        6: "#2dd4bf",
        7: "#f8fafc",
        8: "#94a3b8",
    }

    safe_cells = [
        (x, y) for y in range(rows) for x in range(cols) if (x, y) not in mines
    ]
    jitter_seed = int.from_bytes(
        hashlib.sha256(f"{USERNAME}:reveal".encode()).digest()[:8], "big"
    )
    jitter = random.Random(jitter_seed)
    safe_cells.sort(key=lambda point: point[0] + point[1] * 1.7 + jitter.random() * 1.8)
    reveal_index = {point: index for index, point in enumerate(safe_cells)}

    cells: list[str] = []
    flag_index = 0
    for y in range(rows):
        for x in range(cols):
            px = board_x + x * (cell + gap)
            py = board_y + y * (cell + gap)
            base = f'<rect x="{px}" y="{py}" width="{cell}" height="{cell}" rx="4" class="open-cell"/>'
            if (x, y) in mines:
                delay = 5.4 + flag_index * 0.075
                flag_index += 1
                cells.append(
                    f"<g>{base}"
                    f'<rect x="{px}" y="{py}" width="{cell}" height="{cell}" rx="4" class="mine-cover"/>'
                    f'<g class="flag" opacity="0" transform="translate({px + 8} {py + 6})">'
                    '<path d="M3 20V2m0 2h14l-4.5 5L17 14H3" fill="#4ade80" stroke="#86efac" stroke-width="1.6" stroke-linejoin="round"/>'
                    '<path d="M0 23h10" stroke="#86efac" stroke-width="2" stroke-linecap="round"/>'
                    f'<animate attributeName="opacity" values="0;0;1;1;0;0" keyTimes="0;.05;.12;.72;.88;1" dur="20s" begin="{delay:.3f}s" repeatCount="indefinite"/>'
                    "</g></g>"
                )
                continue

            count = neighboring_mines(x, y, mines, cols, rows)
            delay = 0.5 + reveal_index[(x, y)] * 0.027
            content = ""
            if count:
                color = number_colors[count]
                content = (
                    f'<text x="{px + cell / 2:.1f}" y="{py + 22}" text-anchor="middle" '
                    f'class="number safe-content" fill="{color}" opacity="0">{count}'
                    f'<animate attributeName="opacity" values="0;0;1;1;0;0" keyTimes="0;.05;.12;.72;.88;1" dur="20s" begin="{delay:.3f}s" repeatCount="indefinite"/>'
                    "</text>"
                )
            cells.append(
                f"<g>{base}{content}"
                f'<rect x="{px}" y="{py}" width="{cell}" height="{cell}" rx="4" class="cover">'
                f'<animate attributeName="opacity" values="1;1;0;0;1;1" keyTimes="0;.05;.12;.72;.88;1" dur="20s" begin="{delay:.3f}s" repeatCount="indefinite"/>'
                "</rect>"
                "</g>"
            )

    description = (
        f"Animated Minesweeper board generated from {metrics.contributions} public contributions, "
        f"{metrics.merged_prs} merged pull requests, and {metrics.active_days} active contribution days."
    )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="460" viewBox="0 0 1200 460" role="img" aria-labelledby="title desc">
  <title id="title">{USERNAME}'s contribution minefield</title>
  <desc id="desc">{html.escape(description)}</desc>
  <defs>
    <linearGradient id="mineBg" x1="0" y1="0" x2="1" y2="1">
      <stop stop-color="#090d18"/><stop offset=".55" stop-color="#0c1324"/><stop offset="1" stop-color="#07191a"/>
    </linearGradient>
    <pattern id="mineGrid" width="30" height="30" patternUnits="userSpaceOnUse">
      <path d="M30 0H0V30" fill="none" stroke="#22d3ee" stroke-opacity=".035"/>
    </pattern>
    <filter id="cursorGlow" x="-60%" y="-60%" width="220%" height="220%">
      <feGaussianBlur stdDeviation="5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  <style>
    .mono{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}
    .number{{font:900 18px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}
    .open-cell{{fill:#0d1728;stroke:#1f3048;stroke-width:1}}
    .cover,.mine-cover{{fill:#26334a;stroke:#49607e;stroke-width:1.2}}
    .cursor{{animation:cursorPulse 1.1s ease-in-out infinite alternate}}
    @keyframes cursorPulse{{from{{opacity:.35}}to{{opacity:1}}}}
    @media (prefers-reduced-motion:reduce){{
      .cover{{display:none}}.safe-content,.flag,.cleared{{opacity:1!important}}.scanning,.cursor{{display:none}}
    }}
  </style>
  <rect width="1200" height="460" rx="22" fill="url(#mineBg)"/>
  <rect width="1200" height="460" rx="22" fill="url(#mineGrid)"/>
  <rect x="1" y="1" width="1198" height="458" rx="21" fill="none" stroke="#2b3b51"/>

  <g class="mono">
    <text x="44" y="48" fill="#c4b5fd" font-size="24" font-weight="900">CONTRIBUTION MINEFIELD</text>
    <text x="44" y="76" fill="#64748b" font-size="14">AUTO-GENERATED FROM PUBLIC GITHUB ACTIVITY</text>

    <g transform="translate(650 25)">
      <rect width="150" height="61" rx="11" fill="#111827" stroke="#334155"/>
      <text x="16" y="23" fill="#64748b" font-size="11" font-weight="700">MINES</text>
      <text x="16" y="49" fill="#fb7185" font-size="24" font-weight="900">{mine_count:03d}</text>
      <rect x="164" width="150" height="61" rx="11" fill="#111827" stroke="#334155"/>
      <text x="180" y="23" fill="#64748b" font-size="11" font-weight="700">MERGED</text>
      <text x="180" y="49" fill="#4ade80" font-size="24" font-weight="900">{metrics.merged_prs:03d}</text>
      <rect x="328" width="174" height="61" rx="11" fill="#111827" stroke="#334155"/>
      <text x="344" y="23" fill="#64748b" font-size="11" font-weight="700">CONTRIBUTIONS</text>
      <text x="344" y="49" fill="#22d3ee" font-size="24" font-weight="900">{metrics.contributions:04d}</text>
    </g>

    <text x="44" y="121" class="scanning" fill="#22d3ee" font-size="15" font-weight="700">&gt; SCANNING SAFE CELLS...
      <animate attributeName="opacity" values="1;1;0;0;1;1" keyTimes="0;.34;.4;.72;.78;1" dur="20s" repeatCount="indefinite"/>
    </text>
    <text x="44" y="121" class="cleared" fill="#4ade80" font-size="15" font-weight="700" opacity="0">&gt; FIELD CLEARED — KEEP SHIPPING.
      <animate attributeName="opacity" values="0;0;1;1;0;0" keyTimes="0;.34;.4;.72;.78;1" dur="20s" repeatCount="indefinite"/>
    </text>
  </g>

  {"".join(cells)}

  <rect class="cursor" x="{board_x - 5}" y="{board_y - 5}" width="41" height="41" rx="7" fill="none" stroke="#22d3ee" stroke-width="2" filter="url(#cursorGlow)">
    <animate attributeName="x" values="{board_x - 5};{board_x + board_width - 36};{board_x - 5}" dur="8s" repeatCount="indefinite"/>
  </rect>
  <text x="600" y="431" text-anchor="middle" class="mono" fill="#64748b" font-size="13">Every safe click is a test. Every cleared field is a merge.</text>
</svg>
'''


def write_if_changed(path: Path, content: str) -> None:
    normalized = content.replace("\r\n", "\n")
    if (
        path.exists()
        and path.read_text(encoding="utf-8").replace("\r\n", "\n") == normalized
    ):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalized, encoding="utf-8", newline="\n")


def main() -> None:
    metrics = fetch_metrics()
    write_if_changed(ROOT / "README.md", render_readme(metrics))
    write_if_changed(ROOT / "assets" / "signal.svg", render_signal_svg(metrics))
    write_if_changed(
        ROOT / "assets" / "minesweeper.svg", render_minesweeper_svg(metrics)
    )
    print(
        f"Generated profile: {metrics.merged_prs} merged PRs, "
        f"{metrics.open_prs} open PRs, {metrics.contributions} contributions."
    )


if __name__ == "__main__":
    main()
