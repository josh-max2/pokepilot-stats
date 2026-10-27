"""Snapshot the public TikTok stats of @pokepilot2 and the two side channels (@pokepilot.hill, @pokepilot.raids; added
2026-10-27): per-video views/likes/comments/shares (yt-dlp, no login) and each profile's follower/like totals (the public
profile page's embedded JSON).

    python track.py

Main account: appends to data/snapshots.csv and data/account.csv and rewrites data/latest.json, which the dashboard
(index.html) reads. Side channels: the same three files under data/hill/ and data/raids/. A side channel failing never
fails the run. Run hourly by .github/workflows/track.yml.
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

HANDLE = "pokepilot2"
SIDE = {"pokepilot.hill": "hill", "pokepilot.raids": "raids"}     # handle -> data subfolder
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")
STATE_RE = re.compile(r'<script[^>]*id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>([^<]+)</script>')


def videos(handle: str, required: bool) -> list[dict]:
    out = subprocess.run([sys.executable, "-m", "yt_dlp", "--flat-playlist", "-J", f"https://www.tiktok.com/@{handle}"],
                         capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        if not required:
            print(f"@{handle}: yt-dlp failed: {out.stderr[-300:]}", file=sys.stderr)
            return []
        raise SystemExit(f"yt-dlp failed:\n{out.stderr[-2000:]}")
    entries = json.loads(out.stdout).get("entries") or []
    if not entries and required:
        raise SystemExit("yt-dlp returned no videos (blocked or profile private?)")
    return entries


def account(handle: str) -> dict | None:
    """Follower / total-like counts from the public profile page; None if TikTok serves a challenge."""
    req = urllib.request.Request(f"https://www.tiktok.com/@{handle}", headers={
        "User-Agent": UA, "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            if r.headers.get("content-encoding") == "gzip":
                raw = gzip.decompress(raw)
        m = STATE_RE.search(raw.decode("utf-8", "ignore"))
        stats = json.loads(m.group(1))["__DEFAULT_SCOPE__"]["webapp.user-detail"]["userInfo"]["stats"]
        return {"followers": int(stats["followerCount"]), "likes": int(stats["heartCount"]),
                "videos": int(stats["videoCount"])}
    except Exception as exc:  # noqa: BLE001 - the per-video pull still counts as a good run
        print(f"@{handle}: profile stats unavailable: {exc}", file=sys.stderr)
        return None


def append(path: Path, header: list[str], rows: list[list]) -> None:
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        w.writerows(rows)


def snapshot(handle: str, data: Path, now: str, required: bool) -> str:
    data.mkdir(parents=True, exist_ok=True)
    vids = videos(handle, required)
    if vids:
        append(data / "snapshots.csv", ["at", "id", "views", "likes", "comments", "shares"],
               [[now, e["id"], e.get("view_count") or 0, e.get("like_count") or 0, e.get("comment_count") or 0,
                 e.get("repost_count") or 0] for e in vids])
    acct = account(handle)
    if acct:
        append(data / "account.csv", ["at", "followers", "likes", "videos"],
               [[now, acct["followers"], acct["likes"], acct["videos"]]])
    latest = {
        "updated": now,
        "handle": handle,
        "account": acct,
        "videos": [{
            "id": e["id"],
            "url": f"https://www.tiktok.com/@{handle}/video/{e['id']}",
            "posted": dt.datetime.fromtimestamp(e.get("timestamp") or 0, dt.timezone.utc).isoformat(),
            "caption": e.get("description") or e.get("title") or "",
            "views": e.get("view_count") or 0,
            "likes": e.get("like_count") or 0,
            "comments": e.get("comment_count") or 0,
            "shares": e.get("repost_count") or 0,
        } for e in vids],
    }
    (data / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=1), encoding="utf-8")
    return f"@{handle}: {len(vids)} videos" + (f", {acct['followers']} followers" if acct else "")


def main() -> None:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    print(now, snapshot(HANDLE, DATA, now, required=True))
    for handle, sub in SIDE.items():
        try:
            print(now, snapshot(handle, DATA / sub, now, required=False))
        except Exception as exc:  # noqa: BLE001
            print(f"@{handle}: skipped ({exc})", file=sys.stderr)


if __name__ == "__main__":
    main()
