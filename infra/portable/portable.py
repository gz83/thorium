#!/usr/bin/env python3

# Copyright (c) 2026 Alex313031 and gz83.

"""Create a Thorium portable ZIP from a Linux package or Windows installer."""

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time
from typing import Sequence
import zipfile


MINIMUM_PYTHON = (3, 11)
VERSION_PATTERN = re.compile(r"(?<!\d)(\d+\.\d+\.\d+\.\d+)(?!\d)")
RELEASE_PROFILES = (
    "AVX512",
    "AVX2",
    "SSE2",
    "SSE4",
    "SSE3",
    "ARM64",
    "AVX",
)


class PortableError(RuntimeError):
    """An expected portable packaging failure."""


@dataclass(frozen=True)
class LinuxPackageMetadata:
    version: str
    architecture: str


@dataclass(frozen=True)
class WindowsPackageMetadata:
    version: str
    shell: Path
    architecture: str


def environment_path(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser()


def profile_argument(value: str) -> str:
    profile = value.upper()
    if profile in RELEASE_PROFILES:
        return profile
    allowed = ", ".join(RELEASE_PROFILES)
    raise argparse.ArgumentTypeError(
        f"unsupported profile {value!r}; choose one of: {allowed}"
    )


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--platform",
        choices=("auto", "linux", "windows"),
        default="auto",
        help="input package platform (default: infer from its suffix)",
    )
    parser.add_argument(
        "--input",
        type=environment_path,
        required=True,
        metavar="PATH",
        help="Thorium .deb package or Windows mini installer",
    )
    parser.add_argument(
        "--output",
        type=environment_path,
        metavar="PATH",
        help="output ZIP path (default: next to the input package)",
    )
    parser.add_argument(
        "--seven-zip",
        type=environment_path,
        metavar="PATH",
        help="7-Zip executable for Windows installers (default: search PATH)",
    )
    parser.add_argument(
        "--profile",
        type=profile_argument,
        metavar="NAME",
        help=(
            "SIMD profile used in the release-style output name when it "
            "cannot be inferred"
        ),
    )
    parser.add_argument(
        "--expected-version",
        metavar="VERSION",
        help="require the extracted Thorium version to match this value",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing output archive",
    )
    return parser.parse_args(argv)


def detect_platform(requested: str, package: Path) -> str:
    suffix = package.suffix.lower()
    if requested != "auto":
        conflicting = {("linux", ".exe"), ("windows", ".deb")}
        if (requested, suffix) in conflicting:
            raise PortableError(
                f"--platform {requested} conflicts with input suffix {suffix}"
            )
        return requested
    if suffix == ".deb":
        return "linux"
    if suffix == ".exe":
        return "windows"
    raise PortableError("could not infer the platform; pass --platform explicitly")


def execute(
    command: Sequence[str], *, capture_output: bool
) -> subprocess.CompletedProcess[str]:
    if not capture_output:
        rendered_command = (
            subprocess.list2cmdline(command)
            if os.name == "nt"
            else shlex.join(command)
        )
        print(f"Running: {rendered_command}")
    try:
        if not capture_output:
            return subprocess.run(command, check=True)
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.CalledProcessError as error:
        details = ""
        if capture_output:
            details = (error.stderr or error.stdout or "").strip()
        suffix = f": {details}" if details else ""
        raise PortableError(
            f"command failed with exit code {error.returncode}: "
            f"{command[0]}{suffix}"
        ) from error
    except OSError as error:
        raise PortableError(f"could not run {command[0]}: {error}") from error


def run(command: Sequence[str]) -> None:
    execute(command, capture_output=False)


def run_capture(command: Sequence[str]) -> str:
    return execute(command, capture_output=True).stdout.strip()


def find_program(name: str, configured: Path | None = None) -> str:
    if configured is not None:
        configured = configured.resolve()
        if not configured.is_file():
            raise PortableError(f"program does not exist: {configured}")
        return str(configured)
    found = shutil.which(name)
    if not found and name == "7z" and os.name == "nt":
        candidates = (
            Path(os.environ.get("ProgramFiles", "C:/Program Files"))
            / "7-Zip/7z.exe",
            Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
            / "7-Zip/7z.exe",
        )
        found = next((str(path) for path in candidates if path.is_file()), None)
    if not found:
        raise PortableError(f"{name} was not found in PATH")
    return found


