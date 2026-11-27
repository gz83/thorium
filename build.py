#!/usr/bin/env python3

# Copyright (c) 2026 Alex313031, midzer, and gz83.

"""Build Thorium targets for an existing generated Chromium output directory."""

import argparse
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
from typing import Sequence


MINIMUM_PYTHON = (3, 11)
NINJA_STATUS = "[%r processes, %f/%t @ %o/s | %e sec. ] "
SUPPORTED_DEFAULT_TARGET_OSES = {"android", "chromeos", "linux", "mac", "win"}


class BuildError(RuntimeError):
    """An expected build configuration or command failure."""


class BuildFailure(BuildError):
    """A failed autoninja phase whose exit status must be preserved."""

    def __init__(self, phase: int, phase_count: int, returncode: int) -> None:
        super().__init__(
            f"build phase {phase}/{phase_count} failed with exit code {returncode}"
        )
        self.returncode = returncode


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
    return Path(__file__).resolve().parent


def positive_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if number < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def normalize_exit_status(returncode: int) -> int:
    if returncode < 0:
        return 128 + abs(returncode)
    return returncode or 1


def build_target(value: str) -> str:
    if (
        not value
        or value.startswith("-")
        or any(character.isspace() for character in value)
    ):
        raise argparse.ArgumentTypeError(
            "must be a nonempty Ninja target without whitespace or a leading '-'"
        )
    return value


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build Thorium using the target OS and CPU recorded by GN in an "
            "existing output directory."
        ),
    )
    parser.add_argument(
        "--chromium-src",
        type=environment_path,
        default=default_chromium_src(),
        help="Chromium src directory (default: CR_DIR or the platform default)",
    )
    parser.add_argument(
        "--thorium-root",
        type=environment_path,
        default=default_thorium_root(),
        help="Thorium checkout (default: THOR_DIR or this script's directory)",
    )
    parser.add_argument(
        "-C",
        "--out-dir",
        type=environment_path,
        default=Path("out/thorium"),
        help="GN output directory, relative to Chromium src (default: out/thorium)",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=positive_integer,
        help="maximum parallel jobs (default: let autoninja choose)",
    )
    target_mode = parser.add_mutually_exclusive_group()
    target_mode.add_argument(
        "--no-installer",
        action="store_true",
        help="build thorium_all without the platform installer/package target",
    )
    target_mode.add_argument(
        "--target",
        action="append",
        type=build_target,
        metavar="TARGET",
        help="build only this Ninja target; may be specified more than once",
    )
    parser.add_argument(
        "--expect-os",
        choices=sorted(SUPPORTED_DEFAULT_TARGET_OSES),
        help="fail unless GN generated this target OS",
    )
    parser.add_argument(
        "--expect-cpu",
        choices=("arm", "arm64", "x86", "x64"),
        help="fail unless GN generated this target CPU",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and print the autoninja command without building",
    )
    parser.add_argument(
        "--single-pass",
        action="store_true",
        help="build all selected targets in one autoninja invocation",
    )
    return parser.parse_args(argv)


def resolve_out_dir(chromium_src: Path, out_dir: Path) -> Path:
    if not out_dir.is_absolute():
        out_dir = chromium_src / out_dir
    return out_dir.resolve()


def find_tool(name: str) -> Path:
    executable = shutil.which(name)
    if not executable:
        raise BuildError(
            f"{name} was not found in PATH; add depot_tools to PATH first"
        )
    return Path(executable).resolve()


def platform_command(executable: Path, arguments: Sequence[str]) -> list[str]:
    if os.name == "nt" and executable.suffix.lower() in {".bat", ".cmd"}:
        python_wrapper = executable.with_suffix(".py")
        if not python_wrapper.is_file():
            raise BuildError(
                f"refusing to invoke batch wrapper without a Python companion: "
                f"{executable}"
            )
        return [sys.executable, str(python_wrapper), *arguments]
    return [str(executable), *arguments]


