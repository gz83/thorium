# Thorium documentation &nbsp;<img src="https://raw.githubusercontent.com/Alex313031/Thorium/main/logos/NEW/patches.png" alt="Thorium patches" width="32">

The repository documentation describes Thorium's current Python build tools,
release variants, patches, and user-visible behavior. Chromium prerequisites
and toolchain versions change frequently; platform guides therefore link to
the corresponding upstream documentation instead of freezing tool versions.

## Building

- [Linux build guide](BUILDING.md)
- [Windows build guide](BUILDING_WIN.md)
- [macOS build guide](BUILDING_MAC.md)
- [Cross-compile Windows on Linux](BUILDING_WIN_CROSS.md)
- [ARM and Android builds](../arm/README.md)
- [GN arguments used by Thorium](ABOUT_GN_ARGS.md)
- [Private Actions orchestration](https://github.com/gz83/thorium-build)

GitHub Actions workflows are maintained in the private `gz83/thorium-build`
repository. They check out a reviewed Thorium commit from this repository;
source files and build scripts are not mirrored into the orchestration repo.
Access to its workflows and logs requires permission to that private repository.

All repository Python entry points require Python 3.11 or newer. Run each
script with `--help` for its authoritative options.

## Users and releases

- [Release and SIMD variant guide](ABOUT_RELEASES.md)
- [Frequently asked questions](FAQ.md)
- [Thorium 2024 UI](TH24.md)
- [Command-line switch references](CMDLINE_FLAGS_LIST.md)
- [GitHub releases](https://github.com/Alex313031/thorium/releases)

## Maintenance

- [Patch inventory](PATCHES.md)
- [Rebasing workflow](REBASING.md)
- [Chromium source code search](https://source.chromium.org/chromium/chromium/src)

Report current bugs and feature requests through the [Thorium issue
tracker](https://github.com/Alex313031/thorium/issues).
