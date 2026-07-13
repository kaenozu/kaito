from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = REPOSITORY_ROOT / "tools" / "verify_release_package.ps1"
REHEARSAL_WRAPPER_PATH = REPOSITORY_ROOT / "tools" / "verify_release_rehearsal.ps1"
RELEASE_WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"
REHEARSAL_WORKFLOW_PATH = (
    REPOSITORY_ROOT / ".github" / "workflows" / "release-rehearsal.yml"
)


def test_production_and_rehearsal_execute_the_same_verifier() -> None:
    release = RELEASE_WORKFLOW_PATH.read_text(encoding="utf-8")
    rehearsal = REHEARSAL_WORKFLOW_PATH.read_text(encoding="utf-8")

    command = "./tools/verify_release_package.ps1"
    assert command in release
    assert command in rehearsal
    assert "-Profile production" in release
    assert "-Profile rehearsal" in rehearsal
    assert "-ReferenceChecksumsPath 'dist/SHA256SUMS'" in release
    assert "-ExpectedManifestBase64" in rehearsal


def test_shared_verifier_separates_trust_profiles_fail_closed() -> None:
    verifier = VERIFIER_PATH.read_text(encoding="utf-8")

    assert "[ValidateSet('production', 'rehearsal')]" in verifier
    assert "Production verification refuses rehearsal metadata" in verifier
    assert "Production SignTool verification failed" in verifier
    assert "Production Authenticode verification failed" in verifier
    assert "Rehearsal SignTool verification failed with an unexpected error" in verifier
    assert "test-untrusted" in verifier
    assert "CN=kaito CI signing test" in verifier
    assert "Rehearsal certificate lifetime exceeds three days" in verifier


def test_shared_verifier_rejects_ambiguous_package_identity() -> None:
    verifier = VERIFIER_PATH.read_text(encoding="utf-8")

    assert "Release package must contain exactly five files" in verifier
    assert "SHA256SUMS must contain exactly four entries" in verifier
    assert "Release metadata must describe exactly three assets" in verifier
    assert "duplicate or case-colliding" in verifier
    assert "must use a simple file name without a path" in verifier
    assert (
        "Downloaded SHA256SUMS differs from the locally verified reference file"
        in verifier
    )
    assert "Release SBOM source commit does not match" in verifier
    assert "Release SBOM checksum mismatch for bundled file" in verifier


def test_legacy_rehearsal_entrypoint_is_only_a_compatibility_wrapper() -> None:
    wrapper = REHEARSAL_WRAPPER_PATH.read_text(encoding="utf-8")

    assert "verify_release_package.ps1" in wrapper
    assert "Profile = 'rehearsal'" in wrapper
    assert "Get-AuthenticodeSignature" not in wrapper
    assert "SHA256SUMS" not in wrapper


def test_hardening_executes_production_verifier_negative_cases() -> None:
    hardening = (
        REPOSITORY_ROOT / ".github" / "workflows" / "release-hardening.yml"
    ).read_text(encoding="utf-8")
    integration = (
        REPOSITORY_ROOT / "tools" / "test_verify_release_package.ps1"
    ).read_text(encoding="utf-8")

    assert "Test shared production release verifier" in hardening
    assert "test_verify_release_package.ps1" in hardening
    assert "accept valid unsigned production package" in integration
    assert "reject tampered asset" in integration
    assert "reject unexpected package file" in integration
    assert "reject path-like checksum entry" in integration
    assert "reject rehearsal metadata in production profile" in integration
    assert "reject self-signed binaries in production profile" in integration
