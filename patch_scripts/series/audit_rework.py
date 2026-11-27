#!/usr/bin/env python3
# Copyright (c) 2026 Alex313031 and gz83.
"""Verify the pinned donor inventory and compare its patches to Thorium."""

import argparse
from collections import Counter
import csv
import hashlib
from pathlib import Path, PurePosixPath
import re
import sys

from apply_series import parse_series, selected
from rework import load_donors


def hunks(data, root="."):
    """Return the target and signed nonblank edits of each unified diff hunk."""
    for file in re.split(rb"(?m)(?=^diff --git )", data.replace(b"\r\n", b"\n")):
        name = (re.search(rb"(?m)^\+\+\+ b/([^\n\t]+)", file)
                or re.search(rb"(?m)^--- a/([^\n\t]+)", file)
                or re.match(rb"diff --git a/.+? b/([^\n]+)", file))
        if not name:
            continue
        path = (PurePosixPath(root) / name[1].decode()).as_posix()
        for hunk in re.split(rb"(?m)^@@ [^\n]*?@@[^\n]*\n", file)[1:]:
            edits = tuple(line[:1] + b" ".join(line[1:].split())
                          for line in hunk.splitlines()
                          if line.startswith((b"+", b"-")) and line[1:].strip())
            if edits:
                yield path, edits
        if b"\nGIT binary patch\n" in file:
            yield path, (b"binary", file.split(b"\nGIT binary patch\n", 1)[1])


def audit(upstream, thorium):
    directory = thorium / "other/rework-windows"
    with (directory / "series.tsv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    order = (upstream / "commit_hashes.txt").read_text(encoding="ascii").splitlines()[::-1]
    if len(order) != len(set(order)) or [row["donor"] for row in rows] != order:
        raise ValueError("manifest does not match the complete upstream application order")
    local = {p: data for _, p, data in load_donors(directory)}
    if set(directory.glob("patches/*.diff")) != local.keys():
        raise ValueError("manifest and delivered patch files differ")
    sources, delivered = {}, {}
    for row in rows:
        number = int(row["order"])
        raw = (upstream / (row["donor"] + ".diff")).read_bytes()
        if hashlib.sha256(raw).hexdigest() != row["upstream_sha256"]:
            raise ValueError(f"#{number}: upstream input SHA-256 mismatch")
        sources[number] = set(hunks(raw))
        if row["patch"] != "-":
            data = local[directory / row["patch"]]
            if (data == raw) != (row["status"] == "upstream"):
                raise ValueError(f"#{number}: upstream identity status is incorrect")
            delivered[number] = set(hunks(data))
        elif row["status"] not in {"excluded", "covered"} or not row["adaptation"]:
            raise ValueError(f"#{number}: missing reason for omission")
    print(dict(Counter(row["status"] for row in rows)))
    entries = parse_series(thorium / "patch_scripts/series/series")
    for profile in (set(), {"sse2"}):
        regular = set()
        for entry in entries:
            if selected(entry, profile):
                regular.update(hunks((thorium / entry.patch_path).read_bytes(), entry.apply_root))
        original = [(i, h[0]) for i, edits in sources.items() for h in edits & regular]
        matches = [(i, h[0]) for i, edits in delivered.items() for h in edits & regular]
        covered = [i for i, edits in sources.items() if edits and edits <= regular]
        print(f"{'SSE2' if profile else 'Standard'}: fully covered donors {covered}, "
              f"original matching hunks {sorted(original)}, delivered matching hunks {sorted(matches)}")
        if matches:
            raise ValueError("delivered series contains an identical Thorium hunk")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upstream", type=Path, help="REWORK chromium-159.0.8146.0 directory")
    try:
        audit(parser.parse_args().upstream.resolve(), Path(__file__).resolve().parents[2])
    except (OSError, ValueError) as error:
        sys.exit(str(error))