def validate_payload_tree(root: Path) -> None:
    if not root.is_dir():
        raise PortableError(f"package payload directory is missing: {root}")
    root = root.resolve()
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                mode = entry.stat(follow_symlinks=False).st_mode
                if stat.S_ISDIR(mode):
                    pending.append(path)
                elif stat.S_ISREG(mode):
                    continue
                elif stat.S_ISLNK(mode):
                    target = os.readlink(path)
                    try:
                        resolved_target = (path.parent / target).resolve(strict=True)
                    except FileNotFoundError as error:
                        raise PortableError(
                            f"broken symbolic link in package payload: "
                            f"{path.relative_to(root)} -> {target}"
                        ) from error
                    if not resolved_target.is_relative_to(root):
                        raise PortableError(
                            f"symbolic link escapes the package payload: "
                            f"{path.relative_to(root)} -> {target}"
                        )
                else:
                    raise PortableError(
                        f"unsupported special file in package payload: "
                        f"{path.relative_to(root)}"
                    )


def inspect_linux_package(package: Path, dpkg_deb: str) -> LinuxPackageMetadata:
    fields = run_capture(
        (
            dpkg_deb,
            "--show",
            "--showformat=${Package}\n${Version}\n${Architecture}\n",
            str(package),
        )
    ).splitlines()
    if len(fields) != 3:
        raise PortableError(
            "could not read package name, version, and architecture from "
            f"Debian package metadata: {package}"
        )
    package_name, package_version, architecture = fields
    if package_name != "thorium-browser":
        raise PortableError(
            f"unexpected Debian package name {package_name!r}; expected "
            "'thorium-browser'"
        )
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]*", architecture):
        raise PortableError(f"invalid Debian architecture {architecture!r}")
    version_match = VERSION_PATTERN.search(package_version)
    if not version_match:
        raise PortableError(
            f"could not determine Thorium version from Debian version "
            f"{package_version!r}"
        )
    return LinuxPackageMetadata(version_match.group(1), architecture)


def extract_linux(
    package: Path,
    staging: Path,
    work: Path,
    dpkg_deb: str,
) -> None:
    extracted = work / "deb"
    run((dpkg_deb, "--extract", str(package), str(extracted)))
    payload = extracted / "opt/chromium.org/thorium"
    validate_payload_tree(payload)
    shutil.copytree(payload, staging, symlinks=True)
    for obsolete in ("apparmor.d", "cron", "thorium-browser"):
        path = staging / obsolete
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()
    browser = staging / "thorium"
    if not browser.is_file() or browser.is_symlink():
        raise PortableError(
            "Thorium browser executable is missing from the DEB payload"
        )
    if not browser.stat().st_mode & 0o111:
        raise PortableError("Thorium browser file in the DEB is not executable")
    sandbox = staging / "chrome-sandbox"
    if not sandbox.is_file() or sandbox.is_symlink():
        raise PortableError("Chrome sandbox helper is missing from the DEB payload")
    sandbox.chmod(stat.S_IMODE(sandbox.stat().st_mode) & 0o777)
    shell = staging / "thorium_shell"
    if not shell.is_file() or shell.is_symlink():
        raise PortableError("Thorium Content Shell is missing from the DEB payload")
    if not shell.stat().st_mode & 0o111:
        raise PortableError("Thorium Content Shell file in the DEB is not executable")


def find_unique(
    root: Path,
    name: str,
    location: str,
    *,
    directory: bool = False,
) -> Path:
    match = None
    for path in root.rglob(name):
        matches_type = path.is_dir() if directory else path.is_file()
        if matches_type:
            if match is not None:
                raise PortableError(
                    f"expected exactly one {name} in {location}; found multiple"
                )
            match = path
    if match is None:
        raise PortableError(
            f"expected exactly one {name} in {location}; found none"
        )
    return match


