#!/usr/bin/env python3
"""Mine committers.top git history into time-series JSON for trend charts.

Outputs:
  site/src/data/history.json  - per-slug monthly samples (top 25 users)
  site/src/data/movers.json   - global top movers + per-login series

Usage: python3 scripts/extract_history.py
"""

import datetime
import json
import subprocess
import sys
from pathlib import Path

import yaml

try:
    from yaml import CSafeLoader as Loader
except ImportError:
    from yaml import SafeLoader as Loader

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT / "committers.top"
OUT_DIR = ROOT / "site" / "src" / "data"
REF = "origin/gh-pages"
LOC_PREFIX = "_data/locations"

MONTHS_BACK = 24
TOP_N = 25
MOVER_PREV_MIN = 200
MOVER_TOP = 50
SERIES_TOP = 20
NOW_WINDOW_DAYS = 45
PREV_TARGET_DAYS = 182
PREV_TOLERANCE_DAYS = 90


def git(*args):
    r = subprocess.run(
        ["git", "-C", str(REPO)] + list(args), capture_output=True, text=True
    )
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()[:200]}")
    return r.stdout


class BlobReader:
    """Single persistent `git cat-file --batch` process for fast blob reads."""

    def __init__(self):
        self.proc = subprocess.Popen(
            ["git", "-C", str(REPO), "cat-file", "--batch"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )

    def read(self, spec):
        self.proc.stdin.write(spec.encode() + b"\n")
        self.proc.stdin.flush()
        header = self.proc.stdout.readline().decode(errors="replace").strip()
        if not header or header.endswith(("missing", "ambiguous")):
            return None
        parts = header.split()
        try:
            size = int(parts[-1])
        except ValueError:
            return None
        data = self.proc.stdout.read(size)
        self.proc.stdout.read(1)
        return data.decode("utf-8", errors="replace")

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


def list_slugs():
    out = git("ls-tree", "--name-only", REF, f"{LOC_PREFIX}/")
    return sorted(
        Path(p).stem for p in out.split() if p.endswith((".yml", ".yaml"))
    )


def monthly_commits(slug):
    """One commit (the latest) per month, newest first, up to MONTHS_BACK months."""
    out = git(
        "log",
        "--format=%H %as",
        f"--since={MONTHS_BACK + 1}.months",
        REF,
        "--",
        f"{LOC_PREFIX}/{slug}.yml",
    )
    by_month = {}
    for line in out.strip().splitlines():
        try:
            sha, date = line.split()
        except ValueError:
            continue
        month = date[:7]
        if month not in by_month:
            by_month[month] = (sha, date)
    picked = [by_month[m] for m in sorted(by_month)[-MONTHS_BACK:]]
    return picked


def parse_sample(text):
    """Return (top users list, full users list) or None on bad data."""
    try:
        doc = yaml.load(text, Loader=Loader)
    except yaml.YAMLError:
        return None
    if not isinstance(doc, dict):
        return None
    users = doc.get("users")
    if not isinstance(users, list):
        return None
    clean = []
    for u in users:
        if not isinstance(u, dict):
            continue
        login = u.get("login")
        if not login or not isinstance(login, str):
            continue
        try:
            contributions = int(u.get("contributions") or 0)
        except (TypeError, ValueError):
            continue
        clean.append(
            {
                "login": login,
                "contributions": contributions,
                "avatarUrl": u.get("avatarUrl") or "",
            }
        )
    if not clean:
        return None
    clean.sort(key=lambda u: -u["contributions"])
    return clean


def main():
    if not REPO.is_dir():
        sys.exit(f"committers.top clone not found at {REPO}")

    slugs = list_slugs()
    print(f"Found {len(slugs)} location files on {REF}")

    reader = BlobReader()
    history = {}
    # per-login global aggregates (key = lowercased login)
    user_series = {}  # key -> {date: contributions}
    user_meta = {}  # key -> {login, avatarUrl, latest_date, locations:set}
    total_samples = 0
    parse_failures = 0
    min_date, max_date = None, None

    for i, slug in enumerate(slugs, 1):
        samples = []
        for sha, date in monthly_commits(slug):
            text = reader.read(f"{sha}:{LOC_PREFIX}/{slug}.yml")
            if text is None:
                parse_failures += 1
                continue
            users = parse_sample(text)
            if users is None:
                parse_failures += 1
                continue
            total_samples += 1
            min_date = date if min_date is None or date < min_date else min_date
            max_date = date if max_date is None or date > max_date else max_date
            samples.append(
                {
                    "date": date,
                    "top": [
                        {"login": u["login"], "contributions": u["contributions"]}
                        for u in users[:TOP_N]
                    ],
                }
            )
            for u in users:
                key = u["login"].lower()
                series = user_series.setdefault(key, {})
                if u["contributions"] > series.get(date, -1):
                    series[date] = u["contributions"]
                meta = user_meta.setdefault(
                    key,
                    {"login": u["login"], "avatarUrl": "", "latest": "", "locations": set()},
                )
                meta["locations"].add(slug)
                if date >= meta["latest"]:
                    meta["latest"] = date
                    meta["login"] = u["login"]
                    if u["avatarUrl"]:
                        meta["avatarUrl"] = u["avatarUrl"]
        history[slug] = samples
        if i % 25 == 0 or i == len(slugs):
            print(f"  [{i}/{len(slugs)}] processed (latest: {slug}, {len(samples)} samples)")

    reader.close()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    history_path = OUT_DIR / "history.json"
    history_path.write_text(json.dumps(history, separators=(",", ":")))
    print(f"Wrote {history_path} ({history_path.stat().st_size // 1024} KB)")

    # ---- movers ----
    global_max = datetime.date.fromisoformat(max_date)
    movers = []
    for key, series in user_series.items():
        dates = sorted(series)
        latest = dates[-1]
        latest_d = datetime.date.fromisoformat(latest)
        if (global_max - latest_d).days > NOW_WINDOW_DAYS:
            continue
        target = latest_d - datetime.timedelta(days=PREV_TARGET_DAYS)
        prev_date, prev_gap = None, None
        for d in dates[:-1]:
            gap = abs((datetime.date.fromisoformat(d) - target).days)
            if prev_gap is None or gap < prev_gap:
                prev_date, prev_gap = d, gap
        if prev_date is None or prev_gap > PREV_TOLERANCE_DAYS:
            continue
        prev = series[prev_date]
        if prev < MOVER_PREV_MIN:
            continue
        now = series[latest]
        delta = now - prev
        if delta <= 0:
            continue
        meta = user_meta[key]
        movers.append(
            {
                "login": meta["login"],
                "avatarUrl": meta["avatarUrl"],
                "contributions": now,
                "prevContributions": prev,
                "delta": delta,
                "pct": round(delta / prev * 100, 1),
                "locations": sorted(meta["locations"]),
            }
        )
    movers.sort(key=lambda m: -m["pct"])
    movers = movers[:MOVER_TOP]

    series_logins = {m["login"].lower() for m in movers[:SERIES_TOP]}
    current = []
    for key, series in user_series.items():
        dates = sorted(series)
        latest_d = datetime.date.fromisoformat(dates[-1])
        if (global_max - latest_d).days > NOW_WINDOW_DAYS:
            continue
        current.append((series[dates[-1]], key))
    current.sort(reverse=True)
    series_logins.update(key for _, key in current[:SERIES_TOP])

    series_out = {}
    for key in series_logins:
        login = user_meta[key]["login"]
        series_out[login] = [
            [d, user_series[key][d]] for d in sorted(user_series[key])
        ]

    movers_doc = {
        "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(
            timespec="seconds"
        ),
        "movers": movers,
        "series": series_out,
    }
    movers_path = OUT_DIR / "movers.json"
    movers_path.write_text(json.dumps(movers_doc, separators=(",", ":")))
    print(f"Wrote {movers_path} ({movers_path.stat().st_size // 1024} KB)")

    print(
        f"Summary: {len(slugs)} slugs, {total_samples} samples "
        f"({parse_failures} skipped), dates {min_date}..{max_date}, "
        f"{len(user_series)} unique logins, {len(movers)} movers, "
        f"{len(series_out)} series"
    )


if __name__ == "__main__":
    main()
