#!/usr/bin/env python3

# Copyright (c) 2026 Alex313031 and gz83.

"""Validate macOS application archives and DMG payloads."""

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import Sequence


MACHO_MAGICS = {
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
    b"\xfe\xed\xfa\xce",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe",
}
EXPECTED_ARCHITECTURES = {
    "arm64": {"arm64"},
    "x64": {"x86_64"},
    "universal": {"arm64", "x86_64"},
}


class PackageValidationError(RuntimeError):
    """An expected macOS package validation failure."""


def normalize_archive_path(name: str) -> PurePosixPath:
    if "\\" in name:
        raise PackageValidationError(
            f"archive member uses a backslash path separator: {name!r}"
        )
    path = PurePosixPath(name)
    if path.is_absolute():
        raise PackageValidationError(f"archive member has an absolute path: {name!r}")
    parts: list[str] = []
    for part in path.parts:
        if part in ("", "."):
            continue
        if part == "..":
            raise PackageValidationError(
                f"archive member escapes its extraction root: {name!r}"
            )
        parts.append(part)
    if not parts:
        raise PackageValidationError(f"archive member has an empty path: {name!r}")
    return PurePosixPath(*parts)


def resolve_link_path(base: PurePosixPath, target: str) -> PurePosixPath:
    if "\\" in target:
        raise PackageValidationError(
            f"archive link uses a backslash path separator: {target!r}"
        )
    target_path = PurePosixPath(target)
    if target_path.is_absolute():
        raise PackageValidationError(f"archive link has an absolute target: {target!r}")
    parts = list(base.parts)
    for part in target_path.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                raise PackageValidationError(
                    f"archive link escapes its extraction root: {target!r}"
                )
            parts.pop()
        else:
            parts.append(part)
    if not parts:
        raise PackageValidationError(
            f"archive link resolves to an empty path: {target!r}"
        )
    return PurePosixPath(*parts)


def validate_link(member: tarfile.TarInfo, member_path: PurePosixPath) -> None:
    if member.issym():
        resolved = resolve_link_path(member_path.parent, member.linkname)
    else:
        resolved = normalize_archive_path(member.linkname)
    if not resolved.parts or resolved.parts[0] != "Thorium.app":
        raise PackageValidationError(
            f"archive link escapes Thorium.app: {member.name!r} -> {member.linkname!r}"
        )


def validate_extracted_symlink(path: Path, app: Path) -> None:
    pending = list(path.relative_to(app).parts)
    resolved_parts: list[str] = []
    visited: set[Path] = set()
    while pending:
        part = pending.pop(0)
        if part in ("", "."):
            continue
        if part == "..":
            if not resolved_parts:
                raise PackageValidationError(
                    f"extracted symbolic link escapes Thorium.app: {path}"
                )
            resolved_parts.pop()
            continue

        candidate = app.joinpath(*resolved_parts, part)
        if not candidate.is_symlink():
            resolved_parts.append(part)
            continue
        if candidate in visited:
            raise PackageValidationError(
                f"extracted symbolic link cycle detected at: {candidate}"
            )
        visited.add(candidate)
        target = PurePosixPath(os.readlink(candidate))
        if target.is_absolute():
            raise PackageValidationError(
                f"extracted symbolic link has an absolute target: {candidate}"
            )
        pending[:0] = target.parts


def extract_archive(archive: Path, destination: Path) -> None:
    if not archive.is_file():
        raise PackageValidationError(f"archive does not exist: {archive}")
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise PackageValidationError(
            f"extraction directory must be empty: {destination}"
        )

    extraction_root = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.extract-",
            dir=destination.parent,
        )
    )
    published = False
    try:
        try:
            with tarfile.open(archive, mode="r:gz") as bundle:
                members = bundle.getmembers()
                if not members:
                    raise PackageValidationError("application archive is empty")
                seen_paths: set[PurePosixPath] = set()
                for member in members:
                    member_path = normalize_archive_path(member.name)
                    if member_path.parts[0] != "Thorium.app":
                        raise PackageValidationError(
                            f"archive member is outside Thorium.app: {member.name!r}"
                        )
                    if member_path in seen_paths:
                        raise PackageValidationError(
                            f"archive contains a duplicate member: {member.name!r}"
                        )
                    seen_paths.add(member_path)
                    if not (
                        member.isdir()
                        or member.isreg()
                        or member.issym()
                        or member.islnk()
                    ):
                        raise PackageValidationError(
                            "archive contains an unsupported member type: "
                            f"{member.name!r}"
                        )
                    if member.issym() or member.islnk():
                        validate_link(member, member_path)

                extraction_filter = getattr(tarfile, "data_filter", None)
                if extraction_filter is None:
                    bundle.extractall(extraction_root, members=members)
                else:
                    bundle.extractall(
                        extraction_root,
                        members=members,
                        filter=extraction_filter,
                    )
        except (OSError, tarfile.TarError) as error:
            raise PackageValidationError(
                f"could not extract {archive}: {error}"
            ) from error

        app = extraction_root / "Thorium.app"
        if app.is_symlink() or not app.is_dir():
            raise PackageValidationError(
                "archive did not produce a regular Thorium.app directory"
            )
        for root, directories, files in os.walk(app, followlinks=False):
            for name in (*directories, *files):
                path = Path(root, name)
                if path.is_symlink():
                    validate_extracted_symlink(path, app)

        try:
            os.replace(app, destination / "Thorium.app")
        except OSError as error:
            raise PackageValidationError(
                f"could not publish extracted Thorium.app: {error}"
            ) from error
        published = True
    finally:
        try:
            if published:
                extraction_root.rmdir()
            else:
                shutil.rmtree(extraction_root)
        except OSError as error:
            print(
                f"warning: could not remove temporary extraction directory "
                f"{extraction_root}: {error}",
                file=sys.stderr,
            )


