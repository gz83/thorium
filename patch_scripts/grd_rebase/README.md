# GRD/XTB Rebase

This directory contains the reviewed Thorium GRD/GRDP and XTB rebase tooling
for moving Thorium string changes out of the overlay and into repeatable
scripts.

The runtime surface is intentionally small:

- `sync_grd_strings.py` updates reviewed Chromium GRD/GRDP messages, computes
  old and new GRIT translation IDs, and copies compatible upstream XTB
  translations to the new Thorium IDs.
- `merge_thorium_xtb.py` merges the selected translation inventories into
  Chromium XTB bundles and verifies the merged files with `--check`.
- `update_config_from_patches.py` refreshes low-risk config rows that can be
  derived from the current patch series.

These scripts use only the Python standard library. They do not require
`vpython`, `depot_tools`, or a Chromium checkout's Python wrapper. Python 3.11
or newer is the supported runtime.

## Configuration

The files in `config/` are reviewed inputs, not generated setup output:

- `file_allowlist.csv`: reviewed GRD/GRDP file scope and file ownership role.
  `from_overlay` records the legacy source of the reviewed change; pure
  `overlay_text_sync` files do not need to remain under `src/` once their
  messages are covered by automatic branding discovery or
  `message_allowlist.csv`.
- `message_allowlist.csv`: reviewed message-level exceptions and special
  replacements. Automatic branding discovery covers the standard text-sync
  roles. Files with the `explicit_text_sync` role process only the named
  messages. The list covers three Dino messages and eight browser references
  in the Gemini provider change and Skills gallery notices.
- `feature_patch_message_ownership.csv`: feature-patch and overlay-added
  message ownership; used to prevent feature-patch strings from being handled
  by the overlay replacement workflow. Pass a non-default ownership file to
  `sync_grd_strings.py` with `--feature-message-ownership`.
- `xtb_additions.tsv` contains 4631 reviewed translations across 407 XTB files.
  55 owner/bundle/ID groups provide all 81 translations. Another 62 groups
  supply individual locales where an upstream translation is missing or its
  wording needs correction. Other locales use normal ID migration. Chromium bundles
  may use different locale aliases for the same language, such as `he` or
  `iw` for Hebrew. Rows are grouped by the explicit `owner` column, then by
  bundle, translation ID, and locale. An owner may be a feature patch path or
  a stable GRD rebase workflow identifier, such as
  `grd_rebase:branding:IDS_VERSION_UI_LICENSE`; translations produced by
  branding synchronization do not need a synthetic or historical patch owner.
  `source_path` separately records where each translation was recovered or
  reviewed. It is audit provenance only and may use a stable reviewed source
  identifier instead of a historical Git commit; it does not restrict which
  Chromium checkout receives the translation. The `chromium-upstream:` prefix
  identifies translations recovered from Chromium-owned XTB data without
  binding them to a particular Chromium milestone. The following path and
  message or translation ID retain the concrete audit source. No runtime tool
  parses this prefix or uses it to select translations. When using an alternate
  inventory, pass the same `--inventory` to both sync and merge. The merge owns
  the exact target XTB path and ID for each inventory row.
- `windows_legacy_xtb_additions.tsv` adds four REWORK messages to the 81
  `chromium_strings` locale bundles when `--windows-legacy` is enabled.
  The shortcut label uses Chromium 159 translations. The uninstall prompt
  uses Chromium 109 translations. The pre-XP warning and the unsupported
  Windows installer message have Thorium translations.

`update_config_from_patches.py` may rewrite
`config/feature_patch_message_ownership.csv` and
`config/file_allowlist.csv` by default. It does not rewrite
`message_allowlist.csv` or `xtb_additions.tsv`; those remain reviewed
inputs because they contain special text behavior or translation-data
decisions.

## Run Order

Run the scripts after Chromium and non-string feature patches are in place:

1. Run `sync_grd_strings.py`.
2. Run `merge_thorium_xtb.py`.
3. Run `merge_thorium_xtb.py --check` on the same tree and inventory.

For a Windows legacy checkout, pass `--windows-legacy` to the sync and merge
commands, including dry runs. The read-only check detects the prepared profile
from the Windows locale header, GRD messages or installer string list. Passing the flag also requires
the legacy messages to be present. `setup.py` runs all three steps for the
selected profile.

The check verifies XTB languages against their GRD registrations. For both
profiles it checks the Windows installer's resource references, Chromium-brand
exports and translations in every registered installer locale. For Windows
legacy it also checks the final GRIT IDs and placeholders of nine messages,
the corresponding Windows language pack filenames, and XP font defaults and
overrides.

This order keeps overlay-derived old/new ID syncing separate from reviewed
Thorium-owned additions.

## Python Runtime

Use any Python 3.11+ interpreter available on the host:

```shell
python3 patch_scripts/grd_rebase/sync_grd_strings.py --help
python3 patch_scripts/grd_rebase/merge_thorium_xtb.py --help
```

On Windows, either `py -3.11`, a normal `python.exe`, or
`C:\src\depot_tools\python3.bat` can be used. The depot_tools wrapper is only a
convenient Chromium-environment Python, not a requirement for these scripts.

All config paths stored in this directory use repository-relative POSIX-style
paths. Command-line paths may use native platform separators or `/`; the scripts
normalize them internally where needed.

## Dry Run

Dry-run low-risk config refresh:

```shell
python3 patch_scripts/grd_rebase/update_config_from_patches.py --dry-run
```

Dry-run the overlay string sync and write compact audit summaries:

