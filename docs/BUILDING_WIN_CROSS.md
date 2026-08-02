# Cross-compile Thorium for Windows on Linux

<img src="https://github.com/Alex313031/thorium/blob/main/logos/NEW/build_light.svg#gh-dark-mode-only" alt="Build Thorium" width="48"> <img src="https://github.com/Alex313031/thorium/blob/main/logos/NEW/build_dark.svg#gh-light-mode-only" alt="Build Thorium" width="48">

This workflow targets Windows from a Linux Chromium checkout. It depends on a
compatible Microsoft toolchain archive and may not support every Chromium test,
Crashpad, assembler, signing, or installer workflow available on a native
Windows host. Consult Chromium's current Windows cross-build implementation
before relying on a particular target.

## Prerequisites

Prepare Linux as described in the [Linux build guide](BUILDING.md). In the
Chromium checkout's `.gclient`, include Windows dependencies and profile data:

```python
solutions = [
  {
    "name": "src",
    "url": "https://chromium.googlesource.com/chromium.git",
    "managed": False,
    "custom_deps": {},
    "custom_vars": {
      "checkout_pgo_profiles": True
    },
  },
]

target_os = [ "linux", "win" ]
```

Changing `target_os` requires a full `gclient sync`; `gclient runhooks` alone
cannot add all Windows dependencies. `get_repo.py` manages
`checkout_pgo_profiles`, while `version.py` subsequently performs the forced
sync and hooks.

## Microsoft toolchain archive

Cross-building requires an MSVS artifacts archive matching Chromium's expected
toolchain hash. Thorium publishes prepared **VS Artifacts Archive for Thorium
Cross Building** releases in the
[Alex313031/Snippets release page](https://github.com/Alex313031/Snippets/releases).
Choose the release whose documented MSVS, Windows SDK, and archive hash match
the checked-out Chromium revision. Do not assume that the newest archive is
compatible with an older Thorium branch.

If no matching Thorium archive is available, generate one on a properly
configured Windows system using the depot_tools scripts corresponding to the
Chromium revision.

Point depot_tools at the archive location using the variables expected by
Chromium's `build/vs_toolchain.py`, commonly including:

```shell
export DEPOT_TOOLS_WIN_TOOLCHAIN=1
export DEPOT_TOOLS_WIN_TOOLCHAIN_BASE_URL=/absolute/path/to/archive-directory
export GYP_MSVS_HASH_<toolchain_hash>=<archive_name_without_zip>
```

The exact hash is defined by the checked-out Chromium revision. Run `gclient
runhooks` after setting the variables and resolve toolchain errors before GN
generation.

## Prepare and configure

From the Thorium checkout:

```shell
python3 version.py
python3 setup.py
```

For Windows ARM64 or a SIMD variant, use the matching setup profile instead.
Then configure Chromium with the matching args file:

```shell
cd "$CR_DIR"
gn args out/thorium
```

Use [`win_args.gn`](../win_args.gn) for x64, an appropriate file under
`other/` for SIMD variants, or [`arm/win_ARM_args.gn`](../arm/win_ARM_args.gn)
for Windows ARM64. Thorium's V8 patch automatically selects the Linux x64
ARM64 simulator snapshot toolchain for the latter; do not add host-specific
V8 overrides to `args.gn`.

## Build

Return to Thorium and validate the generated target:

```shell
cd "$THOR_DIR"
python3 build.py --dry-run --expect-os win --expect-cpu x64
python3 build.py --expect-os win --expect-cpu x64
```

Use `arm64` or `x86` when the selected args require it. A successful compile
does not imply that Windows signing, crash reporting, every test target, or all
installer behavior has been validated; test produced artifacts on the target
Windows architecture before publishing them.

<img src="https://github.com/Alex313031/thorium/blob/main/logos/STAGING/Thorium90_504.jpg" alt="Thorium 90" width="200">
