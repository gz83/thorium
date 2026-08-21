# TODO

Actionable bugs and feature requests are tracked in
[GitHub Issues](https://github.com/Alex313031/thorium/issues). This file records
cross-cutting product decisions, implementation work, and verification tasks,
whether or not they already have a dedicated issue.

## Product decisions

- [ ] Re-evaluate SSD Restore behavior
  despite [Thorium issue #61](https://github.com/Alex313031/thorium/issues/61)
  being closed as not planned.
  Measure the current Chromium baseline's Session Restore write frequency
  before deciding whether to adjust the save interval or offer an option that
  disables persistent session writes.

- [ ] Decide whether UA Client Hints should advertise an additional Chrome
  brand. The traditional User-Agent already uses `Chrome/<version>`; consider
  both website compatibility and accurate product identification.

- [ ] Decide whether Thorium should enable the upstream autoplay settings UI.
  First attempt to reproduce its historical Profile Picker crash on the
  current Chromium baseline and document the result.

## Implementation

- [ ] Make `create_dmg.py` include the application architecture in Thorium DMG
  filenames, using distinct names for x64, ARM64, and universal builds.

- [ ] Synchronize ThoriumOS Shortcuts app metadata with
  `keyboard_shortcuts.patch` in the
  [ThoriumOS repository](https://github.com/Alex313031/ThoriumOS):
  - replace the stale Ctrl+Shift+D “Bookmark all tabs” entry with “Duplicate
    tab”;
  - document the Thorium browser shortcuts enabled on ChromeOS;
  - verify that the displayed modifiers match the Ash accelerators changed by
    the patch.

- [ ] Add a Settings UI for the existing disk-cache directory backend
  ([Thorium issue #860](https://github.com/Alex313031/thorium/issues/860)).
  Validate the selected directory and explain that the new location takes
  effect after restart. Store the setting in Local State for all profiles, do
  not automatically migrate or delete the old cache, and make the UI read-only
  or clearly indicate when managed policy or `--disk-cache-dir` controls the
  effective path.

- [ ] Make `DownloadShelfView` propagate item preferred-height changes to
  `BrowserView` and size the shelf from the tallest visible item. Verify that
  the top and item separators remain continuous during window resizing and
  transitions between normal, warning, and deep-scanning modes.

- [ ] Add Thorium-specific desktop app-menu commands:
  - Restart Thorium using `chrome::AttemptRestart()` while retaining Chromium's
    normal session-restoration semantics;
  - Report issue, opening Thorium's GitHub issue template;
  - What's new, opening Thorium release notes rather than Google Chrome-branded
    content.

## Verification and benchmarking

- [ ] Visually verify the Omnibox and bookmark bar with Thorium 2024 enabled and
  disabled. Cover the Omnibox outline, input icon and text, Views suggestion
  popup alignment, and bookmark bar underline with custom themes, keyword mode,
  permission chips, `classic-omnibox`, and 100%/125%/150% display scaling. If
  an issue exists, record the tested Thorium version, platform, theme, display
  scale, expected appearance, and result before changing the current color,
  border, or alignment handling; open a dedicated issue with screenshots for
  any failure.

- [ ] Establish a reproducible benchmark comparing non-optimized Thorium,
  optimized Thorium, Chromium, and Google Chrome based on the same full
  Chromium version where available. Define non-optimized Thorium from the same
  Thorium source and feature patches by disabling only the compiler
  optimizations under measurement. Keep the hardware, workload, profile, and
  number of runs consistent. Archive the complete `args.gn` for locally built
  binaries and record unavoidable differences in revision, toolchain, PGO
  configuration, branding, and proprietary components.

- [ ] Verify restored-window top drag and resize hit targets with Thorium 2024
  UI on Windows, Linux/X11, Linux/Wayland, and macOS. Confirm that tabs and
  caption buttons remain vertically aligned and that the top edge remains
  resizable.

- [ ] Verify and document Thorium's `--no-autoplay` behavior against
  [Supermium issue #1412](https://github.com/win32ss/supermium/issues/1412) on
  every platform where Thorium distributes the switch:
  - confirm that audible HTML media without a user gesture are blocked;
  - confirm that muted video continues to follow Chromium's muted-autoplay
    rules;
  - confirm that an explicit `--autoplay-policy` takes precedence;
  - document that desktop WebAudio remains allowed by
    `allow-webaudio-autoplay.patch`, or decide separately whether it should
    honor `--no-autoplay`.
