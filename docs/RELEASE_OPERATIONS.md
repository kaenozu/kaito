# Release operations and approval gates

This document separates version-controlled safeguards from repository settings and production credentials. A green pull request does not by itself authorize a merge, tag, signing-secret use, or Release publication.

## Required repository settings

Configure a GitHub Environment named `production` before enabling production signing.

- Add at least one independent Required Reviewer.
- Prevent self-review when the repository plan supports it.
- Store `WINDOWS_CERTIFICATE_BASE64` and `WINDOWS_CERTIFICATE_PASSWORD` as Environment secrets, not repository-wide secrets.
- Store `WINDOWS_TIMESTAMP_URL` as an Environment variable and require an HTTPS RFC 3161 endpoint.
- Restrict Environment deployment branches or tags to the intended release policy.
- Protect `master` with the normal Windows CI, Release Hardening, and Release Rehearsal checks.
- Require the branch to be current with `master` before merge when the repository plan supports it.
- Require an independent approving review and dismiss stale approvals after new commits.

These settings are not created by workflow YAML. Their presence must be checked in the repository settings before production use.

## Draft Release roundtrip canary

Workflow: `Draft Release roundtrip canary`

Purpose: exercise the real GitHub tag, Draft Release, asset upload, Release API download, shared verifier, and cleanup path without publishing a Release.

Preconditions:

1. The release hardening and shared verifier pull requests are merged.
2. The selected `source_ref` has successful CI, Hardening, and Rehearsal checks.
3. No Release or tag exists with the generated `draft-roundtrip-<run>-<attempt>` name.
4. The operator has explicit authorization to create and delete a temporary tag and Draft Release.

Run procedure:

1. Open **Actions → Draft Release roundtrip canary → Run workflow**.
2. Select the reviewed source ref, normally `master`.
3. Enter `CREATE_AND_DELETE_DRAFT` exactly.
4. Confirm that the run creates only a Draft Release.
5. Confirm that the five assets are downloaded and verified with the `rehearsal` trust profile.
6. Confirm that cleanup deletes both the Draft Release and temporary tag.
7. Retain the metadata-only Actions evidence.

The workflow contains no publication command. Cleanup refuses to silently delete an unexpectedly public Release and fails if absence of both objects cannot be proven.

## Production signing canary

Workflow: `Production signing canary`

Purpose: validate the real production PFX, trusted certificate chain, timestamp endpoint, SignTool strict verification, and Authenticode identity without creating a tag or Release.

Preconditions:

1. The `production` Environment has an independent Required Reviewer.
2. Environment secrets and `WINDOWS_TIMESTAMP_URL` are configured.
3. The certificate is the intended production code-signing certificate and is currently valid.
4. Secret use has explicit authorization.

Run procedure:

1. Open **Actions → Production signing canary → Run workflow**.
2. Enter `SIGN_CANARY_WITH_PRODUCTION_CERT` exactly.
3. Complete the Environment approval.
4. Confirm the fresh executable is unsigned before signing.
5. Confirm required-mode signing succeeds with the configured timestamp URL.
6. Confirm independent SignTool verification succeeds and Authenticode reports `Valid`.
7. Confirm the signer thumbprint matches the signing status and is not the CI test certificate.
8. Confirm the signed executable is deleted before evidence upload.

Only JSON and text evidence is retained. The signed canary binary is not uploaded.

## Pull-request and merge sequence

1. Review and approve the release-hardening pull request at a fixed HEAD.
2. Merge it with an expected-head guard; do not create a tag or Release.
3. Retarget the shared-verifier pull request to `master`, rerun all required checks, review, and merge.
4. Retarget the canary-workflow pull request to `master`, rerun static and normal checks, review, and merge.
5. Configure and verify repository Environment and branch-protection settings.
6. Run the Draft Release roundtrip canary only after explicit temporary-tag authorization.
7. Run the production signing canary only after explicit production-secret authorization.
8. Perform an actual release only under a separate release decision and fixed tag/commit review.

## Manual security disposition

GitGuardian incidents must be dispositioned in the GitGuardian dashboard after direct inspection. A code comment or successful CI run does not change dashboard incident status.

Record the following for each incident:

- detector and incident ID;
- affected historical commit and line;
- whether the value was a runtime-generated test value, fixture, or real credential;
- final-tree search result;
- rotation requirement, if any;
- reviewer and disposition date.

Do not rewrite shared history solely to hide a false-positive fixture unless a real credential was committed or repository policy requires history removal.
