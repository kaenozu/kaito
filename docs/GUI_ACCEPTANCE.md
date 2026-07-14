# Windows GUI check

This checklist complements automated tests for personal use. Run it when a change affects GUI behavior or Windows integration.

## Automated check

The `packaged-gui-smoke` job runs focused regressions, builds `kaito.exe`, starts the packaged GUI, requires a live top-level window, captures a screenshot, and uploads the executable and test output.

## Optional interaction checks

1. **Encrypted extraction password** — Confirm extraction-password fields are masked, cancel clears the value, and reopening does not restore it.
2. **Rapid preview switching** — Alternate quickly between text and image entries and confirm the UI remains responsive and stale results do not overwrite the latest selection.
3. **Blocked safety report** — Confirm full and selected extraction remain disabled after a blocked safety result.
4. **Recent-history deletion** — Delete recent history, restart kaito, and confirm entries do not return.
5. **Oversized image preview** — Confirm an oversized image is rejected without a hang or crash.
6. **Empty selected folder** — Create and extract a ZIP containing a completely empty selected root folder.
7. **Explorer integration** — Install the generated installer, verify context-menu commands, uninstall, and confirm registrations are removed.

Failures should be recorded with reproduction steps. These checks are quality checks for the owner, not public-release approval gates.