def display_command(command: Sequence[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(command)
    return shlex.join(command)


def read_gn_argument(
    gn: Path, chromium_src: Path, out_dir: Path, name: str
) -> str:
    command = platform_command(
        gn,
        ["args", str(out_dir), f"--list={name}", "--short"],
    )
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            cwd=chromium_src,
        )
    except subprocess.CalledProcessError as error:
        details = (error.stderr or error.stdout or "").strip()
        suffix = f": {details}" if details else ""
        raise BuildError(f"could not read GN argument {name}{suffix}") from error
    except OSError as error:
        raise BuildError(f"could not run GN: {error}") from error

    prefix = f"{name} = "
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            value = stripped[len(prefix) :].strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                return value[1:-1]
            return value
    raise BuildError(f"GN did not report a value for {name}")


def validate_checkout(chromium_src: Path, thorium_root: Path, out_dir: Path) -> None:
    if not chromium_src.is_dir() or not (chromium_src / "BUILD.gn").is_file():
        raise BuildError(f"not a Chromium src directory: {chromium_src}")
    if not thorium_root.is_dir() or not (thorium_root / "other").is_dir():
        raise BuildError(f"not a Thorium checkout: {thorium_root}")
    if not out_dir.is_dir() or not (out_dir / "args.gn").is_file():
        raise BuildError(
            f"GN output directory is not configured: {out_dir}; run "
            f"'gn args {out_dir}' first"
        )
    if not (out_dir / "build.ninja").is_file():
        raise BuildError(f"GN output directory has no build.ninja: {out_dir}")


def default_phases(target_os: str, *, no_installer: bool) -> list[list[str]]:
    if no_installer:
        return [["thorium_all"]]
    if target_os == "win":
        return [["thorium_all"], ["thorium_installer"]]
    if target_os == "linux":
        return [
            ["thorium_all"],
            ["chrome/installer/linux:stable_deb"],
            ["chrome/installer/linux:stable_rpm"],
        ]
    if target_os == "mac":
        return [["thorium_all"], ["chrome/installer/mac:mac"]]
    if target_os == "android":
        # thorium_all currently omits System WebView for x86 and x64, so keep
        # all three legacy Android products explicit for every Android CPU.
        return [
            ["chrome_public_apk"],
            ["content_shell_apk"],
            ["system_webview_apk"],
        ]
    if target_os == "chromeos":
        return [["thorium_all"]]
    raise BuildError(
        f"no default Thorium target policy exists for target_os={target_os!r}; "
        "use --target explicitly"
    )


def build_phases(
    target_os: str,
    *,
    no_installer: bool,
    requested_targets: list[str] | None,
    single_pass: bool,
) -> list[list[str]]:
    if requested_targets:
        unique_targets = dict.fromkeys(requested_targets)
        phases = [[target] for target in unique_targets]
    else:
        phases = default_phases(target_os, no_installer=no_installer)
    if single_pass and len(phases) > 1:
        return [[target for phase in phases for target in phase]]
    return phases


def is_windows_installer_target(target: str) -> bool:
    target = target.replace("\\", "/").lower().removeprefix("//").removeprefix("./")
    if target in {"setup", "setup.exe", "chrome/installer/setup", "chrome/installer/setup:setup"}:
        return True
    name = target.rsplit(":", 1)[-1].rsplit("/", 1)[-1]
    if name.startswith("thorium_") and name.endswith("_mini_installer.exe"):
        return True
    return name in {
        "thorium_installer", "mini_installer", "mini_installer_uncompressed",
        "mini_installer.exe", "mini_installer_uncompressed.exe", "thorium_arm64_installer.exe",
    }


def print_logo(thorium_root: Path) -> None:
    logo = thorium_root / "logos" / "thorium_logo_ascii_art.txt"
    try:
        contents = logo.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        print(f"warning: could not read {logo}: {error}", file=sys.stderr)
        return
    print()
    print(contents.rstrip())


def completion_message(
    target_os: str, out_dir: Path, *, built_default_installer: bool
) -> str:
    if built_default_installer:
        if target_os == "android":
            return f"Build completed. APK files are under {out_dir / 'apks'}."
        if target_os == "mac":
            return "Build completed. Run 'python3 create_dmg.py' to create the DMG."
        if target_os == "win":
            return (
                f"Build completed. The profile-named installer is under {out_dir}."
            )
        if target_os == "linux":
            return f"Build completed. DEB and RPM packages are under {out_dir}."
    return f"Build completed. Products are under {out_dir}."


def main(argv: Sequence[str] | None = None) -> int:
    if sys.version_info < MINIMUM_PYTHON:
        print("error: Python 3.11 or newer is required", file=sys.stderr)
        return 2

    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    try:
        chromium_src = arguments.chromium_src.resolve()
        thorium_root = arguments.thorium_root.resolve()
        out_dir = resolve_out_dir(chromium_src, arguments.out_dir)
        validate_checkout(chromium_src, thorium_root, out_dir)
        gn = find_tool("gn")
        autoninja = find_tool("autoninja")
        target_os = read_gn_argument(gn, chromium_src, out_dir, "target_os")
        target_cpu = read_gn_argument(gn, chromium_src, out_dir, "target_cpu")

        if arguments.expect_os and arguments.expect_os != target_os:
            raise BuildError(
                f"expected target OS {arguments.expect_os!r}, but GN reports "
                f"{target_os!r}"
            )
        if arguments.expect_cpu and arguments.expect_cpu != target_cpu:
            raise BuildError(
                f"expected target CPU {arguments.expect_cpu!r}, but GN reports "
                f"{target_cpu!r}"
            )

        build_steps: list[tuple[list[str], list[str]]] = []
        for phase in build_phases(
            target_os,
            no_installer=arguments.no_installer,
            requested_targets=arguments.target,
            single_pass=arguments.single_pass,
        ):
            ninja_arguments = ["-C", str(out_dir), *phase]
            if arguments.jobs is not None:
                ninja_arguments.extend(["-j", str(arguments.jobs)])
            command = platform_command(autoninja, ninja_arguments)
            build_steps.append((phase, command))

        print(f"Host: {platform.system()} {platform.machine()}")
        print(f"GN target: {target_os} {target_cpu}")
        print(f"Output directory: {out_dir}")
        phase_count = len(build_steps)
        for index, (phase, command) in enumerate(build_steps, start=1):
            print(f"Phase {index}/{phase_count} targets: {', '.join(phase)}")
            print(f"Phase {index}/{phase_count} command: {display_command(command)}")
        if target_os == "win" and any(
            is_windows_installer_target(target)
            for phase, _ in build_steps
            for target in phase
        ):
            check = [
                sys.executable,
                str(thorium_root / "patch_scripts/grd_rebase/merge_thorium_xtb.py"),
                str(chromium_src),
                "--check",
            ]
            print(f"Checking installer translations: {display_command(check)}", flush=True)
            result = subprocess.run(check, cwd=chromium_src)
            if result.returncode:
                return normalize_exit_status(result.returncode)
        if arguments.dry_run:
            return 0

        environment = os.environ.copy()
        environment["NINJA_SUMMARIZE_BUILD"] = "1"
        environment["NINJA_STATUS"] = NINJA_STATUS
        for index, (_, command) in enumerate(build_steps, start=1):
            print(f"Starting build phase {index}/{phase_count}...")
            try:
                subprocess.run(
                    command,
                    check=True,
                    cwd=chromium_src,
                    env=environment,
                )
            except subprocess.CalledProcessError as error:
                raise BuildFailure(index, phase_count, error.returncode) from error
        print_logo(thorium_root)
        print(
            completion_message(
                target_os,
                out_dir,
                built_default_installer=not arguments.no_installer
                and arguments.target is None,
            )
        )
        return 0
    except BuildFailure as error:
        print(f"error: {error}", file=sys.stderr)
        return normalize_exit_status(error.returncode)
    except (BuildError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("error: build interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
