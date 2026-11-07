# macOS application icon generation <img src="https://github.com/Alex313031/thorium/blob/main/logos/NEW/mac/icon_2048px.png" alt="Thorium for macOS" width="48">

Thorium uses Apple's macOS 26 layered icon format. The authoritative layered
application-icon sources are checked in under
[`AppIcon.icon`](../../../../src/chrome/app/theme/chromium/mac/AppIcon.icon/).
The compatibility `app.icns` is generated from the same layers and is not a
separately maintained design.

## Requirements

Generation must run on macOS with:

- Python 3.11 or newer;
- Xcode 26 or newer, including `xcrun`, `actool`, and `iconutil`;
- ImageMagick;
- `rsvg-convert` from librsvg.

Install the Homebrew dependencies with:

```shell
brew install imagemagick librsvg
```

## Generate locally

By default, the script reads `mac_deployment_target` from
`build/config/mac/mac_sdk.gni` in the Chromium checkout selected by `CR_DIR`,
or from `~/chromium/src` when `CR_DIR` is unset:

```shell
CR_DIR=/path/to/chromium/src \
  python3 logos/NEW/mac/gen/build_app_icon.py
```

The Chromium checkout can also be passed explicitly:

```shell
python3 logos/NEW/mac/gen/build_app_icon.py \
  --chromium-src /path/to/chromium/src
```

When no Chromium checkout is available, provide the deployment target
explicitly. The value must match the Chromium branch being packaged:

```shell
python3 logos/NEW/mac/gen/build_app_icon.py \
  --minimum-deployment-target 12.0
```

Run `python3 logos/NEW/mac/gen/build_app_icon.py --help` for the complete
interface.

## Inputs and outputs

Authoritative inputs:

```text
src/chrome/app/theme/chromium/mac/AppIcon.icon/
src/chrome/app/theme/chromium/mac/Assets.xcassets/
logos/NEW/product_logo_256.png
logos/NEW/product_logo_512.png
```

The two product-logo PNGs must remain byte-for-byte identical to the checked-in
`Assets.xcassets/Icon.iconset` document-badge inputs. The generator rejects a
mismatch so Chromium artwork cannot be reintroduced silently.

Generated build resources, which must be reviewed and committed together:

```text
src/chrome/app/theme/chromium/mac/Assets.car
src/chrome/app/theme/chromium/mac/app.icns
```

`Assets.car` provides the layered application icon on macOS 26 and later. Its
`Icon` asset is the Thorium document badge used for associated file types.
`app.icns` remains required by macOS 12–25 and Chromium components that still
consume ICNS resources.

Compatibility PNGs, layer renders, `.new` and `.previous` files, and the lock
and transaction journal are temporary implementation details and must not be
committed. The script publishes `Assets.car` and `app.icns` as one transaction,
rejects concurrent generation, and recovers an interrupted transaction on the
next run.

## Generate with GitHub Actions

Without a Mac, run the
[`Generate macOS app icon`](https://github.com/gz83/thorium-build/actions/workflows/generate-macos-app-icon.yml)
workflow manually in the private orchestration repository. Run its `main`
branch and supply the full reviewed Thorium commit in `thorium_commit`; the
workflow checks out the icon sources from that public-repository commit.

The workflow uses a fixed `MACOSX_DEPLOYMENT_TARGET` because it does not check
out Chromium. Synchronize that value with
`build/config/mac/mac_sdk.gni` whenever the Chromium branch changes.

Download the `thorium-macos-app-icon` artifact. It contains:

```text
Assets.car
app.icns
Thorium.iconset/
DocumentBadge.iconset/
Assets.car.info.json
SHA256SUMS
file-info.txt
tool-versions.txt
```

## Review the artifact

Before publishing the generated resources:

- inspect every size in `Thorium.iconset` for clipping, blur, incorrect
  padding, or layer-composition errors;
- confirm `DocumentBadge.iconset` contains only the transparent Thorium
  roundel, not a complete paper-shaped document icon;
- inspect `Assets.car.info.json` for the expected application-icon and `Icon`
  assets;
- compare `SHA256SUMS`, `file-info.txt`, and `tool-versions.txt` with the
  workflow run;
- copy only `Assets.car` and `app.icns` into
  `src/chrome/app/theme/chromium/mac/` and commit them together with any changed
  source assets.

The diagnostic files and extracted iconsets are review artifacts and are not
Chromium build inputs.

<img src="https://github.com/Alex313031/thorium/blob/main/logos/NEW/mac/apple.png" alt="Apple" width="200">
