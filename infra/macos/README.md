# macOS native smoke comparison

[`macos-smoke-test.yml`](../../.github/workflows/macos-smoke-test.yml) compares
the **same Thorium version** as native x64 and ARM64 applications. It follows
the [WOA workflow](../woa/README.md): download a release package or build
artifact, install it into an isolated location, run browser probes, and upload
diagnostics even when the test fails. It does not compile Chromium.

The defaults select M156.0.8078.28 and `macos_version: 14`, with three native
runs using two same-repository release assets:

| System / architecture | Runner | Release asset |
| --- | --- | --- |
| macOS 14 ARM64 | `macos-14` | `Thorium_MacOS_ARM64.dmg` |
| macOS 15 x64 | `macos-15-intel` | `Thorium_MacOS_x64.dmg` |
| macOS 15 ARM64 | `macos-15` | `Thorium_MacOS_ARM64.dmg` |

The macOS 14 ARM64 run targets the system family reported in the crash issues.
The macOS 15 pair compares architectures on the same OS major version; the
two ARM64 runs also compare OS versions. GitHub currently lists macOS 14 Intel
only as the paid `macos-14-large` larger runner, which this workflow does not
request. See the [standard runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
and [larger runner reference](https://docs.github.com/en/actions/reference/runners/larger-runners).

Select `macos_version: 15` or `26` to run just the native x64/ARM64 pair on that
OS major version. The harness rejects an incorrect OS major version, host
architecture or Rosetta execution and validates every Mach-O file against the
selected architecture. The jobs do not cancel each other on failure. A final
comparison job shows every target's actual OS version, bundle version and
baseline results.
The comparison also shows separate GUI issue results for startup responsiveness
(#1286) and the Baidu search reproduction (#1316).

## Run the M156 comparison

After this workflow is present on the repository's default branch, select
**Compare macOS x64 and ARM64 artifacts** in Actions and run it with the defaults,
or use:

```sh
gh workflow run macos-smoke-test.yml --repo gz83/thorium \
  -f release_tag=M156.0.8078.28 \
  -f expected_version=156.0.8078.28 \
  -f macos_version=14
```

Downloads are limited to the workflow's own repository. A fork must contain the
release assets or use artifacts from its own builds. Optional `x64_sha256` and
`arm64_sha256` inputs verify the original DMGs before mounting them. Actual
SHA-256 values are always recorded. Asset inputs are exact filenames, not URLs
or wildcard patterns.

For a previous Actions run, clear `release_tag`, set `source_run_id`, and leave
`current_run_artifact: false`. Upload one DMG at the root of each artifact named
`thorium-macos-x64` and `thorium-macos-arm64`. `artifact_prefix` changes that
common prefix. The artifact filenames must match `x64_asset` and `arm64_asset`.

A producing workflow can call the comparison after uploading both DMGs:

```yaml
jobs:
  # build-and-package uploads thorium-macos-x64 and thorium-macos-arm64.
  smoke-test:
    needs: build-and-package
    permissions:
      actions: read
      contents: read
    uses: ./.github/workflows/macos-smoke-test.yml
    with:
      current_run_artifact: true
      expected_version: 156.0.8078.28
      macos_version: "14"
```

## What is tested

The DMG is verified and mounted read-only. `Thorium.app` is copied using `ditto`
into a temporary directory, then its version, architecture and code signature
are checked. The harness preserves the original signature and quarantine
attributes: a packaging/signature failure is reported rather than hidden by
re-signing the application. The mount, temporary app and profiles are cleaned up.

Both headless and normal-window runs use new profiles, mock Keychain access,
first-run/default-browser prompt suppression, stderr logging and a DevTools
pipe. The baseline preserves the normal extension, GPU and sandbox settings.
There is no npm dependency, ChromeDriver requirement or exposed debugging port;
the runner needs Python 3.11+ and Node.js 22+.

Each baseline requires a responsive startup page, a local HTML page with
JavaScript/typed-array/BigInt/RegExp/WebAssembly checks, `chrome://version`,
`chrome://newtab`, and a final local renderer liveness check.

The GUI run records two issue-specific results before the capability checks:

- **#1286:** wait for the startup page, obtain the browser window through CDP,
  bring the page forward and verify JavaScript execution. This checks browser,
  window and renderer responsiveness; it does not exercise native toolbar/menu
  input or establish that every kind of UI freeze is absent.
- **#1316:** open `https://www.baidu.com/`, focus a visible search field, insert
  `hello` with CDP input, and submit with Enter. Both the current `#chat-textarea`
  editor and classic `#kw`/`name="wd"` fields are supported, with editable
  fallbacks limited to the search container. A pass requires a Baidu `/s`
  URL with `wd=hello`, actual result entries/headings, a loaded document, and a
  renderer that remains responsive after a two-second observation. The original
  direct navigation to the result URL is not used. Homepage/input/result
  screenshots, full HTML snapshots, input inventories and step details are
  retained when available. HTML is not truncated: inline styles can otherwise
  consume the entire snapshot before the input DOM. The `*-inputs.json` files
  record field identities, editability, focus and geometry to help diagnose
  future page changes. CAPTCHA is recorded without attempting to bypass it.

The GUI run then performs WebGL shader compilation, drawing and pixel readback,
and `OfflineAudioContext` rendering as independent checks. A WebGL API/shader
failure does not skip audio, and neither check can prevent the earlier issue
reproductions. A renderer/process crash still stops checks that can no longer
run. Capability assertion failures are shown separately as diagnostic `FAIL`
results and do not determine the overall status or trigger flag retries. A
required CDP timeout or renderer hang/crash during these checks still fails the
baseline. The recorded WebGL renderer can indicate software rendering; a pass
does not necessarily imply physical GPU acceleration. `gui/gpu-info.json`
records CDP GPU devices, feature status and driver workarounds when available,
to help distinguish a hosted runner limitation from a browser regression.

Google navigation remains an additional diagnostic. An explicit Google network
failure alone does not prevent an overall pass if the renderer is responsive.
An unverified Baidu reproduction always prevents an overall pass.

| Status | Meaning |
| --- | --- |
| `PASS` | The check completed and met its assertions. |
| `FAIL` | A check failed, a required command timed out, or a crash was detected. |
| `INCOMPLETE` | The check could not be verified or was not reached; for Baidu this includes network blocks, CAPTCHA, changed/missing page elements and missing result content. |

Network/verification problems are only marked `INCOMPLETE` when the renderer
still executes JavaScript. An unresponsive or crashed renderer is `FAIL`.
The overall result gives failures precedence over incomplete checks, and is
`PASS` only when both baselines and the required startup/Baidu checks pass;
WebGL/audio diagnostics are displayed separately. Headless does
not run the GUI issue/capability checks; its issue columns show a dash. Missing
GUI results in the final comparison are `INCOMPLETE`, never a pass. Exit codes
are 0 for `PASS`, 1 for `FAIL`, and 2 for `INCOMPLETE`; Actions stays non-green
for either unsuccessful outcome, while the summary explains the distinction.

Normal-window navigation is mandatory. DevTools page screenshots and macOS
desktop screenshots are attempted independently; screenshot availability is
diagnostic because hosted desktop capture can be restricted. A desktop PNG is
not automatically judged nonblank and does not prove native UI correctness.

After a baseline `FAIL`, three independent runs add only `--disable-extensions`,
`--disable-gpu`, or `--no-sandbox`, using a fresh profile each time and repeating
the same suite. If both baseline modes fail, diagnostics use headless mode;
otherwise they use the failing mode. A diagnostic pass never changes a baseline
failure into success. Disabling the GPU may itself make the GUI WebGL diagnostic
fail without changing the core/issue result.
An `INCOMPLETE` result alone does not trigger these diagnostic flag changes.

## Reading the evidence

Each `macos-smoke-<os>-<arch>-<run>-<attempt>` artifact contains:

- `summary.json` / `summary.md`, input provenance, actual OS/CPU/display details,
  package hash, bundle identity, Mach-O architectures, UUIDs and load commands;
- signature, entitlement and extended-attribute inspection output;
- separate baseline and diagnostic directories with browser stdout/stderr,
  phase-tagged DevTools events, page/issue/capability results, GPU information,
  full Baidu HTML snapshots, input inventories and available screenshots;
- a dedicated Crashpad database, fallback profile crash files, and new Thorium
  system diagnostic reports;
- process lists and attempted `sample` thread stacks captured **before** killing
  a failing/hung browser. Sampling errors are retained when macOS denies access.

Detected renderer crashes, early browser exits, command timeouts and crash files
fail the baseline even when a page previously rendered successfully. GUI testing
still runs after a headless failure. Each probe has a five-minute deadline and
bounded cleanup; missing reports fail the final comparison.

This comparison can distinguish architecture- and OS-dependent failures relevant to issues
[#1286](https://github.com/Alex313031/thorium/issues/1286) and
[#1316](https://github.com/Alex313031/thorium/issues/1316), but hosted images do
not guarantee the same macOS patch release or physical hardware as the reporters.
macOS 14 hosted runners are
[retiring on November 2, 2026](https://github.com/actions/runner-images/issues/13518),
with scheduled brownouts before that date. A runner availability failure is
not browser-crash evidence. After retirement, select `15` or `26`; reproducing
Sonoma failures will require a separate macOS 14 host. Symbolizing a crash also
requires matching dSYMs from the exact binary build; these runtime tests cannot
reconstruct them.

## Run directly on a Mac

The actual browser smoke harness can also be run directly:

```sh
python3 infra/macos/smoke_test.py \
  --dmg /path/to/Thorium_MacOS_ARM64.dmg --arch arm64 \
  --expected-version 156.0.8078.28 --results /tmp/thorium-macos-report
```
