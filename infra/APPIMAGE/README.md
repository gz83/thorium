# Thorium AppImage generation <img src="https://raw.githubusercontent.com/Alex313031/Thorium/main/logos/STAGING/Appimage_Logo.svg" alt="AppImage" width="36">

This directory contains the files used to generate a Thorium AppImage on
Linux. The `appimage.py` entry point requires Python 3.11 or newer.

Build dependencies include `dpkg-deb`, `desktop-file-validate`, ImageMagick's
`convert`, `file`, `wget`, and the standard POSIX archive and text-processing
tools required by the vendored `pkg2appimage` script.

## Build

Run `build.py` from the Thorium repository root to produce the Linux DEB. The
package is written to the selected Chromium GN output directory. You can pass
that package directly to the AppImage builder without copying it into this
directory:

```shell
python3 infra/APPIMAGE/appimage.py build \
  /path/to/chromium/src/out/thorium/thorium-browser_VERSION_SSE3.deb
```

Alternatively, place one matching `thorium-browser_*.deb` package in
`infra/APPIMAGE` and let the script detect it:

```shell
cd infra/APPIMAGE
python3 appimage.py build
```

The resulting AppImage is written to `out/` and named after the DEB, for
example `out/Thorium_Browser_VERSION_SSE3.AppImage`.

The automatically selected package must be the only matching DEB in the
directory. When more than one package exists, pass the intended path
explicitly.

The generated AppImage can be run directly. If its executable bit was lost
during copying or downloading, restore it first:

```shell
chmod +x out/Thorium_Browser_*.AppImage
```

Desktop integration tools such as
[AppImageLauncher](https://github.com/TheAssassin/AppImageLauncher) are
optional and are not required to run the AppImage.

## Extract

Extract the sole matching `Thorium*.AppImage` in `out/` with:

```shell
python3 appimage.py extract
```

If more than one matching AppImage exists, pass the intended path explicitly.
Use `--force` to replace an existing `out/Thorium_squashfs-root` directory:

```shell
python3 appimage.py extract out/Thorium_Browser_VERSION_SSE3.AppImage --force
```

## Directory contents

- `files/product_logo_22.png` and `files/product_logo_512.png` provide icon
  sizes not supplied by the packaged payload.
- `files/thorium-shell` wraps `thorium_shell` for use inside the AppImage.
- `Thorium.yml` is the Thorium `pkg2appimage` recipe.
- `out/` contains generated and extracted artifacts.

See [AppImage documentation](https://appimage.org/) for general information.

## About <img src="https://github.com/Alex313031/thorium/blob/main/logos/NEW/thorium_infra_256.png" alt="Thorium infrastructure" width="32">

This infrastructure vendors
[`pkg2appimage`](https://github.com/AppImageCommunity/pkg2appimage/blob/19e30b276ffedf4d3b4b56bc6320f463625a74f8/pkg2appimage)
from [AppImageCommunity/pkg2appimage](https://github.com/AppImageCommunity/pkg2appimage).
The pinned source revision, hash, license, and local-difference status are
recorded in [`README.pkg2appimage`](README.pkg2appimage).

[`Thorium.yml`](https://github.com/Alex313031/thorium/blob/main/infra/APPIMAGE/Thorium.yml)
was modeled after the pinned upstream
[Chromium recipe](https://github.com/AppImageCommunity/pkg2appimage/blob/19e30b276ffedf4d3b4b56bc6320f463625a74f8/recipes/Chromium.yml).
