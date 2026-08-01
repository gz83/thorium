# Thorium infrastructure <img src="https://github.com/Alex313031/thorium/blob/main/logos/NEW/build_light.svg#gh-dark-mode-only" alt="Build Thorium" width="48"> <img src="https://github.com/Alex313031/thorium/blob/main/logos/NEW/build_dark.svg#gh-light-mode-only" alt="Build Thorium" width="48">

This directory contains Thorium development tools, diagnostic configurations,
standalone packaging resources, and supporting metadata. Platform build
instructions are maintained in the
[`docs`](../docs/README.md) directory rather than duplicated here.

## Primary tools

- [`APPIMAGE`](APPIMAGE/README.md) builds and extracts Linux AppImages from a
  Thorium DEB.
- [`DEBUG`](DEBUG/README.md) contains true Debug and Release diagnostic GN
  configurations, `build_debug.py`, and the Thorium UI Debug Shell resources.
- [`portable`](portable/README.md) creates Linux and Windows portable ZIP
  archives from existing release packages.
- [`woa`](woa/README.md) validates a Windows ARM64 mini installer on a native
  GitHub-hosted ARM64 runner, independently of the build host.
- [`build_llvm.py`](build_llvm.py) builds the optimized LLVM/Clang, LLD, and
  Polly toolchain required by Thorium's LLVM optimization patch.

The Python tools require Python 3.11 or newer. Their `--help` output is the
authoritative command-line reference.

## Packaging resources

- [`Arch_Linux`](Arch_Linux/) contains the Arch Linux `PKGBUILD` and associated
  package metadata.
- [`APPIMAGE`](APPIMAGE/README.md) and
  [`portable`](portable/README.md) provide separate post-build packaging
  workflows.

These resources are not all invoked by the repository's main `build.py`
workflow. Review the documentation and current state of the selected packaging
target before using it for a release.

## Build configurations

Maintained release GN configurations are organized by target:

- [`args.gn`](../args.gn): Linux x64;
- [`win_args.gn`](../win_args.gn): Windows x64;
- [`other/Mac`](../other/Mac/): macOS x64 and ARM64;
- [`other/CrOS/cros_args.gn`](../other/CrOS/cros_args.gn):
  ThoriumOS/ChromiumOS;
- [`arm/android`](../arm/android/): Android x86, x64, ARM32, and ARM64;
- [`arm/raspi/raspi_args.gn`](../arm/raspi/raspi_args.gn): Raspberry Pi Linux
  ARM64;
- [`arm/win_ARM_args.gn`](../arm/win_ARM_args.gn): Windows on ARM64;
- [`DEBUG`](DEBUG/README.md): Debug, Release-with-DCHECK, and
  Release-with-symbols configurations.

See [`docs/ABOUT_GN_ARGS.md`](../docs/ABOUT_GN_ARGS.md) for current usage and
policy. Do not combine unrelated platform or SIMD profiles.

The available GN arguments, defaults, and source locations change with
Chromium. Query the configured output directory for the revision being built:

```shell
gn args out/thorium --list
```

Inspect one argument with:

```shell
gn args out/thorium --list=ARGUMENT_NAME
```

## Supporting files

- [`thor_ver`](thor_ver) is the default Windows/profile metadata template.
  [`setup.py`](../setup.py) selects the appropriate variant and copies it into
  the Chromium output directory.
- [`CHROMIUM_LICENSE`](CHROMIUM_LICENSE) records the Chromium BSD-style license
  used by Chromium-derived branding resources.
- [`DEV_CMDLINE_FLAGS.txt`](DEV_CMDLINE_FLAGS.txt) contains development and
  debugging switches. Some deliberately weaken browser security and must not
  be used for normal browsing. See
  [`docs/CMDLINE_FLAGS_LIST.md`](../docs/CMDLINE_FLAGS_LIST.md).
- [`cgpt`](cgpt) is a prebuilt x86-64 Linux ChromeOS GPT utility. Treat it as a
  platform-specific binary and verify its provenance and suitability before
  placing it in `PATH`.

## Standalone component

[`upgrader`](upgrader/) is a nested, standalone Windows upgrader source tree.
It is not currently connected to Thorium's main build or browser updater code
and should not be treated as an enabled product component.

## Related documentation

- [Documentation index](../docs/README.md)
- [Linux build guide](../docs/BUILDING.md)
- [GN argument guide](../docs/ABOUT_GN_ARGS.md)
- [Debugging infrastructure](DEBUG/README.md)
- [Windows on ARM64 smoke testing](woa/README.md)

<img src="https://github.com/Alex313031/thorium/blob/main/logos/NEW/thorium_infra_256.png" alt="Thorium infrastructure" width="200">
