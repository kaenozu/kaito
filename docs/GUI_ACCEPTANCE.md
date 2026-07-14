# Windows GUI acceptance

This checklist complements, but does not replace, automated tests. Perform it against the exact packaged artifact from the pull request's `GUI acceptance` workflow and record the workflow run, artifact SHA-256, Windows version, tester, and result.

## Automated gate

The `packaged-gui-smoke` job must pass on the exact PR HEAD. It runs focused regression tests, builds `kaito.exe`, starts the packaged GUI, requires a live top-level window, captures a screenshot, and uploads the executable, screenshot, and test output.

## Manual cases

1. **Encrypted extraction password** — Open an encrypted ZIP, RAR, and 7z. Confirm every extraction-password field displays mask characters, cancel clears the value, and reopening does not restore it.
2. **Rapid preview switching** — Alternate quickly between text and image entries in ZIP and 7z archives. Confirm the UI remains responsive and an older worker result never overwrites the latest selection.
3. **Blocked safety report** — Open an archive that exceeds a configured limit or contains a rejected path. Confirm both full extraction and selected extraction remain disabled after search, selection, preview, and settings interactions.
4. **Recent-history deletion** — Add at least two recent archives, choose `履歴を削除`, reopen the menu, and restart kaito. Confirm the entries do not return.
5. **Oversized image preview** — Open an archive containing an image above the configured pixel limit. Confirm a rejection message appears without a hang, crash, or full image rendering.
6. **Empty selected folder** — Create a ZIP from a completely empty selected folder, inspect the archive entry, extract it, and confirm the empty root directory is preserved.
7. **Explorer integration** — Install the generated installer, verify open/extract/integrity/compress context-menu commands, uninstall, and confirm registrations are removed.

## Pass rule

Every case must pass on the exact current PR HEAD. A changed commit invalidates the prior manual result. Record failures as issues with reproduction steps and do not mark the PR Ready for Review until they are corrected and retested.