def extract_windows(
    package: Path,
    staging: Path,
    work: Path,
    seven_zip: Path | None,
) -> WindowsPackageMetadata:
    executable = find_program("7z", seven_zip)
    installer = work / "installer"
    payload = work / "payload"
    installer.mkdir()
    payload.mkdir()
    run((executable, "x", "-y", f"-o{installer}", str(package)))
    chrome_archive = find_unique(installer, "chrome.7z", "the extracted installer")
    run((executable, "x", "-y", f"-o{payload}", str(chrome_archive)))
    chrome_bin = find_unique(
        payload,
        "Chrome-bin",
        "the installer payload",
        directory=True,
    )
    validate_payload_tree(chrome_bin)
    shutil.copytree(chrome_bin, staging / "BIN", symlinks=True)
    (staging / "USER_DATA").mkdir()
    browser = staging / "BIN/thorium.exe"
    if not browser.is_file() or browser.is_symlink():
        raise PortableError("Thorium browser executable is missing from the installer")
    version_directory = windows_version_directory(staging)
    shell = version_directory / "thorium_shell.exe"
    if not shell.is_file() or shell.is_symlink():
        raise PortableError(
            "Thorium Content Shell is missing from the Windows version directory"
        )
    return WindowsPackageMetadata(
        version_directory.name,
        shell.relative_to(staging),
        windows_executable_architecture(browser),
    )


def windows_executable_architecture(executable: Path) -> str:
    try:
        with executable.open("rb") as binary:
            if binary.read(2) != b"MZ":
                raise PortableError(
                    f"Windows executable has no DOS header: {executable}"
                )
            binary.seek(0x3C)
            pe_offset_data = binary.read(4)
            if len(pe_offset_data) != 4:
                raise PortableError(
                    f"Windows executable has a truncated DOS header: {executable}"
                )
            pe_offset = struct.unpack("<I", pe_offset_data)[0]
            binary.seek(pe_offset)
            if binary.read(4) != b"PE\0\0":
                raise PortableError(
                    f"Windows executable has no PE signature: {executable}"
                )
            machine_data = binary.read(2)
    except (OSError, OverflowError) as error:
        raise PortableError(
            f"could not inspect Windows executable architecture: {executable}: {error}"
        ) from error

    if len(machine_data) != 2:
        raise PortableError(f"Windows executable has no PE machine field: {executable}")
    machine = struct.unpack("<H", machine_data)[0]
    architecture = {
        0x014C: "x86",
        0x8664: "x64",
        0xAA64: "arm64",
    }.get(machine)
    if architecture is None:
        raise PortableError(
            f"unsupported Windows PE machine 0x{machine:04X}: {executable}"
        )
    return architecture


def windows_version_directory(staging: Path) -> Path:
    bin_dir = staging / "BIN"
    versions = [
        path
        for path in bin_dir.iterdir()
        if path.is_dir() and VERSION_PATTERN.fullmatch(path.name)
    ]
    if len(versions) != 1:
        raise PortableError(
            "expected exactly one version directory in the Windows payload; "
            f"found {len(versions)}"
        )
    return versions[0]


def inferred_profile(package: Path) -> str | None:
    filename_parts = set(re.split(r"[_-]", package.stem.upper()))
    for profile in RELEASE_PROFILES:
        if profile in filename_parts:
            return profile
    return None


def profile_name(package: Path, configured: str | None) -> str | None:
    inferred = inferred_profile(package)
    if configured and inferred and configured != inferred:
        raise PortableError(
            f"--profile {configured!r} conflicts with profile {inferred!r} "
            "in the installer filename"
        )
    return configured or inferred


def windows_release_variant(profile: str, architecture: str) -> str:
    if architecture == "x86":
        if profile == "ARM64":
            raise PortableError("ARM64 profile conflicts with Windows x86 payload")
        return f"WIN32_{profile}"
    if architecture == "x64":
        if profile == "ARM64":
            raise PortableError("ARM64 profile conflicts with Windows x64 payload")
        return profile
    if architecture == "arm64":
        if profile != "ARM64":
            raise PortableError(
                f"profile {profile!r} conflicts with Windows ARM64 payload"
            )
        return profile
    raise PortableError(f"unsupported Windows architecture {architecture!r}")


