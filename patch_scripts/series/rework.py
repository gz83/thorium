#!/usr/bin/env python3
# Copyright (c) 2026 Alex313031 and gz83.
"""Apply the pinned Windows REWORK series after Thorium's selected patches."""

import csv
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile


# These two hashes identify files published by the withdrawn #345 adaptation.
WITHDRAWN_345 = {
    "base/process/launch_win.cc": "f6897fe8f32fbe1be98a49a3eca2c10dfd4ab28a0662f63c5625be01c6bd43aa",
    "remoting/host/win/launch_process_with_token.cc": "ae52501b4e2cea0b6e0f4d8d68b6eaaef03fba01785c8a29e36e617be0d8767b",
}

# Both fresh donor applications and trees prepared before the localization
# fix can reach these exact inputs to the final patch.
LOCALIZATION_INPUTS = {
    "chrome/browser/chrome_browser_main_win.cc": "70d6f8883bfe928c443ee5d1fab2d1f644b6feef7613bf47cfeb5918702d9921",
    "third_party/blink/renderer/platform/text/locale_win.cc": "34978e9f5d77fe89587ab3c47ddff262ddad893e861674bc340f57fd2b633b58",
}

# Postimages before the installer, font and locale-consumer repair. Older
# prepared trees can resume here without replaying donor patches.
LOCALE_CONSUMER_INPUTS = {
    "base/BUILD.gn": "78f57e987eb759b86761f60b801b8b60554153371f9a62422057d04c9696d0db",
    "base/i18n/win/preferred_languages.cc": "c36ae420d91385b5d89de382235fa6411cec480043906e050a1bd236f62ba7e0",
    "base/win/legacy_locale.h": "-",
    "chrome/installer/mini_installer/BUILD.gn": "28565aef0e6a332e57bd63ce0acb1856373714f4a6a25ed2fea26f81eca2729e",
    "chrome/installer/mini_installer/mini_installer.cc": "2155c6f77ad141251b01375b9b122dc3a5dca31c454db433f6e7c8113494d235",
    "chrome/installer/mini_installer/mini_installer_localization.cc": "29e7bdbb6d6a1aa2473134d1aa9888f93b6cd10976fbf6afd6e329948a0dd4bd",
    "content/browser/sandbox_support_win_impl.cc": "78c2d8e88f318eeb5f173e1e6383d83795d73dac7620d3a3b11b775945b79aa0",
    "third_party/blink/renderer/platform/text/locale_win.cc": "6d76efdd6d5f2130e19885ca0cbbcedd16b86f898e8ccbeccb97aa17757579a4",
    "ui/accessibility/platform/ax_platform_node_win.cc": "97458d70650ef50bd004353e5a585b705e51b63ddeae5cd6f79757d55e2f7881",
    "ui/base/l10n/l10n_util_win.cc": "d68ca43f357122d1bac4cd667797a7d85c94f538f42d9e51b1b5392ed2e52eef",
    "ui/base/l10n/l10n_util_win.h": "ee48d62b0b6abd8d76ac31befdf91fe40625b86febef1278491bcd80a84b3b08",
    "ui/views/corewm/tooltip_win.cc": "618372bb19b980d9203b59d8bd18e308c0049de485e55557fc54d2a84b6cd932",
}


LOCALE_RUNTIME_INPUTS = {
    "base/i18n/win/preferred_languages.cc": "e4086934160d816fb502962affb8e0f75d7ff9ce83796100036ad2d0a86a0000",
    "base/win/legacy_locale.h": "11d5a3767602b99b36036785a831bf5ff86b340fc073c46dd239e17b29335382",
    "chrome/installer/mini_installer/mini_installer_localization.cc": "c161995f2e08587242bfeb230f5610c2f7a0f7ba52ead3d210b9b2c2078a28b9",
    "content/browser/speech/tts_win.cc": "ca753f2fa4fc9d0a15ff43e3a43370c5767dacab1d0614be22eac501d45f6ea7",
    "sandbox/win/src/handle_closer_agent.cc": "00de1131a2142e667abe5616e17d6f93b92c7a986278bc8ac28782280ca99527",
    "third_party/icu/source/common/putil.cpp": "418b5adb8b6b137ec731d0cfc6686345996353004f0f982832fb3077cd945f2f",
    "third_party/icu/source/i18n/windtfmt.cpp": "46212636729c6f78544be687c8a65a59b99cc5642236044a4286563db256703a",
}