def is_macho(path: Path) -> bool:
    try:
        with path.open("rb") as source:
            return source.read(4) in MACHO_MAGICS
    except OSError as error:
        raise PackageValidationError(f"could not inspect {path}: {error}") from error


def macho_files(app: Path) -> list[Path]:
    files: list[Path] = []
    for root, _, names in os.walk(app, followlinks=False):
        for name in names:
            path = Path(root, name)
            if not path.is_symlink() and path.is_file() and is_macho(path):
                files.append(path)
    return sorted(files)


def write_architecture_report(
    report: Path,
    target: str,
    expected: set[str],
    records: list[dict[str, object]],
    failures: list[str],
) -> None:
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(
            {
                "valid": not failures,
                "target": target,
                "expected_architectures": sorted(expected),
                "mach_o_file_count": len(records),
                "failures": failures,
                "files": records,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def validate_architectures(app: Path, target: str, report: Path) -> None:
    expected = EXPECTED_ARCHITECTURES[target]
    records: list[dict[str, object]] = []
    failures: list[str] = []
    if app.is_symlink() or not app.is_dir():
        failures.append(f"application bundle does not exist: {app}")
        write_architecture_report(report, target, expected, records, failures)
        raise PackageValidationError(failures[0])
    lipo = shutil.which("lipo")
    if lipo is None:
        failures.append("required command was not found in PATH: lipo")
        write_architecture_report(report, target, expected, records, failures)
        raise PackageValidationError(failures[0])
    try:
        binaries = macho_files(app)
    except PackageValidationError as error:
        failures.append(str(error))
        write_architecture_report(report, target, expected, records, failures)
        raise
    for binary in binaries:
        relative = binary.relative_to(app).as_posix()
        record: dict[str, object] = {"path": relative}
        try:
            completed = subprocess.run(
                [lipo, "-archs", str(binary)],
                check=True,
                capture_output=True,
                text=True,
            )
        except OSError as error:
            message = f"could not run lipo: {error}"
            record.update({"architectures": [], "error": message})
            records.append(record)
            failures.append(f"{relative}: {message}")
            continue
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or error.stdout or str(error)).strip()
            message = f"lipo failed: {detail}"
            record.update({"architectures": [], "error": message})
            records.append(record)
            failures.append(f"{relative}: {message}")
            continue
        architectures = set(completed.stdout.split())
        record["architectures"] = sorted(architectures)
        records.append(record)
        if architectures != expected:
            failures.append(
                f"{relative}: expected {sorted(expected)}, got {sorted(architectures)}"
            )
    if not records:
        failures.append(f"no Mach-O files were found under {app}")
    write_architecture_report(report, target, expected, records, failures)
    if failures:
        raise PackageValidationError(
            "Mach-O architecture validation failed:\n" + "\n".join(failures)
        )
    print(
        f"Validated {len(records)} Mach-O file(s) for {target}: "
        f"{', '.join(sorted(expected))}"
    )


def validate_dmg_root(root: Path) -> None:
    if not root.is_dir():
        raise PackageValidationError(f"mounted DMG root does not exist: {root}")
    entries = {entry.name for entry in root.iterdir()}
    expected = {"Applications", "Thorium.app"}
    if entries != expected:
        raise PackageValidationError(
            f"mounted DMG contains unexpected root entries: {sorted(entries)}"
        )
    app = root / "Thorium.app"
    if app.is_symlink() or not app.is_dir():
        raise PackageValidationError("mounted DMG has no regular Thorium.app bundle")
    applications = root / "Applications"
    if not applications.is_symlink() or os.readlink(applications) != "/Applications":
        raise PackageValidationError(
            "mounted DMG Applications entry is not a /Applications symbolic link"
        )


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract = subparsers.add_parser("extract", help="safely extract Thorium.app")
    extract.add_argument("--archive", type=Path, required=True)
    extract.add_argument("--destination", type=Path, required=True)

    architectures = subparsers.add_parser(
        "validate-architectures",
        help="validate every Mach-O file in Thorium.app",
    )
    architectures.add_argument("--app", type=Path, required=True)
    architectures.add_argument(
        "--target",
        choices=tuple(EXPECTED_ARCHITECTURES),
        required=True,
    )
    architectures.add_argument("--report", type=Path, required=True)

    layout = subparsers.add_parser(
        "validate-dmg-root",
        help="validate the mounted DMG root layout",
    )
    layout.add_argument("--root", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    if sys.version_info < (3, 11):
        print("error: Python 3.11 or newer is required", file=sys.stderr)
        return 2
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.command == "extract":
            extract_archive(args.archive.resolve(), args.destination.resolve())
        elif args.command == "validate-architectures":
            validate_architectures(
                args.app.resolve(),
                args.target,
                args.report.resolve(),
            )
        else:
            validate_dmg_root(args.root.resolve())
    except (PackageValidationError, OSError) as error:
        print(f"{Path(sys.argv[0]).name}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
