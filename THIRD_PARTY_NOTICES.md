# Third-party notices

## 7-Zip 26.02

kaito bundles the Windows console executable and core library from 7-Zip 26.02:

- `bundled/7z.exe`
- `bundled/7z.dll`

Upstream release: `https://github.com/ip7z/7zip/releases/tag/26.02`

The 7-Zip license includes GNU LGPL terms, BSD 2-Clause components, BSD 3-Clause components, and the unRAR license restriction. The complete redistributed notice is in `bundled/7-ZIP-LICENSE.txt`.

The official 26.02 x64 installer used as the source package is not Authenticode-signed. kaito therefore pins both the official GitHub Release URL and its SHA-256 in `bundled/SOURCE-PACKAGE.txt`. `tools/update_7zip.ps1` verifies the package digest before extraction, then independently verifies the extracted `7z.exe` and `7z.dll` against `bundled/SHA256SUMS` before replacing repository files.

RAR support is extraction-only. kaito does not implement or expose RAR creation.

## libarchive test fixtures

RAR files used by kaito's automated tests originate from the libarchive test suite at fixed commit:

`da33bf2d713d05f482a08a4f26aa6e0331444579`

They are test-only, are not included in release builds, and retain their upstream uuencoded representation. Provenance, decoded hashes, expected contents, and license text are under `tests/fixtures/rar/`.

## Python dependencies

Runtime Python dependencies and their versions are declared in `pyproject.toml` and locked in `uv.lock`. Their licenses remain the property of their respective copyright holders.
