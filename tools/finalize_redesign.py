from __future__ import annotations

import re
from pathlib import Path

SOURCE_URL = "https://github.com/ip7z/7zip/releases/download/26.02/7z2602-x64.exe"
SOURCE_SHA256 = "6745fa76dc2ea031596d8678f6f6b99c3c1b435b4164a63485adbbc7b8d82ef0"


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    Path(path).write_text(content, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def remove_named_step(text: str, name: str) -> str:
    pattern = re.compile(
        rf"\n      - name: {re.escape(name)}\n.*?(?=\n      - name:|\Z)",
        re.DOTALL,
    )
    updated, count = pattern.subn("", text, count=1)
    if count != 1:
        raise RuntimeError(f"workflow step not found exactly once: {name}")
    return updated


# GUI and packaging version come from pyproject/package metadata.
gui = read("src/kaito/gui/unzip_app.py")
gui = replace_once(
    gui,
    '__version__ = "0.9.1.dev0"',
    "from kaito.version import __version__",
    "GUI version",
)
write("src/kaito/gui/unzip_app.py", gui)

installer = read("installer/kaito.iss")
installer = replace_once(
    installer,
    '#define MyAppVersion "0.9.1-dev0"',
    '#define MyAppVersion "0.10.0-dev0"',
    "installer version",
)
installer = replace_once(
    installer,
    'Source: "..\\bundled\\SHA256SUMS"; DestDir: "{app}\\licenses"; Flags: ignoreversion',
    'Source: "..\\bundled\\SHA256SUMS"; DestDir: "{app}\\licenses"; Flags: ignoreversion\n'
    'Source: "..\\bundled\\SOURCE-PACKAGE.txt"; DestDir: "{app}\\licenses"; Flags: ignoreversion',
    "installer source package notice",
)
write("installer/kaito.iss", installer)

spec = read("build.spec")
spec = replace_once(
    spec,
    '"""PyInstaller build definition for kaito 0.9.1.dev0."""',
    '"""PyInstaller build definition for kaito 0.10.0.dev0."""',
    "build version",
)
spec = replace_once(
    spec,
    '    "bundled/SHA256SUMS",\n',
    '    "bundled/SHA256SUMS",\n    "bundled/SOURCE-PACKAGE.txt",\n',
    "build source package notice",
)
write("build.spec", spec)

# The official 26.02 x64 installer is not Authenticode-signed. Integrity is
# therefore anchored to the fixed official release URL and a pinned digest.
update_script = read("tools/update_7zip.ps1")
update_script = replace_once(
    update_script,
    "$ExpectedPackageSha256 = '__SET_BY_VERIFIED_WORKFLOW__'",
    f"$ExpectedPackageSha256 = '{SOURCE_SHA256}'",
    "source package digest",
)
old_signature_block = """    $Signature = Get-AuthenticodeSignature $PackagePath
    if ($Signature.Status -ne 'Valid') {
        throw \"Official package signature is not valid: $($Signature.Status)\"
    }
    Write-Host \"Signer: $($Signature.SignerCertificate.Subject)\"

"""
update_script = replace_once(
    update_script,
    old_signature_block,
    "    # 7-Zip 26.02 x64 installer is not Authenticode-signed.\n"
    "    # Trust is anchored to the official fixed URL and pinned SHA-256 below.\n\n",
    "unsigned package handling",
)
write("tools/update_7zip.ps1", update_script)

write(
    "bundled/SOURCE-PACKAGE.txt",
    f"Source: {SOURCE_URL}\n"
    "Authenticode: NotSigned\n"
    f"SHA-256: {SOURCE_SHA256}\n"
    "Verified on: GitHub Actions windows-latest, 2026-07-11\n",
)

notices = read("THIRD_PARTY_NOTICES.md")
marker = "The 7-Zip license includes GNU LGPL terms, BSD 2-Clause components, BSD 3-Clause components, and the unRAR license restriction. The complete redistributed notice is in `bundled/7-ZIP-LICENSE.txt`."
replacement = marker + (
    "\n\nThe upstream 26.02 x64 installer is not Authenticode-signed. kaito pins the "
    "official GitHub Release URL and its SHA-256 in `bundled/SOURCE-PACKAGE.txt`; "
    "the updater verifies that package digest before extracting the bundled files."
)
notices = replace_once(notices, marker, replacement, "third-party source notice")
write("THIRD_PARTY_NOTICES.md", notices)

readme = read("README.md")
readme_marker = "- ハッシュ: `bundled/SHA256SUMS`"
readme = replace_once(
    readme,
    readme_marker,
    readme_marker + "\n- 公式取得元とパッケージSHA-256: `bundled/SOURCE-PACKAGE.txt`",
    "README source identity",
)
write("README.md", readme)

# Return CI from diagnostic/mutating mode to strict reproducible verification.
ci = read(".github/workflows/ci.yml")
ci = remove_named_step(ci, "Regenerate lockfile for review")
ci = remove_named_step(ci, "Capture signed 7-Zip source package identity")
ci = remove_named_step(ci, "Capture required Ruff formatting")
ci = remove_named_step(ci, "Require committed formatting")
ci = replace_once(
    ci,
    "      - name: Type check\n",
    "      - name: Format check\n        run: uv run ruff format --check .\n\n"
    "      - name: Type check\n",
    "CI format check",
)
for diagnostic in (
    "            uv.lock.generated\n",
    "            7zip-source-package.txt\n",
    "            ruff-format.diff\n",
):
    ci = ci.replace(diagnostic, "")
ci = replace_once(
    ci,
    "(Join-Path $installDir 'licenses/SHA256SUMS')",
    "(Join-Path $installDir 'licenses/SHA256SUMS'), (Join-Path $installDir 'licenses/SOURCE-PACKAGE.txt')",
    "CI installed source notice",
)
write(".github/workflows/ci.yml", ci)

release = read(".github/workflows/release.yml")
release = replace_once(
    release,
    "            (Join-Path $installDir 'licenses/SHA256SUMS')",
    "            (Join-Path $installDir 'licenses/SHA256SUMS'),\n"
    "            (Join-Path $installDir 'licenses/SOURCE-PACKAGE.txt')",
    "release installed source notice",
)
write(".github/workflows/release.yml", release)
