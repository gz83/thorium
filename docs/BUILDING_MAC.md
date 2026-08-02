# Build Thorium on macOS

This document adds Thorium-specific steps to Chromium's current [macOS build
instructions](https://chromium.googlesource.com/chromium/src/+/main/docs/mac/build_instructions.md).
Use the Xcode and macOS SDK versions required by the Chromium revision being
built rather than a version frozen in this document.

## Requirements

- An Intel or Apple Silicon Mac supported by the selected Chromium revision.
- Xcode command-line tools and the required macOS SDK.
- Git and Python 3.11 or newer.
- A case-sensitive-compatible Chromium checkout path without problematic
  spaces.

The scripts default to `~/thorium`, `~/chromium/src`, and depot_tools found in
`PATH` or `~/depot_tools`. Override them with `THOR_DIR`, `CR_DIR`, and
`DEPOT_TOOLS_DIR`.

## Prepare the checkout

```shell
git clone --recursive https://github.com/Alex313031/thorium.git ~/thorium
cd ~/thorium
python3 get_repo.py
python3 version.py
python3 setup.py --mac
```

Install Xcode and other macOS prerequisites before `get_repo.py`; that helper
does not install them. `version.py` resets Chromium to Thorium's pinned tag and
runs profile-download hooks. `setup.py --mac` applies the common and macOS
Thorium overlays.

The Chromium solution's `.gclient` entry must contain
`"checkout_pgo_profiles": True`. `get_repo.py` sets it automatically. Chromium
hooks download both Intel and Apple Silicon macOS PGO profiles so either target
can be configured from the checkout.

## Configure GN

```shell
cd "$CR_DIR"
gn args out/thorium
```

Use:

- [`other/Mac/mac_args.gn`](../other/Mac/mac_args.gn) for Intel x64;
- [`other/Mac/mac_ARM_args.gn`](../other/Mac/mac_ARM_args.gn) for Apple Silicon
  ARM64.

Confirm the selected target before building:

```shell
gn args out/thorium --list
gn ls out/thorium
```

## Build and package

From the Thorium checkout, use the expected CPU matching the selected args:

```shell
python3 build.py --expect-os mac --expect-cpu arm64
# Or, for Intel:
python3 build.py --expect-os mac --expect-cpu x64
```

The browser is produced as `out/thorium/Thorium.app`. After a successful build,
create an ad-hoc-signed DMG on macOS with:

```shell
python3 create_dmg.py
```

To package `Chromium.app` instead, use `python3 create_dmg.py --product
chromium`. The script is macOS-only and uses Chromium's `pkg-dmg` tool.

### Package a Linux-built application on GitHub Actions

When cross-building the application on Linux, preserve its executable modes and
symbolic links in a tar archive:

```shell
tar -C "$CR_DIR/out/thorium" -czf Thorium.app.tar.gz Thorium.app
```

Upload `Thorium.app.tar.gz` to a draft release, then manually run
[`Package macOS DMG`](../.github/workflows/package-macos-dmg.yml). Supply the
same release tag, the exact archive filename, the Chromium tag or commit used
for the build, and the application's target architecture. The workflow obtains
the matching Chromium `pkg-dmg`, validates the Mach-O architecture, invokes
`create_dmg.py` on a macOS runner, and publishes the DMG and its SHA-256 file.

The runner architecture does not have to match the application architecture;
it performs packaging and ad-hoc signing rather than compilation. This process
does not provide Developer ID signing or Apple notarization.

Thorium's macOS 26 icon pipeline is maintained under
[`logos/NEW/mac/gen`](../logos/NEW/mac/gen). Generated `Assets.car` and
`app.icns` are repository resources; follow that directory's README when they
need regeneration.

## Development

Run a built browser directly with:

```shell
"$CR_DIR/out/thorium/Thorium.app/Contents/MacOS/Thorium"
```

Current Chromium debugging guidance is available in its [macOS debugging
document](https://chromium.googlesource.com/chromium/src/+/main/docs/mac/debugging.md).
Use `build.py --target TARGET` for individual targets.
