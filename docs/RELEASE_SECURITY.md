# Release security model

The stable tag workflow is intentionally gated and fail-closed. Its signing mode is fixed to `required`; unsigned production assets cannot be published.

## Production environment

The Release job declares the GitHub Actions environment `production`. Repository administrators should configure that environment with required reviewers and store the production signing secrets there:

- `WINDOWS_CERTIFICATE_BASE64`
- `WINDOWS_CERTIFICATE_PASSWORD`

The workflow-side environment declaration is version-controlled. Required-reviewer rules are repository settings and are not created by the workflow file itself. Until those settings are configured, the environment name alone does not provide a human approval barrier.

## Shared package verifier

Both the tag-triggered production workflow and the non-publishing rehearsal execute `tools/verify_release_package.ps1`.

The verifier has two explicit profiles:

- `production`: requires the downloaded `SHA256SUMS` to match the locally verified file. Signed binaries must pass strict SignTool chain verification and Authenticode must be `Valid`. Rehearsal metadata is rejected.
- `rehearsal`: requires the build-job manifest and only accepts the short-lived self-signed `CN=kaito CI signing test` certificate. A SignTool failure is accepted only when it is the expected untrusted-root result.

Both profiles enforce the same package identity checks:

- exactly five top-level release files
- exactly four checksum entries
- exactly three metadata assets
- simple filenames only; no absolute paths or traversal
- no duplicate or case-colliding names
- matching SHA-256 values and byte sizes
- matching version, tag and commit
- CycloneDX 1.6 SBOM identity
- bundled 7-Zip 26.02 hashes
- signer thumbprint consistency

## Publication sequence

1. Validate the stable tag and current `master`.
2. Validate signing configuration and build the package.
3. Refuse every existing Release for the tag and create a brand-new Draft Release.
4. Upload exactly five assets to that new Release ID.
5. Download and verify all Draft assets with the shared `production` profile.
6. Stop with the Release in Draft state and record the exact Release ID and build run ID.
7. A separately dispatched workflow downloads the original build evidence and the same Draft assets, re-verifies them, and rechecks live master, tag, run, Release ID, Draft state, and asset count.
8. Publish only the exact verified Draft Release when every identity still matches.

Existing Draft or public Releases are never reused, and publication cannot occur in the tag-triggered build workflow.
