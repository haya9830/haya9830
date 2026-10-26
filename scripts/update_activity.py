#!/usr/bin/env python3
"""Render a public-only GitHub activity card with the bundled gh CLI.

Run in the profile repository's GitHub Actions workflow. It supplies the
repository GITHUB_TOKEN as GH_TOKEN. Local authenticated queries are refused:
the owner's login could see activity from other private repositories.
No personal token or third-party service is needed.

GitHub documents private/internal collection data as requiring read:user:
https://docs.github.com/en/graphql/reference/users#contributionscollection
Only the public profile repository's workflow token is used. Anonymous
restricted counts are subtracted from each month's calendar total, never
displayed. Do not replace this token with a personal access token.
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timedelta, timezone


USERNAME = "haya9830"
JST = timezone(timedelta(hours=9))
UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "activity.svg"
MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def month_start(year: int, month: int, offset: int) -> datetime:
    index = year * 12 + month - 1 + offset
    return datetime(index // 12, index % 12 + 1, 1, tzinfo=UTC)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def fetch_months(now: datetime) -> list[dict[str, int | datetime]]:
    starts = [month_start(now.year, now.month, offset) for offset in range(-11, 1)]
    fields = []
    for index, start in enumerate(starts):
        end = min(month_start(start.year, start.month, 1) - timedelta(seconds=1), now)
        fields.append(
            f'm{index}: contributionsCollection(from:"{iso_utc(start)}",to:"{iso_utc(end)}") {{'
            " restrictedContributionsCount totalCommitContributions totalPullRequestContributions"
            " contributionCalendar { totalContributions } }"
        )
    query = 'query { user(login:"' + USERNAME + '") { ' + " ".join(fields) + " } }"
    result = subprocess.run(
        ["gh", "api", "graphql", "--include", "-f", "query=" + query],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if result.returncode:
        # Do not print API bodies or the environment, which may contain private data.
        raise RuntimeError("GitHub API request failed; verify gh authentication and retry.")
    header_text, separator, body = result.stdout.partition("\n\n")
    if not separator:
        raise RuntimeError("Unexpected GitHub response: headers were not found.")
    payload = json.loads(body)
    if payload.get("errors") or not payload.get("data", {}).get("user"):
        raise RuntimeError("GitHub did not return the requested public contributions.")
    collections = payload["data"]["user"]
    months = []
    for index, start in enumerate(starts):
        collection = collections[f"m{index}"]
        public_total = collection["contributionCalendar"]["totalContributions"] - collection["restrictedContributionsCount"]
        counts = {
            "contributions": public_total,
            "commits": collection["totalCommitContributions"],
            "pull_requests": collection["totalPullRequestContributions"],
        }
        if any(not isinstance(value, int) or value < 0 for value in counts.values()):
            raise RuntimeError("GitHub returned an invalid contribution count.")
        if counts["commits"] + counts["pull_requests"] > public_total:
            raise RuntimeError("Contribution counts are inconsistent; the existing card was preserved.")
        months.append({"start": start, **counts})
    return months


def render(months: list[dict[str, int | datetime]], now: datetime) -> str:
    first = months[0]["start"]
    assert isinstance(first, datetime)
    period = f"{MONTH_NAMES[first.month - 1]} {first.year} - {MONTH_NAMES[now.month - 1]} {now.year}"
    total = sum(int(month["contributions"]) for month in months)
    commits = sum(int(month["commits"]) for month in months)
    pull_requests = sum(int(month["pull_requests"]) for month in months)
    description = f"Public GitHub contributions for {USERNAME}, {period}, using UTC calendar months: {total} contributions, {commits} commits, {pull_requests} opened pull requests. Current month is incomplete."
    pieces = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="960" height="300" viewBox="0 0 960 300" role="img" aria-labelledby="title description">',
        '<title id="title">Public GitHub activity - haya9830</title>',
        f'<desc id="description">{html.escape(description)}</desc>',
        '<rect x="0.5" y="0.5" width="959" height="299" rx="18" fill="#0d1b16" stroke="#284b38"/>',
        '<g font-family="Arial, Helvetica, sans-serif">',
        '<rect x="32" y="29" width="5" height="17" rx="2" fill="#9cdda8"/>',
        '<text x="48" y="43" fill="#dff2e4" font-size="16" font-weight="700" letter-spacing="1">PUBLIC GITHUB ACTIVITY</text>',
        f'<text x="925" y="42" fill="#9ab9a5" font-size="12" text-anchor="end">Updated {now.astimezone(JST):%Y-%m-%d} JST</text>',
    ]
    metrics = [(32, total, "Contributions"), (250, commits, "Commits"), (468, pull_requests, "Pull requests opened")]
    for x, value, label in metrics:
        pieces.append(f'<text x="{x}" y="98" fill="#f0f7f1" font-size="36" font-weight="700">{value:,}</text>')
        pieces.append(f'<text x="{x}" y="120" fill="#9ab9a5" font-size="12">{label}</text>')
    pieces.extend([
        '<text x="925" y="100" fill="#dff2e4" font-size="12" text-anchor="end">Monthly contributions</text>',
        f'<text x="925" y="120" fill="#9ab9a5" font-size="11" text-anchor="end">{period}</text>',
        '<path d="M32 242H928" stroke="#284b38"/>',
    ])
    maximum = max(int(month["contributions"]) for month in months) or 1
    for index, month in enumerate(months):
        start = month["start"]
        assert isinstance(start, datetime)
        count = int(month["contributions"])
        center = 68 + index * 74.5
        height = max(3, round(count / maximum * 75))
        top = 242 - height
        fill = "#9cdda8" if index == len(months) - 1 else "#4d9469"
        pieces.append(f'<rect x="{center - 22:.1f}" y="{top}" width="44" height="{height}" rx="4" fill="{fill}"><title>{start:%Y-%m}: {count} public contributions</title></rect>')
        if count:
            pieces.append(f'<text x="{center:.1f}" y="{top - 8}" fill="#dff2e4" font-size="11" text-anchor="middle">{count}</text>')
        pieces.append(f'<text x="{center:.1f}" y="260" fill="#a9c4b2" font-size="11" text-anchor="middle">{MONTH_NAMES[start.month - 1]}</text>')
    pieces.extend([
        '<text x="32" y="284" fill="#9ab9a5" font-size="10">UTC calendar months. Public repositories only. Current month in progress. GitHub contribution rules apply.</text>',
        '</g>',
        '</svg>',
    ])
    return "\n".join(pieces) + "\n"


def main() -> int:
    now = datetime.now(UTC).replace(microsecond=0)
    try:
        if (
            os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_REPOSITORY") != "haya9830/haya9830"
            or not os.environ.get("GH_TOKEN")
        ):
            raise RuntimeError("Run this updater in haya9830/haya9830 GitHub Actions with its repository GITHUB_TOKEN; local authenticated generation is disabled.")
        months = fetch_months(now)
        svg = render(months, now)
        # Check XML before replacing an existing, working image.
        import xml.etree.ElementTree as ET

        ET.fromstring(svg)
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(svg, encoding="utf-8")
        print(f"Updated {OUTPUT.relative_to(ROOT)}: {sum(int(m['contributions']) for m in months)} public contributions across 12 calendar months.")
        return 0
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
