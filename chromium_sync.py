#!/usr/bin/env python3

# Copyright (c) 2026 Alex313031 and gz83.

"""Prepare Git checkouts for Thorium's destructive Chromium sync workflow."""

import argparse
from pathlib import Path
import subprocess
import sys
from typing import Callable, Sequence


class CheckoutError(RuntimeError):
    """A checkout could not be prepared for synchronization."""


def prepare_git_checkout(git: str, checkout: Path) -> None:
    """Leave a checkout detached, with no pending rebase or tracked edits."""
    try:
        git_dir = Path(
            subprocess.check_output(
                [git, "rev-parse", "--absolute-git-dir"],
                cwd=checkout,
                text=True,
            ).strip()
        )
        if (git_dir / "rebase-merge").is_dir() or (
            git_dir / "rebase-apply"
        ).is_dir():
            # --quit clears the operation without restoring an obsolete HEAD
            # or applying an autostash over the revision we are switching to.
            operation = (
                "am" if (git_dir / "rebase-apply" / "applying").exists()
                else "rebase"
            )
            print(f"\n[{checkout}] Clearing unfinished git {operation}", flush=True)
            subprocess.run([git, operation, "--quit"], cwd=checkout, check=True)

        # --reset in gclient only resets tracked files. A named branch can
        # still trigger a rebase onto a DEPS pin, including release commits.
        # Detaching keeps the local branch ref intact and avoids that rebase.
        subprocess.run(
            [git, "checkout", "--detach", "--force", "--quiet", "HEAD"],
            cwd=checkout,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise CheckoutError(f"could not prepare {checkout}: {error}") from error


def prepare_dependencies(
    gclient: str,
    git: str,
    chromium_src: Path,
    run: Callable[[Sequence[str], Path], None],
) -> None:
    """Prepare existing Git dependencies of the selected Chromium revision."""
    print("\nPreparing dependency checkouts for gclient sync", flush=True)
    run(
        [
            gclient,
            "recurse",
            "--scm=git",
            sys.executable,
            str(Path(__file__).resolve()),
            git,
            str(chromium_src),
        ],
        chromium_src,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("git", help="Git executable")
    parser.add_argument("chromium_src", type=Path, help="Chromium src directory")
    args = parser.parse_args()
    checkout = Path.cwd().resolve()
    chromium_src = args.chromium_src.resolve()
    # gclient recurse also visits the solution itself and any other solutions.
    # Missing Git checkouts are left for sync to create; never operate on their
    # parent repository by letting Git search upwards for a .git directory.
    if (
        checkout == chromium_src
        or not checkout.is_relative_to(chromium_src)
        or not (checkout / ".git").exists()
    ):
        return 0
    try:
        prepare_git_checkout(args.git, checkout)
    except CheckoutError as error:
        print(f"{Path(__file__).name}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
