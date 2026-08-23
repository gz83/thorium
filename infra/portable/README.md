# Thorium portable packaging

`portable.py` creates portable ZIP archives from a Thorium Linux `.deb` package
or Windows mini installer. It requires Python 3.11 or newer.

## Linux

Install `dpkg-deb`, then run from the Thorium repository root:

```shell
python3 infra/portable/portable.py \
  --platform linux \
  --input /path/to/thorium-browser.deb
```

The input must be a `thorium-browser` Debian package containing the expected
`opt/chromium.org/thorium` payload and executable `thorium` and
`thorium_shell` files. The packager rejects broken links, links that escape the
payload, and unsupported special files.

The generated archive contains portable Bash wrapper launchers whose executable
bits and package-relative symbolic links are stored in the ZIP. Linux packaging
requires `dpkg-deb`. Extract the result with a tool that preserves Unix symbolic
links, such as:

```shell
unzip thorium-browser_VERSION_VARIANT.zip
```

`THORIUM-PORTABLE` supports `--temp-profile` and `--safe-mode`, and reads
additional browser flags from `.config/thorium-flags.conf`. It also removes
pending crash files older than 30 days when the normal portable profile starts.
`THORIUM-SHELL` launches the bundled Thorium Content Shell for web-platform
testing and diagnostics, using a separate profile and cache. The generated
archive includes these details in `README.txt`.

## Windows

Install [7-Zip](https://www.7-zip.org/). The packager searches `PATH` and the
standard 64-bit and 32-bit Windows installation directories. If it cannot find
7-Zip automatically, pass its location explicitly:

```powershell
py -3.11 infra/portable/portable.py `
  --platform windows `
  --input C:\path\to\thorium_AVX2_mini_installer.exe `
  --seven-zip "C:\Program Files\7-Zip\7z.exe"
```

The input must be a Thorium mini installer containing one `chrome.7z`, one
version directory, `thorium.exe`, and one `thorium_shell.exe`. The packager
validates this layout before publishing the archive. The resulting ZIP includes
`THORIUM.BAT`, `THORIUM_SHELL.BAT`, and a platform-specific `README.txt`.

## Output and validation

The platform can normally be inferred from `.deb` or `.exe`, so `--platform`
is optional. Use `--output PATH` to choose the archive name and `--force` to
replace an existing archive. If a renamed x64 package no longer contains its
SIMD profile in the filename, pass `--profile NAME` to retain that profile in
the output archive name. Use `--expected-version VERSION` in release automation
to reject an unexpected package version.

Default output names are:

```text
thorium-browser_VERSION_VARIANT.zip  # Linux
Thorium_[WIN32_]PROFILE_VERSION.zip  # Windows
```

These names follow the release asset convention. Linux x64 variants use their
SIMD profile (`AVX`, `AVX2`, `AVX512`, `SSE3`, or `SSE4`), while Linux ARM64
and 32-bit x86 archives use `arm64` and `i386`. Windows uses the profile spelling
in the installer filename and reads the payload executable's PE machine field;
32-bit x86 archives receive the `WIN32_` prefix. Windows SSE2 is supported as a
32-bit compatibility profile. If a profile cannot be inferred and no
`--profile` is supplied, the packager fails instead of publishing a
non-standard fallback name.

Packaging takes place in an isolated temporary directory. The input package is
never modified, and the final ZIP replaces its destination only after it has
been written successfully. A same-directory lock prevents concurrent packaging
processes from writing the same output. Locks left by a process that no longer
exists are recovered automatically.

## Security and portability

Portable packaging makes the profile and package directory movable; it does
not change binary compatibility. The archive must still run on its target
operating system, CPU architecture, and Thorium SIMD profile, and may retain
platform runtime requirements.

The browser launchers pass `--disable-encryption` and `--disable-machine-id` so
the profile can move between machines. This weakens protection for cookies,
passwords, and other profile data. Treat the extracted directory as sensitive
and do not use this mode when OS-bound credential protection is preferred.

Linux `.desktop` files are included as `.desktop.example` templates. Replace
every `@PORTABLE_ROOT@` placeholder with the absolute extracted directory
before installing them into `~/.local/share/applications`. Install the browser
template as `thorium-portable.desktop` so its desktop identity matches the
launcher. Executable paths are quoted so ordinary spaces are supported; paths
containing desktop-entry escape characters such as `"`, `` ` ``, `$`, or `\\`
require specification-compliant escaping.
