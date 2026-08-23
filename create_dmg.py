#!/usr/bin/env python3

# Copyright (c) 2026 Alex313031, midzer, and gz83.

"""Create a Thorium or Chromium macOS disk image."""

import argparse
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
from typing import Sequence


EXIT_FAILURE = 111
PRODUCTS = {
    "thorium": ("Thorium.app", "Thorium_MacOS.dmg", "Thorium"),
    "chromium": ("Chromium.app", "Chromium_MacOS.dmg", "Chromium"),
}


class DmgError(RuntimeError):
    """An expected disk-image creation failure."""


def environment_path(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser()


def default_chromium_src() -> Path:
    configured = os.environ.get("CR_DIR")
    if configured:
        return environment_path(configured)
    return Path.home() / "chromium" / "src"


def default_thorium_root() -> Path:
    configured = os.environ.get("THOR_DIR")
    if configured:
        return environment_path(configured)
    return Path.home() / "thorium"


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a Thorium or Chromium macOS DMG installation package."
    )
    parser.add_argument(
        "--chromium-src",
        type=environment_path,
        default=default_chromium_src(),
        metavar="PATH",
        help="Chromium src directory (default: CR_DIR or ~/chromium/src)",
    )
    parser.add_argument(
        "--thorium-root",
        type=environment_path,
        default=default_thorium_root(),
        metavar="PATH",
        help="Thorium repository root (default: THOR_DIR or ~/thorium)",
    )
    parser.add_argument(
        "--product",
        choices=tuple(PRODUCTS),
        default="thorium",
        help="application bundle to package (default: thorium)",
    )
    return parser.parse_args(argv)


def find_command(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise DmgError(f"required command was not found in PATH: {name}")
    return executable


def require_file(path: Path, description: str) -> None:
    if not path.is_file():
        raise DmgError(f"{description} does not exist: {path}")


def require_executable_file(path: Path, description: str) -> None:
    require_file(path, description)
    if not os.access(path, os.X_OK):
        raise DmgError(f"{description} is not executable: {path}")


def require_directory(path: Path, description: str) -> None:
    if not path.is_dir():
        raise DmgError(f"{description} does not exist: {path}")


def run(command: Sequence[str], cwd: Path) -> None:
    printable = shlex.join(command)
    print(f"\n[{cwd}] {printable}", flush=True)
    try:
        subprocess.run(command, cwd=cwd, check=True)
    except OSError as error:
        raise DmgError(f"could not run {printable}: {error}") from error
    except subprocess.CalledProcessError as error:
        raise DmgError(
            f"command failed with exit code {error.returncode}: {printable}"
        ) from error


def create_dmg(chromium_src: Path, thorium_root: Path, product: str) -> None:
    chromium_src = chromium_src.expanduser().resolve()
    app_name, output_name, volume_name = PRODUCTS[product]
    app = chromium_src / "out" / "thorium" / app_name
    output = chromium_src / "out" / "thorium" / output_name
    pkg_dmg = chromium_src / "chrome" / "installer" / "mac" / "pkg-dmg"

    require_directory(chromium_src, "Chromium source directory")
    require_directory(app, f"{volume_name} application bundle")
    require_executable_file(pkg_dmg, "Chromium pkg-dmg tool")
    logo = None
    if product == "thorium":
        thorium_root = thorium_root.expanduser().resolve()
        logo = thorium_root / "logos" / "apple_ascii_art.txt"
        require_file(logo, "Thorium Apple ASCII art")
    if output.is_symlink():
        raise DmgError(f"refusing to overwrite symbolic-link DMG output: {output}")
    if os.path.lexists(output) and not output.is_file():
        raise DmgError(f"DMG output path is not a regular file: {output}")
    xattr = find_command("xattr")
    codesign = find_command("codesign")
    hdiutil = find_command("hdiutil")

    print(f"\nBuilding {volume_name} macOS disk image.")
    run([xattr, "-csr", str(app)], chromium_src)
    run([codesign, "--force", "--deep", "--sign", "-", str(app)], chromium_src)
    with tempfile.TemporaryDirectory(
        prefix=f".{output.stem}.", dir=output.parent
    ) as working_dir_name:
        working_dir = Path(working_dir_name)
        packaged_image = working_dir / "packaged.dmg"
        writable_image = working_dir / "writable.dmg"
        mount_point = working_dir / "mount"
        mount_point.mkdir()

        # makehybrid can add FinderInfo that breaks strict code-signing checks.
        # Convert its output to UDRW, sanitize the app, then recompress it.
        run(
            [
                str(pkg_dmg),
                "--sourcefile",
                "--source",
                str(app),
                "--target",
                str(packaged_image),
                "--volname",
                volume_name,
                "--symlink",
                "/Applications:/Applications",
                "--format",
                "UDBZ",
                "--verbosity",
                "2",
            ],
            chromium_src,
        )
        require_file(packaged_image, "pkg-dmg disk image")
        run(
            [
                hdiutil,
                "convert",
                "-format",
                "UDRW",
                "-ov",
                str(packaged_image),
                "-o",
                str(writable_image),
            ],
            chromium_src,
        )
        require_file(writable_image, "writable disk image")

        attached = False
        try:
            run(
                [
                    hdiutil,
                    "attach",
                    "-nobrowse",
                    "-owners",
                    "on",
                    "-mountpoint",
                    str(mount_point),
                    str(writable_image),
                ],
                chromium_src,
            )
            attached = True
            mounted_app = mount_point / app_name
            require_directory(mounted_app, f"mounted {volume_name} application")
            run([xattr, "-csr", str(mounted_app)], chromium_src)
            # Extended attributes are outside the signed file contents.
            run(
                [
                    codesign,
                    "--verify",
                    "--deep",
                    "--strict",
                    "--verbose=2",
                    str(mounted_app),
                ],
                chromium_src,
            )
        except BaseException:
            if attached:
                subprocess.run(
                    [hdiutil, "detach", "-force", str(mount_point)],
                    cwd=chromium_src,
                    check=False,
                )
            raise
        else:
            run([hdiutil, "detach", str(mount_point)], chromium_src)

        run(
            [
                hdiutil,
                "convert",
                "-format",
                "UDBZ",
                "-imagekey",
                "bzip2-level=9",
                "-ov",
                str(writable_image),
                "-o",
                str(output),
            ],
            chromium_src,
        )
    if output.is_symlink() or not output.is_file():
        raise DmgError(f"DMG packaging did not create a regular file: {output}")

    if logo is not None:
        try:
            print(f"\n{logo.read_text(encoding='utf-8')}")
        except (OSError, UnicodeError) as error:
            raise DmgError(f"failed to read {logo}: {error}") from error
    print(f"DMG build completed: {output}")


def main(argv: Sequence[str] | None = None) -> int:
    if sys.version_info < (3, 11):
        print("error: Python 3.11 or newer is required", file=sys.stderr)
        return 2
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if platform.system() != "Darwin":
        print("error: create_dmg.py supports macOS only", file=sys.stderr)
        return 2

    try:
        create_dmg(args.chromium_src, args.thorium_root, args.product)
    except (DmgError, OSError) as error:
        print(f"{Path(sys.argv[0]).name}: {error}", file=sys.stderr)
        return EXIT_FAILURE
    except KeyboardInterrupt:
        print(f"\n{Path(sys.argv[0]).name}: interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