def linux_release_variant(
    package: Path,
    architecture: str,
    configured_profile: str | None,
) -> str:
    architecture_variant = {
        "arm64": "arm64",
        "i386": "i386",
    }.get(architecture)
    inferred = inferred_profile(package)

    if architecture_variant is not None:
        expected_profile = "ARM64" if architecture == "arm64" else None
        if configured_profile and configured_profile != expected_profile:
            raise PortableError(
                f"--profile {configured_profile!r} conflicts with Debian "
                f"architecture {architecture!r}"
            )
        if inferred and inferred != expected_profile:
            raise PortableError(
                f"profile {inferred!r} in the package filename conflicts with "
                f"Debian architecture {architecture!r}"
            )
        return architecture_variant

    if architecture != "amd64":
        raise PortableError(
            f"unsupported Debian architecture {architecture!r} for release naming"
        )
    profile = profile_name(package, configured_profile)
    if profile is None:
        raise PortableError(
            "could not infer the Linux SIMD profile; pass --profile to create "
            "a release-style archive name"
        )
    if profile == "ARM64":
        raise PortableError("ARM64 profile conflicts with Debian architecture 'amd64'")
    return profile


def default_output(
    package: Path,
    platform_name: str,
    version: str,
    release_variant: str,
) -> Path:
    if platform_name == "windows":
        name = f"Thorium_{release_variant}_{version}.zip"
    elif platform_name == "linux":
        product = (
            "thorium-browser-v4l2"
            if package.name.startswith("thorium-browser-v4l2_")
            else "thorium-browser"
        )
        name = f"{product}_{version}_{release_variant}.zip"
    else:
        raise PortableError("could not determine a release-style output name")
    return package.parent / name


def validate_expected_version(actual: str, expected: str | None) -> None:
    if expected and actual != expected:
        raise PortableError(
            f"version mismatch: expected {expected!r}, package contains {actual!r}"
        )


def prepare_linux_package(
    package: Path,
    staging: Path,
    work: Path,
    configured_profile: str | None,
    expected_version: str | None,
) -> tuple[LinuxPackageMetadata, str]:
    dpkg_deb = find_program("dpkg-deb")
    metadata = inspect_linux_package(package, dpkg_deb)
    validate_expected_version(metadata.version, expected_version)
    release_variant = linux_release_variant(
        package,
        metadata.architecture,
        configured_profile,
    )
    extract_linux(package, staging, work, dpkg_deb)
    return metadata, release_variant


def prepare_windows_package(
    package: Path,
    staging: Path,
    work: Path,
    seven_zip: Path | None,
    configured_profile: str | None,
    expected_version: str | None,
) -> tuple[WindowsPackageMetadata, str]:
    profile = profile_name(package, configured_profile)
    if profile is None:
        raise PortableError(
            "could not infer the Windows SIMD profile; pass --profile to "
            "create a release-style archive name"
        )
    staging.mkdir()
    metadata = extract_windows(package, staging, work, seven_zip)
    validate_expected_version(metadata.version, expected_version)
    return metadata, windows_release_variant(profile, metadata.architecture)


def copy_support_files(
    portable_dir: Path,
    staging: Path,
    metadata: LinuxPackageMetadata | WindowsPackageMetadata,
) -> None:
    if isinstance(metadata, LinuxPackageMetadata):
        files = (
            ("README.linux", "README.txt"),
            ("launchers/linux-browser.sh", "THORIUM-PORTABLE"),
            ("launchers/linux-shell.sh", "THORIUM-SHELL"),
            (
                "desktop/thorium-portable.desktop.in",
                "thorium-portable.desktop.example",
            ),
            (
                "desktop/thorium-shell.desktop.in",
                "thorium-shell.desktop.example",
            ),
        )
    else:
        files = (
            ("README.win", "README.txt"),
            ("launchers/windows-browser.cmd", "THORIUM.BAT"),
            ("launchers/windows-shell.cmd", "THORIUM_SHELL.BAT"),
        )
    for source_name, destination_name in files:
        source = portable_dir / source_name
        if not source.is_file():
            raise PortableError(f"portable support file is missing: {source}")
        shutil.copy2(source, staging / destination_name)
    if isinstance(metadata, WindowsPackageMetadata):
        placeholder = b"@THORIUM_SHELL_RELATIVE@"
        launcher = staging / "THORIUM_SHELL.BAT"
        launcher_contents = launcher.read_bytes()
        if launcher_contents.count(placeholder) != 1:
            raise PortableError(
                "Windows Shell launcher must contain exactly one "
                "@THORIUM_SHELL_RELATIVE@ placeholder"
            )
        relative_shell = metadata.shell.as_posix().replace("/", "\\")
        launcher.write_bytes(
            launcher_contents.replace(placeholder, relative_shell.encode("ascii"))
        )
        for name in ("THORIUM.BAT", "THORIUM_SHELL.BAT"):
            path = staging / name
            contents = path.read_bytes().replace(b"\r\n", b"\n").replace(
                b"\r", b"\n"
            )
            path.write_bytes(contents.replace(b"\n", b"\r\n"))
    else:
        for name in ("THORIUM-PORTABLE", "THORIUM-SHELL"):
            path = staging / name
            path.chmod(path.stat().st_mode | 0o111)


