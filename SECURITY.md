# Security policy

## Supported version

Security fixes are applied to the latest released version and the active development branch.

## Reporting a vulnerability

Do not publish a proof of concept containing private user data. Open a private security advisory in GitHub when available, or contact the repository owner directly.

Include the affected archive format, a minimal reproducer, expected behavior, actual behavior, and the kaito/7-Zip versions.

## Archive handling

kaito treats archive contents as untrusted input.

- Absolute paths, drive-letter paths, UNC paths, parent traversal, NTFS alternate data streams, reserved device names, NUL characters, and ambiguous Windows trailing dots/spaces are rejected.
- Link, hard-link, and reparse-point entries are rejected.
- RAR and 7z extraction is staged in a new temporary directory, validated after extraction, and only then moved to the requested destination.
- Entry count, individual file size, total expanded size, and compression ratio are limited.
- Existing destination files are not silently overwritten by the 7-Zip backend.

No validation can make an archive parser risk-free. Keep kaito and its bundled 7-Zip version current.

## Password handling

- Passwords are kept in memory for the current session only and are not written to settings.
- kaito redacts passwords from returned command arguments, application errors, stdout/stderr captured for diagnostics, and tests.
- 7-Zip CLI requires the password to be supplied through its command-line `-p` switch. On Windows, another process running as the same user may be able to inspect process command lines while an encrypted archive is being processed.
- Avoid handling sensitive encrypted archives on shared or untrusted Windows sessions.

A future direct 7z.dll integration may remove the command-line exposure, but that is not implemented in the current release.

## Bundled backend integrity

Release builds only use the bundled `7z.exe` and `7z.dll`. Their SHA-256 values are fixed in source and in `bundled/SHA256SUMS`. A frozen executable does not fall back to a system-installed 7-Zip when the bundled copy is missing or has the wrong hash.
