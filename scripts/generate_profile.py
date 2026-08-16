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
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    if "{{" in template or "}}" in template:
        raise ValueError("README template still contains an unresolved marker")
    return template


def render_signal_svg(metrics: Metrics) -> str:
    cards = (
        ("Merged upstream", metrics.merged_prs),
        ("Open pull requests", metrics.open_prs),
        ("Public repositories", metrics.public_repos),
        ("Contributions", metrics.contributions),
    )
    card_markup: list[str] = []
    for index, (label, value) in enumerate(cards):
        x = index * 290
        card_markup.append(
            f'<g transform="translate({x} 0)">'
            '<rect class="card" width="270" height="92" rx="6"/>'
            f'<text x="18" y="34" class="label">{html.escape(label)}</text>'
            f'<text x="18" y="70" class="value">{value:,}</text>'
            "</g>"
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="92" viewBox="0 0 1140 92" role="img" aria-labelledby="title desc">
  <title id="title">GitHub activity for {USERNAME}</title>
  <desc id="desc">{metrics.merged_prs} merged pull requests, {metrics.open_prs} open pull requests, {metrics.public_repos} public repositories, and {metrics.contributions} public contributions in the last twelve months.</desc>
  <style>
    :root{{color-scheme:light dark}}
    .card{{fill:#f6f8fa;stroke:#d0d7de}}
    .label{{font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;fill:#656d76}}
    .value{{font:600 28px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;fill:#1f2328}}
    @media(prefers-color-scheme:dark){{
      .card{{fill:#0d1117;stroke:#30363d}}
      .label{{fill:#8b949e}}
      .value{{fill:#f0f6fc}}
    }}
  </style>
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
    cycle = 24.0
    reset_at = 21.2
    cols, rows = 28, 7
    cell, gap = 31, 4
    board_width = cols * cell + (cols - 1) * gap
    board_height = rows * cell + (rows - 1) * gap
    board_x = 0
    board_y = 0
    mine_count = min(34, max(18, metrics.merged_prs + metrics.active_days + 12))
    mines = mine_positions(
        cols, rows, mine_count, f"{USERNAME}:{datetime.now(UTC).year}"
    )

    def point_position(point: tuple[int, int]) -> tuple[float, float]:
        x, y = point
        return (
            board_x + x * (cell + gap) + cell / 2,
            board_y + y * (cell + gap) + cell / 2,
        )

    def cursor_position(point: tuple[int, int]) -> tuple[float, float]:
        x, y = point_position(point)
        margin = 22
        return (
            min(board_width - margin, max(margin, x)),
            min(board_height - margin, max(margin, y)),
        )

    def animation_times(*seconds: float) -> str:
        return ";".join(f"{min(1, max(0, value / cycle)):.4f}" for value in seconds)

    def reveal_animation(reveal_at: float, *, inverted: bool) -> str:
        before = max(0, reveal_at - 0.16)
        after_reset = min(cycle, reset_at + 0.38)
        values = "0;0;1;1;0;0" if inverted else "1;1;0;0;1;1"
        return (
            f'<animate attributeName="opacity" values="{values}" '
            f'keyTimes="{animation_times(0, before, reveal_at, reset_at, after_reset, cycle)}" '
            f'dur="{cycle:g}s" repeatCount="indefinite"/>'
        )

    safe_cells = [
        (x, y) for y in range(rows) for x in range(cols) if (x, y) not in mines
    ]
    counts = {
        point: neighboring_mines(*point, mines, cols, rows) for point in safe_cells
    }
    zero_cells = [point for point in safe_cells if counts[point] == 0]

    click_aims = ((2, 3), (14, 1), (24, 5))
    click_cells: list[tuple[int, int]] = []
    for aim_x, aim_y in click_aims:
        candidates = [point for point in zero_cells if point not in click_cells]
        if not candidates:
            candidates = [point for point in safe_cells if point not in click_cells]
        click_cells.append(
            min(
                candidates,
                key=lambda point: (point[0] - aim_x) ** 2 + (point[1] - aim_y) ** 2,
            )
        )

    mine_regions = (
        sorted(
            (point for point in mines if point[0] < 9),
            key=lambda point: (point[1], point[0]),
        ),
        sorted(
            (point for point in mines if 9 <= point[0] < 19),
            key=lambda point: (point[1], point[0]),
        ),
        sorted(
            (point for point in mines if point[0] >= 19),
            key=lambda point: (point[1], point[0]),
        ),
    )
    flag_cells = [
        min(
            region or tuple(mines),
            key=lambda point: (point[0] - aim[0]) ** 2 + (point[1] - aim[1]) ** 2,
        )
        for region, aim in zip(mine_regions, ((6, 2), (15, 4), (23, 2)), strict=True)
    ]

    jitter_seed = int.from_bytes(
        hashlib.sha256(f"{USERNAME}:reveal".encode()).digest()[:8], "big"
    )
    jitter = random.Random(jitter_seed)
    cascade_starts = (1.6, 6.3, 13.1)
    reveal_at: dict[tuple[int, int], float] = {}
    for point in safe_cells:
        phase = min(
            range(len(click_cells)),
            key=lambda index: (
                (point[0] - click_cells[index][0]) ** 2
                + (point[1] - click_cells[index][1]) ** 2
            ),
        )
        distance = (
            (point[0] - click_cells[phase][0]) ** 2
            + (point[1] - click_cells[phase][1]) ** 2
        ) ** 0.5
        reveal_at[point] = (
            cascade_starts[phase] + distance * 0.16 + jitter.random() * 0.12
        )

    flag_starts = (4.45, 9.65, 11.95)
    mine_reveal_at: dict[tuple[int, int], float] = {}
    for phase, region in enumerate(mine_regions):
        for index, point in enumerate(region):
            mine_reveal_at[point] = flag_starts[phase] + index * 0.075

    cells: list[str] = []
    for y in range(rows):
        for x in range(cols):
            px = board_x + x * (cell + gap)
            py = board_y + y * (cell + gap)
            base = f'<rect x="{px}" y="{py}" width="{cell}" height="{cell}" rx="4" class="open-cell"/>'
            if (x, y) in mines:
                flag_at = mine_reveal_at[(x, y)]
                cells.append(
                    f"<g>{base}"
                    f'<rect x="{px}" y="{py}" width="{cell}" height="{cell}" rx="4" class="mine-cover"/>'
                    f'<g class="flag" opacity="0" transform="translate({px + 8} {py + 6})">'
                    '<path class="flag-cloth" d="M3 20V2m0 2h14l-4.5 5L17 14H3" stroke-width="1.6" stroke-linejoin="round"/>'
                    '<path class="flag-pole" d="M0 23h10" stroke-width="2" stroke-linecap="round"/>'
                    f"{reveal_animation(flag_at, inverted=True)}"
                    "</g></g>"
                )
                continue

            count = counts[(x, y)]
            cell_reveal = reveal_at[(x, y)]
            content = ""
            if count:
                content = (
                    f'<text x="{px + cell / 2:.1f}" y="{py + 22}" text-anchor="middle" '
                    f'class="number n{count} safe-content" opacity="0">{count}'
                    f"{reveal_animation(cell_reveal, inverted=True)}"
                    "</text>"
                )
            cells.append(
                f"<g>{base}{content}"
                f'<rect x="{px}" y="{py}" width="{cell}" height="{cell}" rx="4" class="cover">'
                f"{reveal_animation(cell_reveal, inverted=False)}"
                "</rect>"
                "</g>"
            )

    click_pulses: list[str] = []
    for point, pulse_at in zip(click_cells, cascade_starts, strict=True):
        cx, cy = point_position(point)
        click_pulses.append(
            f'<circle class="pulse click-pulse" cx="{cx:.1f}" cy="{cy:.1f}" r="4" fill="none" stroke-width="3" opacity="0">'
            '<animate attributeName="opacity" values="0;0;1;0;0" '
            f'keyTimes="{animation_times(0, pulse_at, pulse_at + 0.08, pulse_at + 0.72, cycle)}" dur="{cycle:g}s" repeatCount="indefinite"/>'
            '<animate attributeName="r" values="4;4;7;30;30" '
            f'keyTimes="{animation_times(0, pulse_at, pulse_at + 0.08, pulse_at + 0.72, cycle)}" dur="{cycle:g}s" repeatCount="indefinite"/>'
            "</circle>"
        )

    flag_pulses: list[str] = []
    for point, pulse_at in zip(flag_cells, flag_starts, strict=True):
        cx, cy = point_position(point)
        flag_pulses.append(
            f'<circle class="pulse flag-pulse" cx="{cx:.1f}" cy="{cy:.1f}" r="5" opacity="0">'
            '<animate attributeName="opacity" values="0;0;1;0;0" '
            f'keyTimes="{animation_times(0, pulse_at, pulse_at + 0.08, pulse_at + 0.55, cycle)}" dur="{cycle:g}s" repeatCount="indefinite"/>'
            '<animate attributeName="r" values="5;5;12;22;22" '
            f'keyTimes="{animation_times(0, pulse_at, pulse_at + 0.08, pulse_at + 0.55, cycle)}" dur="{cycle:g}s" repeatCount="indefinite"/>'
            "</circle>"
        )

    danger_cell = flag_cells[2]
    danger_x = board_x + danger_cell[0] * (cell + gap)
    danger_y = board_y + danger_cell[1] * (cell + gap)
    danger_pulse = (
        f'<rect class="pulse danger-pulse" x="{danger_x - 3}" y="{danger_y - 3}" width="{cell + 6}" height="{cell + 6}" rx="7" '
        'fill-opacity=".12" stroke-width="3" opacity="0">'
        '<animate attributeName="opacity" values="0;0;1;.25;1;.25;0;0" '
        f'keyTimes="{animation_times(0, 10.85, 11.0, 11.25, 11.5, 11.75, 12.05, cycle)}" dur="{cycle:g}s" repeatCount="indefinite"/>'
        "</rect>"
    )

    route_points = [
        (22, 22),
        cursor_position(click_cells[0]),
        cursor_position(click_cells[0]),
        cursor_position(flag_cells[0]),
        cursor_position(flag_cells[0]),
        cursor_position(click_cells[1]),
        cursor_position(click_cells[1]),
        cursor_position(flag_cells[1]),
        cursor_position(flag_cells[1]),
        cursor_position(danger_cell),
        cursor_position(danger_cell),
        cursor_position(danger_cell),
        cursor_position(click_cells[2]),
        cursor_position(click_cells[2]),
        (board_width - 22, board_height - 22),
        (board_width - 22, 22),
        (board_width - 22, 22),
        (22, 22),
    ]
    route_times = (
        0,
        1.42,
        1.9,
        4.2,
        4.75,
        6.08,
        6.65,
        9.35,
        9.92,
        10.85,
        11.55,
        12.2,
        12.92,
        13.55,
        16.2,
        17.05,
        reset_at,
        cycle,
    )
    route_values = ";".join(f"{x:.1f} {y:.1f}" for x, y in route_points)

    route_path = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in route_points[1:14])

    confetti_rng = random.Random(jitter_seed ^ 0xC0FFEE)
    confetti_colors = ("#3fb950", "#58a6ff", "#a371f7", "#d29922", "#f85149")
    confetti: list[str] = []
    for index in range(30):
        x = confetti_rng.randint(10, board_width - 10)
        start = 16.3 + confetti_rng.random() * 0.9
        end = 20.5 + confetti_rng.random() * 0.35
        width = confetti_rng.randint(4, 9)
        height = confetti_rng.randint(8, 16)
        color = confetti_colors[index % len(confetti_colors)]
        confetti.append(
            f'<rect class="confetti" x="{x}" y="-18" width="{width}" height="{height}" rx="2" fill="{color}" opacity="0">'
            f'<animate attributeName="y" values="-18;-18;{board_height};{board_height}" '
            f'keyTimes="{animation_times(0, start, end, cycle)}" dur="{cycle:g}s" repeatCount="indefinite"/>'
            '<animate attributeName="opacity" values="0;0;1;0;0" '
            f'keyTimes="{animation_times(0, start, start + 0.18, end, cycle)}" dur="{cycle:g}s" repeatCount="indefinite"/>'
            "</rect>"
        )

    description = (
        f"A cursor plays an animated Minesweeper round generated from {metrics.contributions} public contributions, "
        f"{metrics.merged_prs} merged pull requests, and {metrics.active_days} active contribution days."
    )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{board_width}" height="{board_height}" viewBox="0 0 {board_width} {board_height}" role="img" aria-labelledby="title desc">
  <title id="title">{USERNAME}'s contribution minefield</title>
  <desc id="desc">{html.escape(description)}</desc>
  <style>
    :root{{color-scheme:light dark}}
    .number{{font:600 17px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}
    .open-cell{{fill:#f6f8fa;stroke:#d0d7de;stroke-width:1}}
    .cover,.mine-cover{{fill:#d8dee4;stroke:#afb8c1;stroke-width:1}}
    .n1{{fill:#0969da}}.n2{{fill:#1a7f37}}.n3{{fill:#cf222e}}.n4{{fill:#8250df}}
    .n5{{fill:#bc4c00}}.n6{{fill:#0a7a74}}.n7{{fill:#1f2328}}.n8{{fill:#656d76}}
    .flag-cloth{{fill:#1a7f37;stroke:#1a7f37}}.flag-pole{{stroke:#1a7f37}}
    .click-pulse{{stroke:#0969da}}.flag-pulse{{fill:#1a7f37}}
    .danger-pulse{{fill:#cf222e;stroke:#cf222e}}
    .route{{stroke:#0969da}}
    .player-core{{fill:#0969da;stroke:#0969da}}
    .player-pointer{{fill:#ffffff;stroke:#0969da}}
    .player-dot{{fill:#1a7f37}}
    .player-core{{animation:playerPulse .7s ease-in-out infinite alternate}}
    .route{{stroke-dasharray:8 11;animation:routeFlow 1s linear infinite}}
    @keyframes playerPulse{{from{{opacity:.55}}to{{opacity:1}}}}
    @keyframes routeFlow{{to{{stroke-dashoffset:-38}}}}
    @media(prefers-color-scheme:dark){{
      .open-cell{{fill:#161b22;stroke:#30363d}}
      .cover,.mine-cover{{fill:#21262d;stroke:#30363d}}
      .n1{{fill:#58a6ff}}.n2{{fill:#3fb950}}.n3{{fill:#f85149}}.n4{{fill:#a371f7}}
      .n5{{fill:#d29922}}.n6{{fill:#39c5cf}}.n7{{fill:#f0f6fc}}.n8{{fill:#8b949e}}
      .flag-cloth{{fill:#3fb950;stroke:#3fb950}}.flag-pole{{stroke:#3fb950}}
      .click-pulse{{stroke:#58a6ff}}.flag-pulse{{fill:#3fb950}}
      .danger-pulse{{fill:#f85149;stroke:#f85149}}
      .route{{stroke:#58a6ff}}.player-core{{fill:#58a6ff;stroke:#58a6ff}}
      .player-pointer{{fill:#f0f6fc;stroke:#58a6ff}}.player-dot{{fill:#3fb950}}
    }}
    @media (prefers-reduced-motion:reduce){{
      .cover{{display:none}}.safe-content,.flag{{opacity:1!important}}
      .player,.pulse,.confetti,.route{{display:none}}
    }}
  </style>
  <path class="route" d="{route_path}" fill="none" stroke-opacity=".1" stroke-width="2"/>
  {"".join(cells)}
  {danger_pulse}
  {"".join(click_pulses)}
  {"".join(flag_pulses)}

  {"".join(confetti)}

  <g class="player">
    <circle class="player-core" r="17" fill-opacity=".12" stroke-width="2"/>
    <path class="player-pointer" d="M-8-13v26l7-7 7 14 7-4-7-13h11z" stroke-width="1.5" stroke-linejoin="round"/>
    <circle class="player-dot" r="3.5"/>
    <animateTransform attributeName="transform" type="translate" values="{route_values}" keyTimes="{animation_times(*route_times)}" dur="{cycle:g}s" repeatCount="indefinite"/>
  </g>
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