def process_state(process_id: int) -> tuple[bool, str | None]:
    if process_id <= 0:
        return False, None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        )
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        )
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.GetProcessTimes.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        )
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(
            process_query_limited_information, False, process_id
        )
        if not handle:
            # ERROR_INVALID_PARAMETER means the PID does not exist. Other errors,
            # such as access denial, cannot safely prove that a lock is stale.
            return ctypes.get_last_error() != 87, None
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True, None
            if exit_code.value != still_active:
                return False, None
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel_time = wintypes.FILETIME()
            user_time = wintypes.FILETIME()
            if not kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel_time),
                ctypes.byref(user_time),
            ):
                return True, None
            identity = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
            return True, str(identity)
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False, None
    except PermissionError:
        return True, None
    except OSError:
        return True, None
    try:
        result = subprocess.run(
            ("ps", "-o", "lstart=", "-p", str(process_id)),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "LC_ALL": "C"},
        )
    except OSError:
        return True, None
    identity = result.stdout.strip() if result.returncode == 0 else ""
    return True, identity or None


@contextmanager
def output_lock(output: Path):
    lock = output.with_name(f".{output.name}.lock")
    current_running, current_identity = process_state(os.getpid())
    if not current_running:
        raise PortableError("could not identify the current packaging process")
    for attempt in range(2):
        try:
            descriptor = os.open(
                lock,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError as error:
            lock_error = error
        else:
            lock_initialized = False
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as lock_file:
                    json.dump(
                        {"pid": os.getpid(), "identity": current_identity},
                        lock_file,
                    )
                    lock_file.write("\n")
                    lock_file.flush()
                    os.fsync(lock_file.fileno())
                    acquired_stat = os.fstat(lock_file.fileno())
                lock_initialized = True
            finally:
                if not lock_initialized:
                    try:
                        lock.unlink()
                    except FileNotFoundError:
                        pass
            break
        try:
            lock_stat = lock.stat()
        except OSError as stat_error:
            raise PortableError(
                f"could not inspect output lock {lock}: {stat_error}"
            ) from stat_error
        record_valid = True
        try:
            record = json.loads(lock.read_text(encoding="utf-8"))
            process_id = int(record["pid"])
            recorded_identity = record.get("identity")
            if recorded_identity is not None:
                recorded_identity = str(recorded_identity)
        except (OSError, TypeError, ValueError, KeyError):
            record_valid = False
            process_id = -1
            recorded_identity = None
        if not record_valid and time.time() - lock_stat.st_mtime < 60:
            raise PortableError(
                f"another portable packaging process is initializing the "
                f"output lock: {lock}"
            ) from lock_error
        running, observed_identity = process_state(process_id)
        same_process = running and (
            recorded_identity is None
            or observed_identity is None
            or recorded_identity == observed_identity
        )
        if same_process:
            raise PortableError(
                f"another portable packaging process holds the output lock: {lock}"
            ) from lock_error
        if attempt:
            raise PortableError(
                f"stale output lock could not be recovered automatically: {lock}"
            ) from lock_error
        try:
            if lock.stat().st_ino != lock_stat.st_ino:
                continue
            lock.unlink()
        except OSError as cleanup_error:
            raise PortableError(
                f"could not remove stale output lock {lock}: {cleanup_error}"
            ) from cleanup_error
        print(f"warning: removed stale output lock: {lock}", file=sys.stderr)
    else:
        raise PortableError(f"could not acquire output lock: {lock}")

    try:
        yield
    finally:
        try:
            if lock.stat().st_ino != acquired_stat.st_ino:
                print(
                    f"warning: output lock changed ownership and was preserved: {lock}",
                    file=sys.stderr,
                )
            else:
                lock.unlink()
        except FileNotFoundError:
            pass
        except OSError as error:
            print(
                f"warning: could not remove output lock {lock}: {error}",
                file=sys.stderr,
            )


def write_zip(staging: Path, output: Path, *, force: bool) -> None:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output_lock(output):
        if output.exists() and not force:
            raise PortableError(
                f"output already exists; pass --force to replace it: {output}"
            )
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output.name}.", suffix=".new", dir=output.parent
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            with zipfile.ZipFile(
                temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
            ) as archive:
                staging_root = staging.resolve()
                for path in sorted(staging.rglob("*")):
                    relative = path.relative_to(staging).as_posix()
                    if path.is_symlink():
                        target = os.readlink(path)
                        try:
                            resolved_target = (path.parent / target).resolve(
                                strict=True
                            )
                        except FileNotFoundError as error:
                            raise PortableError(
                                f"broken symbolic link in package payload: "
                                f"{relative} -> {target}"
                            ) from error
                        if not resolved_target.is_relative_to(staging_root):
                            raise PortableError(
                                f"symbolic link escapes the package payload: "
                                f"{relative} -> {target}"
                            )
                        info = zipfile.ZipInfo(relative)
                        info.create_system = 3
                        info.external_attr = (stat.S_IFLNK | 0o777) << 16
                        archive.writestr(info, os.fsencode(target))
                    elif path.is_dir():
                        info = zipfile.ZipInfo(f"{relative}/")
                        info.external_attr = (path.stat().st_mode & 0xFFFF) << 16
                        archive.writestr(info, b"")
                    elif path.is_file():
                        archive.write(path, relative)
                    else:
                        raise PortableError(
                            f"unsupported special file in package payload: {relative}"
                        )
            current_umask = os.umask(0)
            os.umask(current_umask)
            temporary.chmod(0o666 & ~current_umask)
            if not force and output.exists():
                raise PortableError(
                    f"output was created while packaging; pass --force to "
                    f"replace it: {output}"
                )
            os.replace(temporary, output)
        finally:
            if temporary.exists() or temporary.is_symlink():
                temporary.unlink()