```shell
mkdir -p out/grd_rebase

python3 patch_scripts/grd_rebase/sync_grd_strings.py \
  /path/to/chromium/src \
  --file-allowlist patch_scripts/grd_rebase/config/file_allowlist.csv \
  --message-allowlist patch_scripts/grd_rebase/config/message_allowlist.csv \
  --dry-run \
  --xtb-conflict-report out/grd_rebase/xtb_conflicts_summary.tsv \
  --xtb-missing-report out/grd_rebase/xtb_missing_summary.tsv \
  > out/grd_rebase/grd_sync_dry_run.tsv
```

Dry-run the reviewed additions merge:

```shell
python3 patch_scripts/grd_rebase/merge_thorium_xtb.py \
  /path/to/chromium/src \
  --dry-run
```

The summary always reports the validated inventory size and then classifies
each row according to the supplied Chromium worktree, for example:

```text
validated 4631 Thorium translations across 407 XTB files: <inserted> inserted, <refreshed> refreshed, <already-present> already present, <changed-files> files changed
```

Only the first two counts are inventory invariants. The inserted, refreshed,
already-present, and changed-file counts vary with the Chromium revision and
the current state of its worktree.

Equivalent PowerShell form:

```powershell
New-Item -ItemType Directory -Force out/grd_rebase | Out-Null

py -3.11 patch_scripts/grd_rebase/sync_grd_strings.py `
  C:\src\chromium\src `
  --file-allowlist patch_scripts/grd_rebase/config/file_allowlist.csv `
  --message-allowlist patch_scripts/grd_rebase/config/message_allowlist.csv `
  --dry-run `
  --xtb-conflict-report out/grd_rebase/xtb_conflicts_summary.tsv `
  --xtb-missing-report out/grd_rebase/xtb_missing_summary.tsv `
  > out/grd_rebase/grd_sync_dry_run.tsv

py -3.11 patch_scripts/grd_rebase/merge_thorium_xtb.py `
  C:\src\chromium\src `
  --dry-run
```

## Apply

Refresh low-risk config from the current patch series:

```shell
python3 patch_scripts/grd_rebase/update_config_from_patches.py
```

Apply overlay GRD/GRDP replacements and copied XTB translations:

```shell
python3 patch_scripts/grd_rebase/sync_grd_strings.py \
  /path/to/chromium/src \
  --file-allowlist patch_scripts/grd_rebase/config/file_allowlist.csv \
  --message-allowlist patch_scripts/grd_rebase/config/message_allowlist.csv
```

Apply reviewed XTB additions:

```shell
python3 patch_scripts/grd_rebase/merge_thorium_xtb.py \
  /path/to/chromium/src
```

All apply operations are designed to be idempotent.

## GRIT ID Notes

Sync and release validation use `grit_messages.py` to calculate translation IDs
for the reviewed messages. It implements Chromium's `GenerateMessageId()`
fingerprint and meaning handling.

- MD5 first 64 bits interpreted as signed.
- Optional `meaning` fingerprint combined with the message fingerprint.
- The high bit is stripped to produce a positive decimal ID.
- `use_name_for_id="true"` returns the message name.
- `<ph name="...">` uses the placeholder presentation/name in presentable
  content.

The replica is intentionally scoped to reviewed text-sync files plus explicit
special messages. If future special entries include conditional message bodies
that need platform-specific active-branch resolution, compare against Chromium
GRIT parser output before enabling them.

## Reports

`sync_grd_strings.py` can write compact audit reports:

- `--xtb-conflict-report`: summarized converged new-ID conflicts where multiple
  old translations map to the same new ID. Reviewed global or locale-specific
  preferences select the appropriate old translation where required. For
  remaining conflicts, the script deterministically keeps the first candidate
  and reports grouped review buckets instead of every locale row.
- `--xtb-missing-report` checks the final ID in each mapped locale for the
  planned source changes (including unchanged IDs) and patch-owned declarations
  marked for upstream reuse or complete additions. It includes the translations
  that sync will copy and the exact target rows in the reviewed merge inventory.
  Generate this report on the patched baseline before applying string sync.
  In Windows legacy mode, sync checks all nine messages on every run.
  If a translation is missing from a mapped locale after accounting for the
  planned merge, sync reports the message and exits before writing resources.

Current dry-runs may report converged XTB conflicts. Review the grouped conflict
report before accepting the deterministically selected candidates. A reviewed
locale-specific preference affects only that locale; other locales in the same
converged-ID group retain their normal selection and remain visible in the
report when they still conflict. The missing report is expected to contain only
its header. Each data row identifies a resource and locales that still need a
translation before release.

## Validation

After setup, verify the reviewed translations on disk with the same profile
used to prepare the checkout. For example, for Windows legacy:

```shell
python3 patch_scripts/grd_rebase/merge_thorium_xtb.py /path/to/chromium/src --windows-legacy --check
```

`--check` is read-only and exits nonzero when an inventory entry is missing
or differs from the merged text. It identifies each affected XTB file. For a
legacy checkout it also verifies all nine messages in the Windows locales of
`chromium_strings`, `generated_resources`, `ui_strings` and `ax_strings`.
Windows installer builds through `build.py` run this check
before starting Ninja, including with `--dry-run`.
The earlier `--xtb-missing-report` also accounts for planned insertions.

Basic syntax checks:

```shell
python3 -m py_compile \
  patch_scripts/grd_rebase/grit_messages.py \
  patch_scripts/grd_rebase/update_config_from_patches.py \
  patch_scripts/grd_rebase/sync_grd_strings.py \
  patch_scripts/grd_rebase/merge_thorium_xtb.py
```

Behavior validation should run the dry-run command and inspect the compact
reports:

- conflict summary should be grouped into a small number of review buckets;
- missing summary should contain only its header; if it contains data rows,
  each row should group all missing locales for one message and must be
  resolved before release.

The full dry-run TSV is useful for script refactors and spot checks, but it is
not intended to be reviewed line by line.
