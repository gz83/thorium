# Build Thorium on Windows

<img src="https://github.com/Alex313031/thorium/blob/main/logos/NEW/build_light.svg#gh-dark-mode-only" alt="Build Thorium" width="48"> <img src="https://github.com/Alex313031/thorium/blob/main/logos/NEW/build_dark.svg#gh-light-mode-only" alt="Build Thorium" width="48">

Follow Chromium's current [Windows build
instructions](https://chromium.googlesource.com/chromium/src/+/main/docs/windows_build_instructions.md)
for supported Windows, Visual Studio, SDK, and toolchain versions. These
requirements change with Chromium and are intentionally not duplicated here.

## Requirements and paths

- A 64-bit Windows installation supported by the selected Chromium revision.
- Visual Studio and the Windows SDK required by Chromium.
- Git and Python 3.11 or newer (`py -3.11`).
- An NTFS checkout with sufficient memory and disk space.

Default script paths are:

```text
Thorium:     C:\Users\<user>\thorium
Chromium:    C:\src\chromium\src
depot_tools: PATH lookup, then C:\src\depot_tools
```

Use `THOR_DIR`, `CR_DIR`, and `DEPOT_TOOLS_DIR` or the scripts' explicit path
options to override them. Add depot_tools to `PATH` and follow Chromium's
Windows environment-variable requirements.

## Prepare the checkout

Clone Thorium and run the cross-platform bootstrap:

```powershell
git clone --recursive https://github.com/Alex313031/thorium.git "$HOME\thorium"
cd "$HOME\thorium"
py -3.11 get_repo.py
py -3.11 version.py
py -3.11 setup.py
```

Install Visual Studio and the SDK before running the bootstrap. `version.py`
force-checks out Thorium's pinned Chromium tag, removes untracked Chromium
files, synchronizes dependencies, and runs hooks. `setup.py` applies Thorium's
overlays, patches, and translations.

For a SIMD or ARM64 variant, select exactly one setup profile:

```powershell
py -3.11 setup.py --avx2
py -3.11 setup.py --sse3
py -3.11 setup.py --sse2
py -3.11 setup.py --woa
```

See `py -3.11 setup.py --help` and the [SIMD release guide](ABOUT_RELEASES.md).

For the M159 Windows x86/x64 compatibility port, add `--windows-legacy` to
the selected desktop setup command. The [REWORK series guide](../other/rework-windows/README.md)
covers the pinned donor release, exclusions and static checks.

## Configure GN

From Chromium `src`:

```powershell
gn args out\thorium
```

Use [`win_args.gn`](../win_args.gn) for the normal Windows build or the file
matching the selected profile under `other/` or `arm/`. Profile-specific setup
and args must agree. Inspect the generated configuration with:

```powershell
gn args out\thorium --list
gn ls out\thorium
```

## Build and install

Run from the Thorium checkout:

```powershell
py -3.11 build.py --expect-os win --expect-cpu x64
```

For Windows ARM64, replace `x64` with `arm64`; for 32-bit variants use `x86`.
The default Windows build uses separate browser and installer phases. The
profile-named mini installer and related symbols are written under
`out\thorium`.

When an installer target is selected, `build.py` checks the prepared
translations before starting the first build phase. This also runs with
`--dry-run`, including explicit `setup.exe` and mini installer targets. For a
regular or REWORK checkout it verifies installer resource exports and their
translations. REWORK builds also check nine Windows messages, their
placeholders and language pack filenames, and XP font resources.

Useful validation and development forms are:

```powershell
py -3.11 build.py --dry-run --expect-os win --expect-cpu x64
py -3.11 build.py --no-installer --expect-os win --expect-cpu x64
py -3.11 build.py --target thorium_all
```

Run the unpacked browser as `out\thorium\thorium.exe`, or run the generated
profile-named mini installer.

## Updating and cleanup

Update the Thorium Git checkout normally, then rerun `version.py`, the selected
`setup.py` profile, and GN generation as needed. `trunk.py` and `clean.py` are
destructive maintenance tools; inspect their `--help` output and preserve local
work before using them.

Debug configurations and packaging guidance live in
[`infra/DEBUG`](../infra/DEBUG). Use `build.py --target TARGET` for individual
test or development targets.

<img src="https://github.com/Alex313031/thorium/blob/main/logos/STAGING/Thorium90_504.jpg" alt="Thorium 90" width="200">