def main(argv: Sequence[str] | None = None) -> int:
    if sys.version_info < MINIMUM_PYTHON:
        print("error: Python 3.11 or newer is required", file=sys.stderr)
        return 2
    args = parse_arguments(sys.argv[1:] if argv is None else argv)
    try:
        package = args.input.resolve()
        if not package.is_file():
            raise PortableError(f"input package does not exist: {package}")
        if args.output is not None and args.output.resolve() == package:
            raise PortableError("output archive must not replace the input package")
        platform_name = detect_platform(args.platform, package)
        if platform_name == "linux" and args.seven_zip is not None:
            raise PortableError("--seven-zip is only valid for Windows packages")
        portable_dir = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(prefix="thorium-portable-") as temporary:
            work = Path(temporary)
            staging = work / "staging"
            if platform_name == "linux":
                metadata, release_variant = prepare_linux_package(
                    package,
                    staging,
                    work,
                    args.profile,
                    args.expected_version,
                )
            else:
                metadata, release_variant = prepare_windows_package(
                    package,
                    staging,
                    work,
                    args.seven_zip,
                    args.profile,
                    args.expected_version,
                )
            copy_support_files(portable_dir, staging, metadata)
            output = (
                args.output.resolve()
                if args.output is not None
                else default_output(
                    package,
                    platform_name,
                    metadata.version,
                    release_variant,
                ).resolve()
            )
            write_zip(staging, output, force=args.force)
        print(f"Portable archive: {output}")
    except (PortableError, OSError, shutil.Error) as error:
        print(f"{Path(sys.argv[0]).name}: {error}", file=sys.stderr)
        return 111
    except KeyboardInterrupt:
        print(f"\n{Path(sys.argv[0]).name}: interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
