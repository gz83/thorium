# REWORK for Thorium M159 on Windows

This optional patch series adds legacy Windows compatibility code to Thorium
`e4585112` (Chromium `159.0.8154.36`) for x86 and x64. It uses the
[REWORK patches for Chromium 159.0.8146.0](https://github.com/e3kskoy7wqk/Chromium-for-windows-7-REWORK/tree/a76fca71dd5dd7f33eb80e4dbbee9e58de124d93/chromium-159.0.8146.0).
Runtime verification on older Windows versions is pending.

## Apply

After syncing Chromium and its pinned dependencies, run this from the Thorium
checkout. Add your usual SIMD flag, such as `--sse2`, when preparing that profile.

```cmd
py -3.11 setup.py --thorium-root . --chromium-src D:\src\chromium\src --windows-legacy
```

Setup applies Thorium's regular patches first, then REWORK, and includes the
[Windows legacy translations](../../patch_scripts/grd_rebase/README.md). Use Chromium's
Rust toolchain or a target sysroot built with the patched Rust standard library.
To return to a regular build, use a clean checkout of the pinned Chromium revision.

## Verify

To check both patch series, use a Chromium tree with the Thorium overlays
already in place. For a SIMD build, add the matching condition, such as
`--condition sse2`.

```cmd
py -3.11 patch_scripts\series\apply_series.py --thorium-root . --source-tree D:\src\chromium\src --condition windows-legacy
```

To compare the local patches with the pinned upstream release, run the audit
against the directory containing `commit_hashes.txt` and the original `.diff` files.

```cmd
py -3.11 patch_scripts\series\audit_rework.py D:\path\to\REWORK\chromium-159.0.8146.0
```

Patch order, hashes and reasons for adaptations or exclusions are recorded in
[series.tsv](series.tsv). The [localization patch](repairs/windows-localization.diff)
updates the Control Panel display name and XP locale fallback after REWORK.
The [Windows language and font patch](repairs/windows-locale-consumers.diff)
shares XP locale lookup across the browser, Blink and accessibility, selects the
localized tooltip font, and supports localized installer dialogs on XP.
The [runtime locale patch](repairs/windows-locale-runtime.diff) handles XP
installer language fallback, speech voice languages, ICU regional formats,
and locale enumeration. The [Windows locale integration patch](repairs/windows-locale-integration.diff)
connects the captions subpage on Windows before 10, preserves localized file
dialog titles, handles unknown XP locales, and samples CPU usage on XP
without relying on localized counter names.
