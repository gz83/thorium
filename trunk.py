#!/usr/bin/env python3

# Copyright (c) 2026 Alex313031, midzer, and gz83.

"""Reset, rebase, and synchronize a Chromium checkout."""

import argparse
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
from typing import Sequence

from chromium_sync import CheckoutError, prepare_dependencies, prepare_git_checkout


EXIT_FAILURE = 111
CHROMIUM_NESTED_CHECKOUTS = (
    (Path("v8"), "V8"),
    (Path("third_party/devtools-frontend/src"), "DevTools"),
    (Path("third_party/ffmpeg"), "FFmpeg"),
)


class TrunkError(RuntimeError):
    """An expected synchronization failure."""


def environment_path(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser()


def default_chromium_src() -> Path:
    configured = os.environ.get("CR_DIR")
    if configured:
        return environment_path(configured)
    if os.name == "nt":
        return Path("C:/src/chromium/src")
    return Path.home() / "chromium" / "src"


def default_thorium_root() -> Path:
    configured = os.environ.get("THOR_DIR")
    if configured:
        return environment_path(configured)
    return Path.home() / "thorium"


def default_depot_tools() -> Path:
    configured = os.environ.get("DEPOT_TOOLS_DIR")
    if configured:
        return environment_path(configured)
    gclient = shutil.which("gclient")
    if gclient:
        return Path(gclient).resolve().parent
    if os.name == "nt":
        return Path("C:/src/depot_tools")
    return Path.home() / "depot_tools"


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebase/sync the Chromium repository and run its hooks."
    )
    parser.add_argument(
        "--chromium-src",
        type=environment_path,
        default=default_chromium_src(),
        metavar="PATH",
        help="Chromium src directory (default: CR_DIR or the platform default)",
    )
    parser.add_argument(
        "--thorium-root",
        type=environment_path,
        default=default_thorium_root(),
        metavar="PATH",
        help="Thorium repository root (default: THOR_DIR or ~/thorium)",
    )
    parser.add_argument(
        "--depot-tools",
        type=environment_path,
        default=default_depot_tools(),
        metavar="PATH",
        help=(
            "depot_tools directory (default: DEPOT_TOOLS_DIR, the gclient "
            "location, or the platform default)"
        ),
    )
    return parser.parse_args(argv)


def find_command(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise TrunkError(
            f"required command '{name}' was not found in PATH; "
            "ensure depot_tools and Git are installed"
        )
    return executable


def depot_command(depot_tools: Path, name: str) -> str:
    suffix = ".bat" if os.name == "nt" else ""
    command = depot_tools / f"{name}{suffix}"
    if not command.is_file():
        raise TrunkError(f"depot_tools command does not exist: {command}")
    return str(command)


def run(command: Sequence[str], cwd: Path) -> None:
    printable = (
        subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)
    )
    print(f"\n[{cwd}] {printable}", flush=True)
    try:
        subprocess.run(command, cwd=cwd, check=True)
    except OSError as error:
        raise TrunkError(f"could not run {printable}: {error}") from error
    except subprocess.CalledProcessError as error:
        raise TrunkError(
            f"command failed with exit code {error.returncode}: {printable}"
        ) from error


def require_checkout(path: Path, description: str) -> None:
    if not path.is_dir():
        raise TrunkError(f"{description} directory does not exist: {path}")
    if not (path / ".git").exists():
        raise TrunkError(f"{description} is not a Git checkout: {path}")


def remove_tree(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    print(f"\nRemoving: {path}", flush=True)
    try:
        if path.is_symlink() or path.is_file():
            path.unlink()
        else:
            shutil.rmtree(path, onerror=remove_readonly)
    except OSError as error:
        raise TrunkError(f"failed to remove {path}: {error}") from error


def remove_readonly(function, path: str, error_info) -> None:
    """Retry removal after making a Windows read-only path writable."""
    del error_info
    os.chmod(path, 0o700)
    function(path)


def clean_checkout(git: str, path: Path) -> None:
    prepare_git_checkout(git, path)
    run([git, "clean", "-ffd"], path)


def print_logo(thorium_root: Path) -> None:
    logo = thorium_root / "logos" / "chromium_logo_ascii_art.txt"
    try:
        print(f"\n{logo.read_text(encoding='utf-8')}")
    except (OSError, UnicodeError) as error:
        print(f"warning: could not display {logo}: {error}", file=sys.stderr)


def synchronize(
    chromium_src: Path,
    thorium_root: Path,
    depot_tools: Path,
) -> None:
    chromium_src = chromium_src.expanduser().resolve()
    thorium_root = thorium_root.expanduser().resolve()
    depot_tools = depot_tools.expanduser().resolve()
    nested_checkouts = tuple(
        (chromium_src / relative_path, description)
        for relative_path, description in CHROMIUM_NESTED_CHECKOUTS
    )

    require_checkout(chromium_src, "Chromium")
    for path, description in nested_checkouts:
        require_checkout(path, description)

    git = find_command("git")
    gclient = depot_command(depot_tools, "gclient")
    rebase_update = depot_tools / "git-rebase-update"
    if not rebase_update.is_file():
        raise TrunkError(
            f"depot_tools command does not exist: {rebase_update}"
        )
    os.environ["DEPOT_TOOLS_DIR"] = str(depot_tools)
    os.environ["PATH"] = str(depot_tools) + os.pathsep + os.environ.get("PATH", "")

    print("\nScript to Rebase/Sync the Chromium repo.\n")
    print(f"Rebasing/Syncing and running hooks in {chromium_src}")

    prepare_git_checkout(git, chromium_src)

    for path, _ in nested_checkouts:
        clean_checkout(git, path)

    remove_tree(chromium_src / "third_party" / "pak")

    run([git, "checkout", "-f", "origin/main"], chromium_src)
    run([git, "clean", "-ffd"], chromium_src)
    run([git, "rebase-update"], chromium_src)
    run([git, "fetch", "--tags"], chromium_src)

    prepare_dependencies(gclient, git, chromium_src, run)

    print("\ngclient sync", flush=True)
    run(
        [
            gclient,
            "sync",
            "--with_branch_heads",
            "--with_tags",
            "--force",
            "--reset",
            "--nohooks",
            "--delete_unversioned_trees",
        ],
        chromium_src,
    )
    run([git, "clean", "-ffd"], chromium_src)

    print("\ngclient runhooks", flush=True)
    run([gclient, "runhooks"], chromium_src)

    print("\nDone! You can now run 'version.py'.")
    print_logo(thorium_root)


def main(argv: Sequence[str] | None = None) -> int:
    if sys.version_info < (3, 11):
        print("error: Python 3.11 or newer is required", file=sys.stderr)
        return 2
    if platform.system() not in ("Linux", "Darwin", "Windows"):
        print("error: only Linux, macOS, and Windows are supported", file=sys.stderr)
        return 2

    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        synchronize(args.chromium_src, args.thorium_root, args.depot_tools)
    except (TrunkError, CheckoutError) as error:
        print(f"{Path(sys.argv[0]).name}: {error}", file=sys.stderr)
        return EXIT_FAILURE
    except OSError as error:
        print(
            f"{Path(sys.argv[0]).name}: filesystem operation failed: {error}",
            file=sys.stderr,
        )
        return EXIT_FAILURE
    except KeyboardInterrupt:
        print(f"\n{Path(sys.argv[0]).name}: interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
