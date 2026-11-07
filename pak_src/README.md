# Thorium PAK Customizer

<img src="https://github.com/Alex313031/thorium/blob/main/logos/STAGING/pak.png" alt="Thorium PAK Customizer">

This directory vendors the Rust 3.x implementation of
[chrome-pak-customizer](https://github.com/myfreeer/chrome-pak-customizer) and
contains the prebuilt command-line tools bundled with Thorium Linux and
Windows products.
The pinned upstream revision and Thorium-specific integration details are
recorded in [`README.chromium`](README.chromium).

The tool unpacks and repacks Chromium PAK v4 and v5 files. It also supports
Brotli-compressed resources and the Microsoft Edge v5 resource-ID variant.
Compatibility is determined by the PAK format rather than the Chromium release
number, so the tool also applies to newer Chromium and Thorium releases that
continue to use these supported formats. A future incompatible PAK format
would require a corresponding tool update.

## Requirements

- Python 3.11 or newer
- Rust and Cargo (the source MSRV is Rust 1.59; reproducible CI builds use the
  repository-pinned Rust 1.85.0 toolchain)
- The Rust target and native or cross-linker required by the selected platform

All Cargo operations use the checked-in lock file.

## Build

Build for the current Rust host target:

```bash
python3 pak_src/build.py build
```

Build a release target explicitly:

```bash
python3 pak_src/build.py build --target x86_64-unknown-linux-musl
```

Supported release targets are:

```text
x86_64-unknown-linux-musl
aarch64-unknown-linux-musl
x86_64-pc-windows-msvc
i686-pc-windows-msvc
x86_64-apple-darwin
aarch64-apple-darwin
```

GNU Linux host targets are also accepted for local compilation and testing,
but are not published into `binaries/`; Thorium's Linux prebuilts use musl to
avoid a dependency on the build host's glibc version.

## Use

Unpack a PAK file into a directory:

```shell
pak -u input.pak output_directory
```

Repack the generated `pak_index.ini` into a PAK file:

```shell
pak -p output_directory/pak_index.ini output.pak
```

The remaining options are:

```text
-e  Force the undocumented Microsoft Edge v5 format
-m  Use memory-mapped input while unpacking when supported
-v  Print version information
-c  Print the Chromium ASCII art
-h  Print command-line help
```

Existing destination files are overwritten. The Windows
[`pack.bat`](binaries/pak-win/pack.bat) and
[`unpack.bat`](binaries/pak-win/unpack.bat) wrappers instead publish through
temporary paths and refuse to overwrite an existing unpacked directory.

## Test

Run the upstream Rust unit tests:

```bash
python3 pak_src/build.py test
```

Add one or more real Chromium/Thorium PAK files to perform byte-for-byte
round-trip checks:

```bash
python3 pak_src/build.py test \
  --fixture /path/to/resources.pak \
  --fixture /path/to/chrome_100_percent.pak
```

Fixtures are never downloaded automatically. If no explicit fixtures are
provided, the script uses `pak_src/tests/*.pak` when that directory exists.

## Publish Thorium prebuilts

`package` builds one target and atomically replaces its existing Thorium
integration binary together with `binaries/SHA256SUMS`:

```bash
python3 pak_src/build.py package --target x86_64-unknown-linux-musl
python3 pak_src/build.py package --target aarch64-unknown-linux-musl
python3 pak_src/build.py package --target x86_64-pc-windows-msvc
python3 pak_src/build.py package --target i686-pc-windows-msvc
```

For a release binary already built by an external cross-compilation command,
pass its explicit path with `--source`. The script verifies that its ELF or PE
architecture matches the requested target before publishing it. macOS targets
are build-only because Thorium does not currently bundle this utility in its
macOS application.

Publishing uses `binaries/.pak-build.lock/` to prevent concurrent processes
from replacing a binary and the shared checksum manifest at the same time. An
unclean process termination can leave this lock behind. Inspect its
`owner.txt`, confirm that the recorded process is no longer running on the
recorded host, and only then remove the lock directory manually. The script
never deletes an unknown stale lock automatically.

Published filenames match the names consumed by Thorium's `setup.py` and
Windows installer integration:

```text
binaries/pak
binaries/pak_arm64
binaries/pak-win/pak_mingw32.exe
binaries/pak-win/pak_mingw64.exe
```

The Windows directory also contains `pack.bat` and `unpack.bat`. They select
the appropriate x86 or x64 executable and provide drag-and-drop wrappers for
packing `pak_index.ini` or unpacking a PAK file. Their exit codes are suitable
for command-line automation as well as interactive use.

The Windows executable names are retained for compatibility with Thorium's
setup and installer integration. The 3.x source implementation is validated
against real Chromium PAK v4, v5, Brotli-era, and Microsoft Edge v5 fixtures.
Each generated platform binary also performs a byte-identical v4 fixture
round trip before it is published by CI.

Verify the four checked-in binaries against the checksum manifest on a system
with GNU `sha256sum`:

```shell
cd pak_src/binaries
sha256sum --check SHA256SUMS
```

### GitHub Actions

Maintainers who do not want to install cross-compilation toolchains locally
can run the manual
[`Build PAK 3.x binaries`](https://github.com/gz83/thorium-build/actions/workflows/build-pak-binaries.yml)
workflow in the private orchestration repository, supplying the reviewed
Thorium source commit. It validates pinned PAK fixtures, builds all four bundled targets in
their appropriate hosted environments, and performs a byte-identical PAK
round trip with each generated binary. It uploads `thorium-pak-3x-binaries`
containing the binaries,
`SHA256SUMS`, file-type information, and per-platform toolchain records. Use
the included `thorium-pak-3x-binaries.tar.xz` when transferring the Linux
binaries because GitHub's expanded artifact view does not preserve executable
permission bits. The workflow creates this archive with normalized metadata,
then extracts it and verifies its exact contents, checksums, and Linux execute
permissions before upload. It never commits binaries or creates a GitHub
Release automatically.

## Clean

```bash
python3 pak_src/build.py clean
```

This command removes only `pak_src/target/`.

## Bundling

`setup.py` copies the appropriate Linux binary and the Windows helper files to
Chromium's `out/thorium` directory. The Windows mini installer then includes
the two Windows executables. Android builds do not bundle the PAK utility.

The same setup step copies this directory's canonical
[`README.chromium`](README.chromium), [`LICENSE`](LICENSE), and
[`OWNERS`](OWNERS) files to Chromium's `third_party/pak` directory for
third-party metadata and license processing.

The vendored Rust 3.x source and its prebuilt binaries are covered by the MIT
license in `LICENSE`.
