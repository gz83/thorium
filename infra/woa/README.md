# Windows on ARM64 smoke test

[`smoke_test.ps1`](smoke_test.ps1) is the native Windows ARM64 test harness
used by [the WOA smoke-test workflow](../../.github/workflows/woa-smoke-test.yml).
It validates a raw `thorium_ARM64_installer.exe` without depending on whether
the installer was built on Linux or Windows.

The test runs on GitHub's `windows-11-arm` runner and verifies:

- the installer is an ARM64 PE file;
- its optional SHA-256 matches;
- silent per-user installation succeeds;
- every runtime EXE and DLL is ARM64;
- the intentionally bundled offline PAK tools are the expected IA-32 and x64
  binaries in the installed version directory;
- Thorium can render a local page in headless mode without disabling its
  sandbox;
- native V8 JavaScript, typed arrays, BigInt, regular expressions, and a small
  WebAssembly module execute successfully in that renderer;
- WebGL compiles and links shaders, draws a triangle, and returns the expected
  pixel value through `readPixels()`;
- `OfflineAudioContext` renders a local oscillator with valid peak and RMS
  sample levels without requiring an audio output device;
- normal-window Thorium can navigate to Google and `chrome://version`;
- `chrome://version` identifies the running build as ARM64;
- the native browser frame can be captured as a nonblank PNG when the runner
  exposes a capturable desktop;
- the installed setup program can uninstall Thorium.

The harness follows Chromium installer status semantics: first installation
returns `0`, while a successful `setup.exe --uninstall --force-uninstall`
returns `19` (`UNINSTALL_SUCCESSFUL`).

Thorium currently bundles `pak_mingw32.exe` and `pak_mingw64.exe` so users can
inspect and rebuild PAK resources. They are packaging tools, not browser runtime
components, and cannot be ARM64 because their retained public filenames denote
their target architectures. The architecture check requires these two exact
files directly under the installed version directory, with PE machines `0x014C`
and `0x8664` respectively. A missing or incorrectly built PAK tool, or any other
non-ARM64 EXE or DLL, still fails the test.

The headless probe primarily verifies successful native startup, JavaScript
execution, and rendering using Chromium's normal GPU selection. If
`--dump-dom` writes the expected script-generated DOM but does not terminate
itself before the timeout, the harness stops its process tree, records a
diagnostic warning, and continues. A timeout without the expected DOM remains
a hard failure. Installer and uninstaller timeouts are always hard failures.

The primary headless and GUI probes do not disable background networking,
component updates, default applications, synchronization, extensions, the
sandbox, or GPU selection. They suppress the first-run and default-browser
prompts so those UI surfaces cannot obstruct unattended automation, enable
stderr logging, and otherwise retain only the arguments required to isolate
the temporary test profile and drive the corresponding headless or
DevTools-based automation. More invasive arguments are confined to diagnostic
runs after the primary headless probe has already failed.

When the normal headless probe cannot render, the harness runs two diagnostic
comparisons and records their results in separate logs. `--disable-extensions`
isolates the installed extension configuration, while `--no-sandbox` isolates
the Windows sandbox and sandboxed child-process path. These are diagnosis only:
the release test still fails if either comparison renders successfully because
the default installed configuration must work without weakening its sandbox.
Failure in all three runs points to a broader renderer, child-process, or
payload problem.

When all three headless probes fail without producing a Crashpad minidump, the
harness performs one additional diagnostic run with Crashpad disabled and a
temporary per-user Windows Error Reporting `LocalDumps` entry for
`thorium.exe`. This is intended to capture FailFast renderer failures such as
`0xC0000409`, which may bypass Chromium's normal dump path. The temporary
registry entry and profile are removed during cleanup; any resulting minidump
is retained under `crash-dumps/wer` in the report artifact. This diagnostic
does not weaken or replace the normal release checks.

The GUI probe runs the installed `thorium.exe` normally; it does not use
`--headless` or disable the GPU. Even after a headless failure, it runs before
the final failure is reported so the artifact retains independent renderer
evidence. It discovers the normal Browser Frame through Win32, verifies a local
page, `chrome://version`, and Google through the local DevTools endpoint,
and attempts a full-window `PrintWindow` capture. If that image is blank, it
tries a desktop-region capture. Screenshots and `gui-report.json` are stored
under the report artifact's `gui` directory. The report also retains the last
page targets observed through DevTools, and a startup-window screenshot is
captured before external navigation is judged, so a network failure does not
discard all GUI evidence. The harness inspects the Windows accessibility tree
for Chromium crash-page error codes such as `STATUS_ACCESS_VIOLATION`, records
the code and a failure screenshot, and repeats that check after each activated
page is captured. A DevTools target URL and title alone are not accepted as
proof that its renderer survived navigation.

