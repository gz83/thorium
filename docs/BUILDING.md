# Build Thorium on Linux

<img src="https://github.com/Alex313031/thorium/blob/main/logos/NEW/build_light.svg#gh-dark-mode-only" alt="Build Thorium" width="48"> <img src="https://github.com/Alex313031/thorium/blob/main/logos/NEW/build_dark.svg#gh-light-mode-only" alt="Build Thorium" width="48">

This guide covers the repository's supported Linux workflow. See the
[Windows](BUILDING_WIN.md), [macOS](BUILDING_MAC.md), [Windows cross-build](BUILDING_WIN_CROSS.md),
and [ARM/Android](../arm/README.md) guides for other targets.

## Requirements

- A 64-bit Linux host with enough memory and disk space for a Chromium build.
- Git and Python 3.11 or newer.
- A supported Chromium build distribution and its build dependencies.

Chromium's current requirements are authoritative:

- [Linux build instructions](https://chromium.googlesource.com/chromium/src/+/main/docs/linux/build_instructions.md)
- [Linux build dependencies](https://chromium.googlesource.com/chromium/src/+/main/build/install-build-deps.py)

Large builds may require a higher open-file limit. Inspect it with `ulimit -Sn`
and `ulimit -Hn`; raise it only within limits allowed by the host.

## Paths and environment

By default the Python tools use:

```text
Thorium:     ~/thorium
Chromium:    ~/chromium/src
depot_tools: PATH lookup, then ~/depot_tools
Output:      ~/chromium/src/out/thorium
```

Override these defaults when needed:

```shell
export THOR_DIR=/path/to/thorium
export CR_DIR=/path/to/chromium/src
export DEPOT_TOOLS_DIR=/path/to/depot_tools
export PATH="$PATH:$DEPOT_TOOLS_DIR"
```

Use absolute paths. The scripts also accept explicit path options shown by
`--help`.

## Create or validate the checkout

Clone Thorium, then run its bootstrap helper:

```shell
git clone --recursive https://github.com/Alex313031/thorium.git ~/thorium
cd ~/thorium
python3 get_repo.py
```

On Debian-derived Linux systems, `get_repo.py` can install Chromium build
dependencies through `sudo`. Pass `--skip-build-deps` to manage them yourself.
It also creates or validates the Chromium checkout, prepares depot_tools, and
enables `checkout_pgo_profiles` in the Chromium solution's `.gclient` entry.

Review `python3 get_repo.py --help` before using `--sync-existing` or
`--recover-incomplete`; recovery may reset checkout state.

## Select the Thorium revision

From the Thorium checkout:

```shell
python3 version.py
python3 setup.py
```

`version.py` force-checks out the Chromium tag pinned by Thorium, removes
untracked files from Chromium, synchronizes dependencies, and runs hooks.
Before synchronization, both `version.py` and `trunk.py` quit unfinished Git
rebases and detach dependency checkouts so switching between release and trunk
revisions does not rebase local branches. Local branch refs are retained;
unfinished rebase state and tracked edits are discarded.
`setup.py` then copies Thorium overlays, applies the ordered patch series, and
merges GRD/XTB translations. Do not run either command over Chromium work you
need to preserve.

Use a platform or SIMD setup profile when appropriate:

```shell
python3 setup.py --avx2
python3 setup.py --raspi
python3 setup.py --android
python3 setup.py --cros
```

Run `python3 setup.py --help` for the full profile list. SIMD compatibility is
documented in [the release guide](ABOUT_RELEASES.md).

Repeating `setup.py` with the same profile is supported. Before switching to a
different profile, run `version.py` to restore the pinned clean Chromium tree;
this is required in particular for profiles that select conditional patches,
such as `--raspi`, `--woa`, and `--sse2`. The setup ownership manifest can
clean files copied by an earlier run, but it intentionally does not attempt to
reverse an already applied conditional patch series.

## Configure GN

Change to Chromium and create the output directory:

```shell
cd "$CR_DIR"
gn args out/thorium
```

Start with [`args.gn`](../args.gn), or use the matching platform/variant file
under `other/`, `arm/`, or `infra/DEBUG/`. Do not combine unrelated profiles.
Inspect the effective configuration with:

```shell
gn args out/thorium --list
gn ls out/thorium
```

See [Thorium GN arguments](ABOUT_GN_ARGS.md) for project-specific policy.

## Build

Run the unified build entry point from Thorium:

```shell
cd "$THOR_DIR"
python3 build.py --expect-os linux --expect-cpu x64
```

Linux builds run separate phases for `thorium_all`, the DEB package, and the
RPM package. Separate phases intentionally reduce the chance that one packaging
failure hides another target's result. Useful alternatives include:

```shell
python3 build.py --dry-run --expect-os linux --expect-cpu x64
python3 build.py --no-installer --expect-os linux --expect-cpu x64
python3 build.py --target thorium_all
python3 build.py -j 16
```

The packages and build products are written under `out/thorium`.

## Maintenance and cleanup

`trunk.py` resets Chromium to upstream tip-of-tree, deletes untracked files,
synchronizes dependencies, and runs hooks. It is a destructive maintenance
tool, not a required step before every release build:

```shell
python3 trunk.py
```

`version.py` should be run afterward to return to Thorium's pinned Chromium
revision. To preview or perform cleanup of `out/thorium` and downloaded PGO
profiles:

```shell
python3 clean.py --dry-run
python3 clean.py
```

Both operations can destroy local work or build output. Commit or back up
anything important first.

For an individual Ninja target, use `build.py --target LABEL`; direct
`autoninja -C out/thorium LABEL` remains available for advanced development.

<img src="https://github.com/Alex313031/thorium/blob/main/logos/STAGING/Thorium90_504.jpg" alt="Thorium 90" width="200">