LOCALE_INTEGRATION_INPUTS = {
    "base/win/legacy_locale.h": "c98e639e36aa4217dd38572bcaa6e04f72a800dddd43cb579031a8994b1cd589",
    "chrome/browser/resources/settings/BUILD.gn": "f1dd99d29b3f16fd538895a27e08bb50ea102e07d3a9c3ba6ad7bcd9ae8f7c06",
    "chrome/browser/resources/settings/a11y_page/a11y_page.html.ts": "422af28370b79de6e526f5e8538f7e2572413a056620321e66f731111de28904",
    "chrome/browser/resources/settings/a11y_page/a11y_page.ts": "b0039c67df332dce846e157d8e4bdb856e4d3ff203561cdc9fc0fba36c068d49",
    "chrome/browser/resources/settings/a11y_page/a11y_page_index.html.ts": "541f304e8671cdc760eb8f0e7634d3b62a4b8797c1b00d96c7ed8ca1ed06f099",
    "chrome/browser/resources/settings/a11y_page/a11y_page_index.ts": "efc33981606e7f5ccce88ca2b5d09f7fda77f23dd64d412c0f3d9e264a1607e7",
    "components/system_cpu/cpu_probe_win.cc": "1dd3ebe61b16467b99a91810c6f6e5d3bfb7a3bfc1711005070c25589754d174",
    "ui/shell_dialogs/execute_select_file_win.cc": "6185b18b1064d0733a190f982e8d4d79f308b8e5301dd9dca453f9ef9fe97e66",
}

LOCALE_REPAIRS = (
    (LOCALIZATION_INPUTS, "windows-localization.diff"),
    (LOCALE_CONSUMER_INPUTS, "windows-locale-consumers.diff"),
    (LOCALE_RUNTIME_INPUTS, "windows-locale-runtime.diff"),
    (LOCALE_INTEGRATION_INPUTS, "windows-locale-integration.diff"),
)


def checked_path(root, name):
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or ":" in name or "\\" in name:
        raise ValueError(f"invalid path in REWORK series: {name}")
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError(f"path leaves checkout: {path}")
    return path


def file_bytes(path):
    if not path.exists():
        return None
    return path.read_bytes()


def normalized(data):
    if data is None or b"\0" in data:
        return data
    return data.replace(b"\r\n", b"\n")


def digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else "-"