Each browser probe sets Chromium's test-supported `BREAKPAD_DUMP_LOCATION` to
an isolated directory inside the uploaded report, so Windows Crashpad does not
write to its normal profile-independent database. Any generated `.dmp` files
therefore survive cleanup. After Crashpad creates a dump, the harness briefly
waits for its size to stabilize before terminating the remaining browser
process tree; `CrashDumpReady` in the JSON report records whether that handoff
completed. When Crashpad produces no dump, the report also preserves abnormal
renderer-termination histograms, their probable Windows NTSTATUS value, and
matching Application Error or Windows Error Reporting events. Minidumps and
event records are diagnostic evidence rather than a substitute for symbols;
obtain matching PDB files from the exact build when a stack trace is required.

GitHub Actions does not provide an interactive remote desktop for a person to
operate. The Windows job can still start desktop processes in its job session,
but GitHub does not guarantee that DWM composition or screen capture remains
available on every hosted image. The workflow therefore attempts GUI testing
by default. A detected renderer crash or Crashpad dump is always a hard product
failure. Other GUI capability failures remain diagnostic until `require_gui`
is enabled. After a successful trial establishes that the current
`windows-11-arm` image supports navigation and captures, set
`require_gui: true` to make those runner capabilities a release gate as well.
Once a GUI renderer is available, a failed WebGL or `OfflineAudioContext`
capability check is always a hard product failure, independent of
`require_gui`.

This workflow does not validate real hardware acceleration, media hardware
paths, Widevine playback, touch behavior, or human-visible UI quality. A WOA
device or tester is still required before treating a new major release as fully
validated.

## Test an artifact from another Actions run

The producing workflow must upload one raw ARM64 mini installer in an artifact.
Run `Test Windows on ARM64 artifact` manually and provide:

```text
source_run_id: numeric ID of the producing run
artifact_name: name passed to actions/upload-artifact
current_run_artifact: false
installer_pattern: thorium_ARM64_installer.exe
expected_sha256: optional 64-character digest
require_gui: false for the first capability-probing run
```

The run must belong to the same repository. The workflow deliberately does not
download artifacts or executables from arbitrary external URLs.

## Call it after an online build

A future Linux or Windows WOA build workflow can upload the installer and call
the reusable workflow in the same run:

```yaml
jobs:
  build:
    # Build and upload an artifact named thorium-woa-installer.
    # ...

  smoke-test:
    needs: build
    permissions:
      actions: read
      contents: read
    uses: ./.github/workflows/woa-smoke-test.yml
    with:
      artifact_name: thorium-woa-installer
      current_run_artifact: true
      require_gui: true
```

Do not place source trees, `out/`, PDB files, or portable archives in this
artifact. Upload the raw mini installer so selection and integrity checks remain
unambiguous.

## Test a local Linux cross-build

For a one-off local build, upload the raw installer to a temporary draft release
in your own repository, then select that tag in the manual workflow:

```shell
repo=OWNER/REPOSITORY
installer=/path/to/thorium_ARM64_installer.exe
tag=woa-smoke-$(date +%Y%m%d-%H%M%S)
sha256=$(sha256sum "$installer" | cut -d' ' -f1)
gh release create "$tag" --repo "$repo" --draft \
  --title "$tag" --notes "Temporary WOA smoke input"
gh release upload "$tag" "$installer" --repo "$repo"
gh workflow run woa-smoke-test.yml \
  --repo "$repo" \
  -f release_tag="$tag" \
  -f release_asset_pattern=thorium_ARM64_installer.exe \
  -f installer_pattern=thorium_ARM64_installer.exe \
  -f expected_sha256="$sha256" \
  -f require_gui=false
```

After the test has downloaded the asset, remove the temporary draft and tag:

```shell
gh release delete "$tag" --repo "$repo" --cleanup-tag --yes
```

Only test artifacts that you built or otherwise trust: the workflow installs
and executes the supplied binary on its runner.
