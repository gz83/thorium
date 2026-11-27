# Thorium Patch Series

`patch_scripts/series/series` is the ordered list of Thorium's regular
patches. The optional [Windows REWORK series](../../other/rework-windows/README.md)
has a separate pinned manifest and applies after the selected regular patches.

Patch files intentionally remain in `other/` for now. The series layer records
ordering, apply roots, and platform conditions. The root-level `setup.py`
applies patches through this runner on every supported host platform.

## Platform Notes

Run the scripts from the Thorium repository root. On Windows, the examples use
the Python launcher:

```powershell
py -3.11 patch_scripts\series\apply_series.py --help
```

On Linux/macOS, use `python3`:

```sh
python3 patch_scripts/series/apply_series.py --help
```

All paths may be passed in the host platform's native style. The series file
itself should keep forward slashes.

## Syntax

```text
other/example.patch
chromium/apply/root: other/example.patch
[condition] chromium/apply/root: other/example.patch
```

Patch paths are relative to the Thorium repository root. Apply roots are
relative to the Chromium source tree. Use forward slashes in the series file;
the runner resolves them through Python's `Path` APIs on the host platform.
Apply roots may be standalone Git checkouts or subdirectories inside the main
Chromium checkout; the runner handles both forms.
For example, this applies the patch from inside Chromium's
`third_party/ffmpeg` checkout:

```text
third_party/ffmpeg: other/ffmpeg-branding.patch
```

## Check

Windows:

```powershell
py -3.11 patch_scripts\series\apply_series.py --source-tree C:\src\chromium\src
```

Linux/macOS:

```sh
python3 patch_scripts/series/apply_series.py --source-tree /path/to/chromium/src
```

Check mode is the default. It validates ordered patch dependencies by applying
each patch cumulatively to temporary Git indexes with `git apply --cached`.
This does not modify the Chromium worktree or its real index.

If `--source-tree` is omitted, the runner follows the same convention as
Thorium's setup scripts:

1. `CR_DIR`
2. `CR_SRC_DIR`
3. `CHROMIUM_SRC`
4. `CHROMIUM_SRC_DIR`

It then falls back to `C:\src\chromium\src` on Windows or `~/chromium/src` on
Linux/macOS.

If `--thorium-root` is omitted, the runner uses `THOR_DIR` when set, otherwise
it uses the repository containing `patch_scripts/series/apply_series.py`.

## Conditions

Conditional entries are skipped unless explicitly enabled:

Windows:

```powershell
py -3.11 patch_scripts\series\apply_series.py --source-tree C:\src\chromium\src --condition sse2
```

Linux/macOS:

```sh
python3 patch_scripts/series/apply_series.py --source-tree /path/to/chromium/src --condition sse2
```

Select at most one build variant, such as `sse2` or `raspi`. The apply/check
runner also accepts `--condition windows-legacy` alone or together with a
Windows desktop SIMD variant. It checks both layers in a temporary directory
and verifies their resulting file hashes before writing any patch output.

## Apply

Windows:

```powershell
py -3.11 patch_scripts\series\apply_series.py --source-tree C:\src\chromium\src --apply
```

Linux/macOS:

```sh
python3 patch_scripts/series/apply_series.py --source-tree /path/to/chromium/src --apply
```

`--apply` modifies the Chromium checkout. It first checks whether a patch
applies cleanly, applies it with `git apply --reject`, and treats
reverse-applicable patches as already applied.

## Refresh

Use `refresh_series.py` to re-export patches against the current ordered
series context. It applies each patch to a temporary index, exports the
single-patch tree delta, and compares that output with the existing patch file.

Default dry-run checks only unconditional entries.

Windows:

```powershell
py -3.11 patch_scripts\series\refresh_series.py --source-tree C:\src\chromium\src
```

Linux/macOS:

```sh
python3 patch_scripts/series/refresh_series.py --source-tree /path/to/chromium/src
```

The refresh runner applies the series to temporary Git indexes and compares
temporary trees, so it does not modify the Chromium worktree or Chromium's real
index. It only reports patch files whose re-exported form differs from the
current file.

Refresh follows normal apply/check condition handling by default: unconditional
entries are processed, while conditional entries are skipped. Pass
`--condition sse2` or `--condition raspi` to refresh that variant together with
the unconditional entries that precede it. In condition mode, unconditional
entries are applied as context only; only entries with the requested condition
are eligible for refresh/write.

`--all-conditions` selects every conditional entry in one combined temporary
index flow. It is useful for checking series coverage and whether the current
set of conditional patches can be applied together, but it does not create an
isolated audit for each build variant. It therefore cannot replace separate
`--condition sse2` and `--condition raspi` runs when validating those variants.
The runner rejects `--all-conditions --write` and also verifies that every
`other/**/*.patch` file is listed in the series.

The temporary indexes are initialized from each apply root's `HEAD`. The
Chromium worktree may have local changes, but the checked-out `HEAD` must be
the intended base revision for the series.

To overwrite changed unconditional patch files on Windows:

```powershell
py -3.11 patch_scripts\series\refresh_series.py --source-tree C:\src\chromium\src --write
```

To overwrite changed unconditional patch files on Linux/macOS:

```sh
python3 patch_scripts/series/refresh_series.py --source-tree /path/to/chromium/src --write
```

Variant dry-run on Windows:

```powershell
py -3.11 patch_scripts\series\refresh_series.py --source-tree C:\src\chromium\src --condition raspi
```

Variant dry-run on Linux/macOS:

```sh
python3 patch_scripts/series/refresh_series.py --source-tree /path/to/chromium/src --condition raspi
```

Variant write-back only updates patches tagged with the requested condition;
unconditional entries are applied as context and reported as `context-only`:

Windows:

```powershell
py -3.11 patch_scripts\series\refresh_series.py --source-tree C:\src\chromium\src --condition raspi --write
```

Linux/macOS:

```sh
python3 patch_scripts/series/refresh_series.py --source-tree /path/to/chromium/src --condition raspi --write
```

Full conditional audit on Windows:

```powershell
py -3.11 patch_scripts\series\refresh_series.py --source-tree C:\src\chromium\src --all-conditions
```

Full conditional audit on Linux/macOS:

```sh
python3 patch_scripts/series/refresh_series.py --source-tree /path/to/chromium/src --all-conditions
```

`--all-conditions --write` is intentionally rejected. Write conditional
patches one variant at a time:

```shell
python3 patch_scripts/series/refresh_series.py \
  --source-tree /path/to/chromium/src --condition sse2 --write
python3 patch_scripts/series/refresh_series.py \
  --source-tree /path/to/chromium/src --condition raspi --write
```

If a patch fails to apply, refresh stops and leaves the patch for manual
repair. Mail-style patches with headers are reported but not rewritten.

## Policy

External patches should be imported into `other/` before they become part of
the normal rebase flow. Add a separate external series only if Thorium later
needs to consume a live external patch stack during review.
