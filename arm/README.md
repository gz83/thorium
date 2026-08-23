# Thorium ARM and Android Builds <img src="https://github.com/Alex313031/thorium/blob/main/logos/STAGING/arm_logo.png" alt="ARM" width="128">

This directory contains build argument files for Android ARM32, ARM64, x86,
and x64, Raspberry Pi ARM64, and Windows on ARM64. ARM ABI selection remains
owned by Chromium's central build configuration; these files select the target
and applicable product settings.

- Android builds: see [`android/README.md`](android/README.md) and select the
  argument file for the intended architecture.
- Windows on ARM64 builds: use [`win_ARM_args.gn`](win_ARM_args.gn) as the
  basis for `args.gn`. The patch series automatically selects the compatible
  V8 snapshot toolchain when this target is cross-built on Linux x64; no
  host-specific override belongs in the args file.
- macOS ARM64 argument files are located in [`other/Mac`](../other/Mac).

## Prepare the source tree

Before synchronization, make sure `.gclient` includes every platform you plan
to build. Android requires `"android"` and Windows on ARM requires `"win"` in
`target_os`. For example:

```python
target_os = ["linux", "win", "android"]
```

Builds that consume Chromium optimization profiles, including Android and
Windows on ARM64, also require the Chromium solution's `custom_vars` to
contain `checkout_pgo_profiles=True`. Add it to the existing `src` solution,
for example:

```python
solutions = [
    {
        "name": "src",
        # Keep the checkout's existing URL, dependencies, and other fields.
        "custom_vars": {
            "checkout_pgo_profiles": True,
        },
    },
]
```

`get_repo.py` enables `checkout_pgo_profiles` automatically. Users who created
or maintain a Chromium checkout manually must add it themselves. Changing
`target_os` requires a full `gclient sync`; changing only
`checkout_pgo_profiles` on an otherwise complete checkout requires at least
`gclient runhooks`. Running `version.py` after either change performs the
required sync and hooks.

The Raspberry Pi configuration currently uses neither full PGO nor Android
AFDO, so it does not itself require `checkout_pgo_profiles`. Keeping the option
enabled is harmless and lets the same checkout support other Thorium targets.

Then run the following commands from the Thorium checkout in this order:

```shell
python3 version.py
python3 setup.py --raspi  # Raspberry Pi ARM64
# Or use: python3 setup.py --woa
# Or use: python3 setup.py --android
```

`version.py` selects the Chromium revision and runs Chromium's hooks. Select
the platform profile with `setup.py`; run `python3 setup.py --help` for all
available profiles.

The `--arm64` setup option is retained as an alias for `--raspi`; it does not
select an arbitrary ARM64 platform.

The setup step applies Thorium's patch series and copies profile-specific
resources, so it must run after `version.py` has selected and synchronized the
Chromium revision.

Additional checkout maintenance commands include:

```shell
git fetch --tags
git rebase-update
gclient runhooks
git show-ref
```

Destructive synchronization commands are documented in the main [building
guide](../docs/BUILDING.md#maintenance-and-cleanup).

## Configure and build

After preparation, change to the Chromium `src` directory and create or edit
the output configuration:

```shell
gn args out/thorium
gn ls out/thorium
```

Use [`raspi/raspi_args.gn`](raspi/raspi_args.gn) for Raspberry Pi ARM64,
[`win_ARM_args.gn`](win_ARM_args.gn) for Windows on ARM64, or the appropriate
file documented in [`android/README.md`](android/README.md) for Android.

Run the repository's unified build entry point from the Thorium checkout. The
expected OS and CPU checks prevent accidentally building a differently
configured output directory:

```shell
cd /path/to/thorium

# Raspberry Pi ARM64
python3 build.py --expect-os linux --expect-cpu arm64

# Windows on ARM64
python3 build.py --expect-os win --expect-cpu arm64

# Android examples; replace the CPU with arm, arm64, x86, or x64 as needed
python3 build.py --expect-os android --expect-cpu arm64
```

## Raspberry Pi Builds &nbsp;<img src="https://github.com/Alex313031/thorium/blob/main/logos/STAGING/Raspberry_Pi_Logo.svg" alt="Raspberry Pi" width="28">

Thorium Raspberry Pi builds support ARM64 operating systems. Consult the
[Thorium Raspi repository](https://github.com/Alex313031/Thorium-Raspi) for the
device and operating-system support of a particular release. See Raspberry
Pi's [64-bit OS announcement](https://www.raspberrypi.com/news/raspberry-pi-os-64-bit/)
for additional background.
