#!/usr/bin/env python3

# Copyright (c) 2026 Alex313031 and gz83.

"""Build or extract Thorium AppImages on Linux."""

import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from typing import Sequence


MINIMUM_PYTHON = (3, 11)
PACKAGE_GLOB = "thorium-browser_*.deb"
APPIMAGE_GLOB = "Thorium*.AppImage"


class AppImageError(RuntimeError):
    """An expected AppImage preparation or extraction failure."""


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser(
        "build", help="build an AppImage from a Thorium DEB"
    )
    build.add_argument(
        "package",
        nargs="?",
        type=Path,
        help="Thorium DEB (default: detect one in the APPIMAGE directory)",
    )

    extract = subparsers.add_parser("extract", help="extract a Thorium AppImage")
    extract.add_argument(
        "appimage",
        nargs="?",
        type=Path,
        help="AppImage (default: detect one in the out directory)",
    )
    extract.add_argument(
        "--force",
        action="store_true",
        help="replace an existing out/Thorium_squashfs-root directory",
    )
    return parser.parse_args(argv)


def require_linux() -> None:
    if platform.system() != "Linux":
        raise AppImageError("AppImage operations are supported only on Linux")


def require_tool(name: str) -> Path:
    executable = shutil.which(name)
    if not executable:
        raise AppImageError(f"required tool not found in PATH: {name}")
    return Path(executable).resolve()


def select_single(paths: list[Path], description: str) -> Path:
    unique = sorted({path.resolve() for path in paths})
    if not unique:
        raise AppImageError(f"no {description} found")
    if len(unique) > 1:
        names = ", ".join(path.name for path in unique)
        raise AppImageError(
            f"multiple {description}s found ({names}); specify one explicitly"
        )
    return unique[0]


def find_package(base_dir: Path, requested: Path | None) -> Path:
    if requested is not None:
        package = requested.expanduser().resolve()
        if not package.is_file():
            raise AppImageError(f"DEB does not exist: {package}")
        if package.suffix.lower() != ".deb":
            raise AppImageError(f"not a DEB package: {package}")
        return package

    matches = [path for path in base_dir.glob(PACKAGE_GLOB) if path.is_file()]
    return select_single(matches, f"DEB matching {PACKAGE_GLOB}")


def package_output_name(package: Path) -> str:
    stem = package.stem.removeprefix("thorium-browser_")
    return f"Thorium_Browser_{stem}.AppImage"


def copy_payload(extracted: Path, payload: Path, resources: Path) -> None:
    product_dir = extracted / "opt/chromium.org/thorium"
    if not product_dir.is_dir():
        relative_product_dir = product_dir.relative_to(extracted)
        raise AppImageError(f"DEB does not contain {relative_product_dir}")

    shutil.copytree(product_dir, payload, dirs_exist_ok=True, symlinks=True)
    for obsolete in (payload / "cron", payload / "thorium-browser"):
        if obsolete.is_dir() and not obsolete.is_symlink():
            shutil.rmtree(obsolete)
        elif obsolete.exists() or obsolete.is_symlink():
            obsolete.unlink()

    for name in ("product_logo_512.png", "product_logo_22.png", "thorium-shell"):
        source = resources / name
        if not source.is_file():
            raise AppImageError(f"required AppImage resource is missing: {source}")
        destination = payload / name
        shutil.copy2(source, destination)
        if name == "thorium-shell":
            destination.chmod(destination.stat().st_mode | 0o111)


