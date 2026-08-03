# Thorium Shell <img src="https://raw.githubusercontent.com/Alex313031/Thorium/main/logos/STAGING/content_shell_app_icon_192.png" width="64" alt="Thorium Shell icon">

Thorium Shell is Thorium's branded build of Chromium `content_shell`. It is a
minimal harness around Chromium's Content and Blink layers, intended primarily
for web-platform tests, renderer debugging, and focused development work. It
is not a replacement for the full Thorium browser or Android WebView and does
not provide Thorium's complete browser UI, profile features, or product
integration.

See Chromium's documentation for
[running web tests in Content Shell](https://chromium.googlesource.com/chromium/src/+/main/docs/testing/web_tests_in_content_shell.md)
and the broader
[web-test infrastructure](https://chromium.googlesource.com/chromium/src/+/main/docs/testing/web_tests.md).

## Repository integration

The root-level [`setup.py`](../setup.py) copies this directory into Chromium's
`out/thorium` staging directory. The
[`thorium-content-shell-branding.patch`](../other/thorium-content-shell-branding.patch)
owns the Chromium GN target rename, product name, executable or app-bundle
branding, platform icons, logging name, and Android package output name.

Platform packaging is owned separately:

- [`thorium-linux-installer-packaging.patch`](../other/thorium-linux-installer-packaging.patch)
  installs the Linux executable, launcher, desktop entry, and icon;
- [`mini_installer.patch`](../other/mini_installer.patch) includes the Windows
  executable and icon in the installed version directory;
- [`infra/portable`](../infra/portable/) provides Linux and Windows portable
  launchers;
- [`infra/APPIMAGE`](../infra/APPIMAGE/) provides the AppImage launcher.

The files in this directory are therefore active packaging inputs rather than
standalone copies of Chromium `content_shell` source files.

## Build

After configuring `out/thorium`, build only the branded shell with Thorium's
cross-platform build entry point:

```shell
python3 build.py --target thorium_shell
```

On Windows PowerShell, use the repository's Python 3.11 baseline explicitly:

```powershell
py -3.11 build.py --target thorium_shell
```

Run these commands from the Thorium repository root. You may pass
`--chromium-src`, `--out-dir`, and the other options documented by
`python3 build.py --help` when using non-default paths.

On Android, Thorium's normal build flow directly builds the upstream
`content_shell_apk` target; the branding patch changes its produced APK name to
`Thorium_Shell_<architecture>.apk`. The `thorium_shell` GN group also depends
on that APK. The suffix is `arm32`, `arm64`, `x86`, or `x64`, matching the
selected Android output configuration.

Expected branded products are:

| Platform | Product |
|---|---|
| Linux | `thorium_shell`, with the packaged `thorium-shell` launcher |
| Windows | `thorium_shell.exe` |
| macOS | `Thorium Shell.app` |
| Android | `Thorium_Shell_arm32.apk`, `Thorium_Shell_arm64.apk`, `Thorium_Shell_x86.apk`, or `Thorium_Shell_x64.apk` |

## Run

On a packaged Linux installation, run:

```shell
thorium-shell [arguments]
```

The Linux desktop entry also exposes an **Open Thorium Shell** action. This
desktop action is Linux-specific and should not be expected on Windows,
macOS, or Android.

For an unpackaged build, launch the product directly from the generated output
directory. Windows installers place `thorium_shell.exe` below Thorium's
versioned application directory, so scripts should not assume that it resides
directly in the top-level `Application` directory. The Windows portable bundle
provides `THORIUM_SHELL.cmd`, which resolves the versioned executable for the
user.

Thorium does not make a compatibility guarantee for driving Thorium Shell with
ChromeDriver, Puppeteer, or other browser-automation front ends. Use Chromium's
current Content Shell and web-test tooling when automation behavior matters.

## Screenshot

<img src="https://raw.githubusercontent.com/Alex313031/thorium/main/logos/STAGING/thorium_shell_screenshot.png" width="500" alt="Thorium Shell window">
