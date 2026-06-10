#!/usr/bin/env python3
"""Refresh stale data/locations/*.yml files using the vendored collector.

Mirrors upstream committers.top daily_update.yml logic:
  - collector --list-presets -> CSV (preset,title,definition_checksum)
  - filename = preset.replace(" ", "_")
  - stale if: file missing | checksum mismatch | total_user_count == 0
    | "generated" timestamp older than STALE_DAYS
  - refresh up to MAX_IN_RUN presets (shuffled), writing
    "page: {filename}.html\\n" + collector yaml stdout

Env:
  COLLECTOR_BIN  collector binary (default: most-active-github-users-counter)
  GITHUB_TOKEN   required unless --dry-run
  MAX_IN_RUN     max presets refreshed per run (default 3)
  STALE_DAYS     age threshold in days (default 5)
"""

import csv
import datetime
import glob
import os
import random
import re
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO_ROOT, "data", "locations")
COLLECTOR_BIN = os.environ.get("COLLECTOR_BIN", "most-active-github-users-counter")
MAX_IN_RUN = int(os.environ.get("MAX_IN_RUN", "3"))
STALE_DAYS = int(os.environ.get("STALE_DAYS", "5"))

FIELD_RE = {
    "definition_checksum": re.compile(r"^definition_checksum: (\w+)$", re.M),
    "total_user_count": re.compile(r"^total_user_count: (\d+)$", re.M),
    "generated": re.compile(r"^generated: (\S+)$", re.M),
}


def list_presets():
    """Return {preset: definition_checksum} from the collector, or None if unavailable."""
    try:
        proc = subprocess.run(
            [COLLECTOR_BIN, "--list-presets"], capture_output=True, text=True
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    presets = {}
    for row in csv.DictReader(proc.stdout.splitlines()):
        if row.get("preset"):
            presets[row["preset"]] = row.get("definition_checksum", "")
    return presets or None


def presets_from_files():
    """Fallback: derive preset names from existing yml filenames (no checksums)."""
    presets = {}
    for path in glob.glob(os.path.join(DATA_DIR, "*.yml")):
        filename = os.path.splitext(os.path.basename(path))[0]
        presets[filename.replace("_", " ")] = None
    return presets


def parse_generated(value):
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def stale_reason(path, expected_checksum):
    if not os.path.exists(path):
        return "missing"
    content = open(path).read()

    if expected_checksum is not None:
        m = FIELD_RE["definition_checksum"].search(content)
        if not m or m.group(1) != expected_checksum:
            return "definition_checksum mismatch"

    m = FIELD_RE["total_user_count"].search(content)
    if not m or m.group(1) == "0":
        return "total_user_count == 0"

    m = FIELD_RE["generated"].search(content)
    generated = parse_generated(m.group(1)) if m else None
    if generated is None:
        return "missing/invalid generated timestamp"
    age = datetime.datetime.now(datetime.timezone.utc) - generated
    if age.days >= STALE_DAYS:
        return "generated %d days ago" % age.days

    return None


def refresh(preset, filename):
    proc = subprocess.run(
        [COLLECTOR_BIN, "--token", os.environ.get("GITHUB_TOKEN", ""),
         "--preset", preset, "--output", "yaml"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print("FAILED %s (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
              % (preset, proc.returncode, proc.stdout, proc.stderr), file=sys.stderr)
        return False
    with open(os.path.join(DATA_DIR, "%s.yml" % filename), "w") as f:
        f.write("page: %s.html\n%s" % (filename, proc.stdout))
    print("Refreshed: %s" % filename)
    return True


def main():
    dry_run = "--dry-run" in sys.argv[1:]

    presets = list_presets()
    checksums_verified = presets is not None
    if presets is None:
        if not dry_run:
            print("error: collector binary %r not available (set COLLECTOR_BIN)"
                  % COLLECTOR_BIN, file=sys.stderr)
            sys.exit(1)
        print("note: collector binary %r unavailable; reading presets from "
              "existing yml files (checksum verification needs the binary)"
              % COLLECTOR_BIN)
        presets = presets_from_files()

    stale = []
    for preset in sorted(presets):
        filename = preset.replace(" ", "_")
        reason = stale_reason(os.path.join(DATA_DIR, "%s.yml" % filename),
                              presets[preset])
        if reason:
            stale.append((preset, filename, reason))

    if not stale:
        print("Nothing stale.")
        return

    random.shuffle(stale)
    selected = stale[:MAX_IN_RUN]

    print("Stale: %d file(s); refreshing up to %d this run%s"
          % (len(stale), MAX_IN_RUN, " (dry run)" if dry_run else ""))
    for preset, filename, reason in selected:
        print("  would refresh %s.yml (%s)" % (filename, reason) if dry_run
              else "  refreshing %s.yml (%s)" % (filename, reason))
    if dry_run:
        skipped = len(stale) - len(selected)
        if skipped:
            print("  (+%d more stale, deferred to later runs)" % skipped)
        if not checksums_verified:
            print("  warning: definition_checksum not verified (collector unavailable)")
        return

    refreshed, failed = [], []
    for preset, filename, _reason in selected:
        (refreshed if refresh(preset, filename) else failed).append(filename)

    if refreshed:
        print("Succeeded: %s" % " ".join(refreshed))
    if failed:
        print("Failed: %s" % " ".join(failed), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