def read_package_version(dpkg_deb: Path, package: Path) -> str:
    result = subprocess.run(
        [str(dpkg_deb), "--field", str(package), "Version"],
        check=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    version = result.stdout.strip()
    if not version:
        raise AppImageError(f"DEB has no Version field: {package}")
    return version


def appimage_snapshot(output_dir: Path) -> dict[Path, tuple[int, int]]:
    snapshot = {}
    for path in output_dir.glob(APPIMAGE_GLOB):
        if path.is_file():
            metadata = path.stat()
            snapshot[path.resolve()] = (metadata.st_mtime_ns, metadata.st_size)
    return snapshot


def build_appimage(base_dir: Path, requested_package: Path | None) -> Path:
    dpkg_deb = require_tool("dpkg-deb")
    package = find_package(base_dir, requested_package)
    recipe = base_dir / "Thorium.yml"
    builder = base_dir / "pkg2appimage"
    resources = base_dir / "files"
    output_dir = base_dir / "out"
    if not recipe.is_file():
        raise AppImageError(f"AppImage recipe is missing: {recipe}")
    if not builder.is_file():
        raise AppImageError(f"pkg2appimage is missing: {builder}")
    if not os.access(builder, os.X_OK):
        raise AppImageError(f"pkg2appimage is not executable: {builder}")

    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / package_output_name(package)
    before = appimage_snapshot(output_dir)
    version = read_package_version(dpkg_deb, package)
    build_tree = base_dir / "Thorium"
    try:
        build_tree.mkdir()
    except FileExistsError as error:
        raise AppImageError(
            f"another build or stale pkg2appimage directory exists: {build_tree}"
        ) from error

    print(f"Package: {package}")
    print(f"Output: {destination}")
    build_failed = False
    try:
        with tempfile.TemporaryDirectory(prefix="thorium-appimage-") as temporary:
            temporary_dir = Path(temporary)
            extracted = temporary_dir / "deb"
            payload = temporary_dir / "payload"
            extracted.mkdir()
            payload.mkdir()
            subprocess.run(
                [str(dpkg_deb), "--extract", str(package), str(extracted)],
                check=True,
            )
            copy_payload(extracted, payload, resources)

            environment = os.environ.copy()
            environment["THORIUM_APPIMAGE_PAYLOAD"] = str(payload)
            environment["THORIUM_APPIMAGE_VERSION"] = version
            subprocess.run(
                [str(builder), str(recipe)],
                cwd=base_dir,
                env=environment,
                check=True,
            )
    except BaseException:
        build_failed = True
        raise
    finally:
        if build_tree.is_dir():
            try:
                shutil.rmtree(build_tree)
            except OSError as error:
                if not build_failed:
                    raise
                print(
                    f"warning: failed to remove build directory {build_tree}: "
                    f"{error}",
                    file=sys.stderr,
                )

    after = appimage_snapshot(output_dir)
    generated = [path for path, state in after.items() if before.get(path) != state]
    source = select_single(generated, "newly generated AppImage")
    if source != destination:
        source.replace(destination)
    print(f"Created: {destination}")
    return destination


def find_appimage(base_dir: Path, requested: Path | None) -> Path:
    if requested is not None:
        appimage = requested.expanduser().resolve()
        if not appimage.is_file():
            raise AppImageError(f"AppImage does not exist: {appimage}")
        return appimage
    return select_single(
        [
            path
            for path in (base_dir / "out").glob(APPIMAGE_GLOB)
            if path.is_file()
        ],
        "Thorium AppImage in out",
    )


def extract_appimage(base_dir: Path, requested: Path | None, *, force: bool) -> Path:
    appimage = find_appimage(base_dir, requested)
    if not os.access(appimage, os.X_OK):
        raise AppImageError(f"AppImage is not executable; run chmod +x {appimage}")

    output_dir = base_dir / "out"
    destination = output_dir / "Thorium_squashfs-root"
    destination_exists = os.path.lexists(destination)
    if destination_exists and not force:
        raise AppImageError(f"extraction destination already exists: {destination}")
    if destination_exists and os.path.ismount(destination):
        raise AppImageError(f"refusing to replace mounted destination: {destination}")
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="thorium-appimage-extract-", dir=output_dir
    ) as temporary:
        temporary_dir = Path(temporary)
        subprocess.run(
            [str(appimage), "--appimage-extract"],
            cwd=temporary_dir,
            check=True,
        )
        extracted = temporary_dir / "squashfs-root"
        if extracted.is_symlink() or not extracted.is_dir():
            raise AppImageError("AppImage did not create squashfs-root")
        backup = output_dir / (
            f".{destination.name}.previous-{temporary_dir.name}"
        )
        if os.path.lexists(backup):
            raise AppImageError(f"extraction backup already exists: {backup}")
        try:
            if destination_exists:
                destination.rename(backup)
            extracted.rename(destination)
        except BaseException as error:
            if (
                destination_exists
                and os.path.lexists(backup)
                and not os.path.lexists(destination)
            ):
                try:
                    backup.rename(destination)
                except OSError as restore_error:
                    raise AppImageError(
                        f"failed to install extracted AppImage and restore "
                        f"{destination}: {restore_error}"
                    ) from error
            raise
        if destination_exists:
            try:
                if backup.is_dir() and not backup.is_symlink():
                    shutil.rmtree(backup)
                else:
                    backup.unlink()
            except OSError as error:
                print(
                    f"warning: extracted AppImage was installed, but the old "
                    f"destination could not be removed: {backup}: {error}",
                    file=sys.stderr,
                )

    print(f"Extracted: {destination}")
    return destination


def main(argv: Sequence[str] | None = None) -> int:
    if sys.version_info < MINIMUM_PYTHON:
        required = ".".join(str(part) for part in MINIMUM_PYTHON)
        print(f"error: Python {required} or newer is required", file=sys.stderr)
        return 2

    args = parse_arguments(sys.argv[1:] if argv is None else argv)
    try:
        require_linux()
        base_dir = Path(__file__).resolve().parent
        if args.command == "build":
            build_appimage(base_dir, args.package)
        else:
            extract_appimage(base_dir, args.appimage, force=args.force)
    except (
        AppImageError,
        OSError,
        shutil.Error,
        subprocess.CalledProcessError,
    ) as error:
        print(f"{Path(sys.argv[0]).name}: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(f"\n{Path(sys.argv[0]).name}: interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
