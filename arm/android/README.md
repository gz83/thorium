# Android `args.gn` files

`debug_args.gn` targets ARM64. Use the other argument files as references when
creating an x86, x64, or ARM32 debug configuration; do not duplicate Chromium's
ARM ABI or microarchitecture settings in these files.

`android_full_debug = true` can be used for a more complete debug build.

`chromium_x64_release_args.gn` is a Chromium-branded x64 release reference
configuration. It is separate from Thorium's architecture-specific release
configurations and still enables selected media and build options.

API keys enable location-related features but do not provide desktop-style
Google Sync in Android Chromium because access is subject to additional Google
service restrictions.

## Checkout prerequisites

Before synchronization, include `"android"` in `.gclient` `target_os`:

```python
target_os = ["android"]
```

The Chromium `src` solution's `custom_vars` must also contain
`checkout_pgo_profiles=True`. Add it to the existing solution rather than at
the top level of `.gclient`, for example:

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
or maintain a Chromium checkout manually must add it themselves. If Android is
newly added to `target_os`, run a full `gclient sync`; `gclient runhooks` alone
does not fetch the new Android dependencies. If only
`checkout_pgo_profiles` changed on an otherwise complete Android checkout,
`gclient runhooks` is sufficient. Running `version.py` after either change
performs the required sync and hooks.

## Optimization profiles

Chromium's gclient hooks and CIPD dependencies own Android optimization data;
`setup.py` does not download it separately:

- ARM32 release builds use Chromium's default Android AFDO profile together
  with the ARM32 orderfile; they do not consume the downloaded ARM32 full-PGO
  dataset.
- ARM64 release builds use full PGO and the matching ARM64 orderfile. Chromium
  keeps the ARM64 PGO profile in the ARM64 orderfile package so both profiles
  are generated from the same revision.
- x86 release builds use Chromium's default Android AFDO profile and keep
  `chrome_pgo_phase=0`. Chromium treats x64 as a high-end Android target by
  default, so the x64 release configurations use neither full PGO nor the
  default AFDO profile. The x86 and x64 argument files do not explicitly
  select a Chrome orderfile.
- `debug_args.gn` is an ARM64 non-official debug configuration and uses
  neither full PGO nor the default official-build AFDO profile.
- Android in `target_os` fetches both orderfile CIPD packages and the bundled
  ARM64 PGO profile independently of `checkout_pgo_profiles`.
- `checkout_pgo_profiles=True` enables the AFDO, additional PGO, and V8
  builtins profile hooks.

The argument files use source-absolute `//chrome/...` orderfile paths, so they
are portable across checkout locations.

## Prepare and build

Prepare the Chromium revision and apply the Android profile from the Thorium
checkout in this order:

```shell
python3 version.py
python3 setup.py --android
```

`version.py` selects the Chromium revision; it does not select the Android
architecture. The setup step applies Thorium's patches and Android resources
after that revision is ready.

Additional checkout maintenance commands include:

```shell
git fetch --tags
git rebase-update
gclient runhooks
git show-ref
```

Destructive synchronization commands are documented in the main [building
guide](../../docs/BUILDING.md#maintenance-and-cleanup).

Then change to the Chromium `src` directory and create or edit the Android
output configuration:

```shell
gn args out/thorium
gn ls out/thorium
```

Paste the appropriate `arm32_args.gn`, `arm64_args.gn`, `x86_args.gn`, or
`x64_args.gn` contents into the editor for the selected Android architecture.

Build from the Thorium checkout with the CPU matching the selected argument
file:

```shell
cd /path/to/thorium
python3 build.py --expect-os android --expect-cpu arm64
```

Replace `arm64` with `arm`, `x86`, or `x64` when using the corresponding
configuration.

The release APK filenames identify the actual GN target CPU. Android's `arm`
target is published as `arm32` to distinguish 32-bit ARM from ARM64:

| GN `target_cpu` | Filename suffix | Example browser APK |
| --- | --- | --- |
| `arm` | `arm32` | `Thorium_Public_arm32.apk` |
| `arm64` | `arm64` | `Thorium_Public_arm64.apk` |
| `x86` | `x86` | `Thorium_Public_x86.apk` |
| `x64` | `x64` | `Thorium_Public_x64.apk` |

The same suffix is used by `Thorium_Shell_*.apk` and
`SystemWebView_*.apk`. Each output directory must still be generated and built
for only one target CPU; renaming does not create a multi-architecture APK.