def load_states(directory, sse2):
    states = {}
    with (directory / "file-states.tsv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            values = [row["input"], row["thorium"], row["rework"]]
            if sse2 and row["sse2_override"]:
                values = row["sse2_override"].split(",")
            if values == ["!"] * 3:
                continue
            start, regular, final = values
            if regular == "=":
                regular = start
            if final == "=":
                final = regular
            states[row["path"]] = (start, regular, final)
    return states


def load_donors(directory):
    patches = []
    with (directory / "series.tsv").open(encoding="utf-8", newline="") as stream:
        for index, row in enumerate(csv.DictReader(stream, delimiter="\t"), 1):
            if int(row["order"]) != index:
                raise ValueError(f"out-of-order REWORK entry {row['donor']}")
            if row["patch"] == "-":
                continue
            patch = checked_path(directory, row["patch"])
            data = patch.read_bytes()
            if digest(data) != row["patch_sha256"]:
                raise ValueError(f"REWORK patch SHA-256 mismatch: {patch.name}")
            if row["status"] == "upstream" and row["upstream_sha256"] != row["patch_sha256"]:
                raise ValueError(f"modified upstream patch: {patch.name}")
            patches.append((".", patch, data))
    return patches


def apply_layer(stage, patches, pending, states, *, rework):
    for root, patch, data in patches:
        sections = re.split(rb"(?m)(?=^diff --git )", data)
        selected = []
        total = 0
        for section in sections:
            if not section.startswith(b"diff --git "):
                continue
            # Binary Git diffs have only the diff --git path header.
            match = (re.search(rb"(?m)^\+\+\+ b/([^\r\n\t]+)", section)
                     or re.search(rb"(?m)^--- a/([^\r\n\t]+)", section)
                     or re.match(rb"diff --git a/.+? b/([^\r\n]+)", section))
            if not match:
                raise ValueError(f"missing path in {patch.name}")
            name = (PurePosixPath(root) / match[1].decode()).as_posix()
            if name not in states:
                raise ValueError(f"{patch.name}: unrecorded target {name}")
            total += 1
            if name in pending:
                selected.append(section)
        if not total:
            raise ValueError(f"no Git diff in {patch.name}")
        if not selected:
            continue
        args = ["git", "-c", "core.autocrlf=false", "-c", "core.longpaths=true",
                "apply", "--no-index", "--whitespace=nowarn"]
        if rework:
            args.append("--ignore-space-change")
        if root != ".":
            args.append("--directory=" + root)
        # A recovered checkout can contain both completed and pending files.
        # On clean input pass the original patch to Git without rewriting it.
        if len(selected) == total:
            args.append(str(patch))
            content = None
        else:
            args.append("-")
            content = b"".join(selected)
        result = subprocess.run(args, cwd=stage, input=content, capture_output=True)
        if result.returncode:
            raise ValueError(f"{patch.name}: {os.fsdecode(result.stderr).strip()}")


def publish(path, result, original):
    # The staged bytes always use Git's text convention. Preserve an existing
    # CRLF checkout and its file permissions when replacing a text file.
    if result is None:
        path.unlink(missing_ok=True)
        return
    if (original and b"\0" not in original and b"\r\n" in original
            and b"\n" not in original.replace(b"\r\n", b"")):
        result = normalized(result).replace(b"\n", b"\r\n") if b"\0" not in result else result
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    descriptor, name = tempfile.mkstemp(dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(result)
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def apply(source_tree, thorium_root, ordinary, conditions, write):
    directory = thorium_root / "other/rework-windows"
    states = load_states(directory, "sse2" in conditions)
    # setup.py subsequently synchronizes translated GRDs and copies the SIMD
    # profile's version label. Accept those verified outputs on a second run.
    with (directory / "setup-outputs.tsv").open(encoding="utf-8", newline="") as stream:
        prepared = {row["path"]: row["sha256"] for row in csv.DictReader(stream, delimiter="\t")
                    if row["profile"] == "all" or row["profile"] in conditions}
    donors = load_donors(directory)
    regular = [(e.apply_root, thorium_root / e.patch_path,
                (thorium_root / e.patch_path).read_bytes()) for e in ordinary]
    print(f"Checking {len(regular)} Thorium and {len(donors)} REWORK patches", flush=True)
    inputs = {}
    first_layer = set()
    withdrawn = set()
    resume_at = {}
    repair_inputs = {(name, sha): index for index, (hashes, _) in enumerate(LOCALE_REPAIRS)
                     for name, sha in hashes.items()}
    with tempfile.TemporaryDirectory(prefix="thorium-rework-") as temp:
        stage = Path(temp)
        for name, (start, mid, end) in states.items():
            path = checked_path(source_tree, name)
            data = normalized(file_bytes(path))
            actual = digest(data)
            if actual == end or actual == prepared.get(name):
                continue
            if actual == WITHDRAWN_345.get(name):
                withdrawn.add(name)
            elif (name, actual) in repair_inputs:
                resume_at[name] = repair_inputs[name, actual]
            elif actual not in (start, mid):
                raise ValueError(f"{name}: unexpected input {actual} (expected {start}, {mid} or {end})")
            elif actual != mid:
                first_layer.add(name)
            inputs[name] = actual
            if data is not None:
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        apply_layer(stage, regular, first_layer, states, rework=False)
        for name in first_layer:
            if digest(normalized(file_bytes(stage / name))) != states[name][1]:
                raise ValueError(f"{name}: unexpected intermediate Thorium output")
        apply_layer(stage, donors, inputs.keys() - withdrawn - resume_at.keys(), states, rework=True)
        if withdrawn:
            repair = directory / "repairs/withdraw-345.diff"
            apply_layer(stage, [(".", repair, repair.read_bytes())], withdrawn, states, rework=False)
        for index, (hashes, filename) in enumerate(LOCALE_REPAIRS):
            pending = {name for name in inputs.keys() & hashes.keys() if resume_at.get(name, 0) <= index}
            if pending:
                repair = directory / "repairs" / filename
                apply_layer(stage, [(".", repair, repair.read_bytes())], pending, states, rework=False)
        for name in inputs:
            if digest(normalized(file_bytes(stage / name))) != states[name][2]:
                raise ValueError(f"{name}: unexpected final REWORK output")
        if write:
            for name, initial in inputs.items():
                path = checked_path(source_tree, name)
                current = file_bytes(path)
                actual = digest(normalized(current))
                if actual == states[name][2]:
                    continue
                if actual != initial:
                    raise ValueError(f"{name}: input changed during patch application")
                publish(path, file_bytes(stage / name), current)
    print(f"Verified {len(states)} file states; {'updated' if write else 'pending'} {len(inputs)}")
