# Release operations and fixed-head gates

This document separates version-controlled safeguards from repository settings and production credentials. A green pull request does not by itself authorize a merge, tag, signing-secret use, or Release publication.

`kaenozu/kaito` uses a solo-maintainer model. External approving review is optional and the required approval count is zero. The maintainer must still make an explicit decision for the exact target after all technical and administrative gates pass.

## Non-negotiable authorization boundaries

The following actions require an explicit decision for the exact target and must not be inferred from a successful CI run or an earlier audit:

- marking a Draft pull request Ready for Review;
- merging or enabling auto-merge;
- creating or moving a tag;
- creating, publishing, or deleting a Release outside an authorized canary;
- using production signing secrets, a production certificate, or a production timestamp service.

Bot or AI feedback may assist review but is not an authorization boundary. No second human is required for PR merge authorization under the solo-maintainer policy.

## Repository capability and protection gate

Protect `master` before merging PR #20. The first release-pipeline merge must not occur while repository policy is only documented but unenforced.

Required branch protection or ruleset controls:

- require a pull request before merging;
- set required approving reviews to zero;
- do not require approval of the most recent push by another user;
- require all review conversations to be resolved;
- require the normal Windows CI, Release Hardening, and Release Rehearsal checks;
- require the pull request to be current with `master` when supported;
- prevent force pushes and branch deletion;
- apply the rule to administrators or otherwise record any unavoidable owner bypass;
- Enable Release immutability for future published Releases.

The repository is private. Verify the active GitHub plan before relying on branch protection, rulesets, or Environment protection. Environment secrets and deployment branches require a plan that supports the selected private-repository controls.

## Fixed-head pull-request gate

Workflow: `Release PR fixed-head gate`

Purpose: produce fail-closed evidence for a specific pull request, HEAD SHA, current `master` SHA, exact changed-file set, required workflow set, review-thread state, and auto-merge state.

The workflow is manual and read-only. It requires the exact confirmation phrase `VERIFY_FIXED_PR_GATE` and uploads JSON evidence. A result is:

- `PASS` only when every fixed-head and repository-state check passes;
- `FAIL` for a PR state, SHA, file, workflow, review-thread, or auto-merge mismatch;
- `INCONCLUSIVE` when GitHub state cannot be retrieved or evaluated completely.

The gate does not fetch collaborator permissions and does not require an `APPROVED` review. It records a `solo_maintainer_policy` PASS check instead.

For PR #20, the previously validated snapshot was:

- base ref: `master`;
- current base SHA: `bfcbd9904196043e371a8f398edc71a6de30cdf1`;
- fixed HEAD: `8cac1e2985a9ca3c7f68893f0a95debbc6f8b67b`;
- comparison: 63 ahead, 0 behind;
- required workflows: `CI`, `Release hardening checks`, `Release rehearsal`;
- exact changed files: 12.

That snapshot is no longer merge-authorizing because a Release publication race was identified. The corrected PR #20 HEAD, comparison, file set, and workflows must be supplied when the gate is eventually run.

## Required repository settings

Configure a GitHub Environment named `production` before enabling production signing.

- Store `WINDOWS_CERTIFICATE_BASE64` and `WINDOWS_CERTIFICATE_PASSWORD` as Environment secrets, not repository-wide secrets.
- Store `WINDOWS_TIMESTAMP_URL` as an Environment variable and require an HTTPS RFC 3161 endpoint.
- Restrict Environment deployment branches or tags to the intended release policy.
- Verify ordinary pull-request workflows cannot read production secrets.
- An Environment Required Reviewer is optional under the solo-maintainer model; do not configure an impossible second-person requirement unless a collaborator is intentionally added later.

These settings are not created by workflow YAML. Their presence must be checked in repository settings before production use.

## Pull-request and merge sequence

1. Confirm the GitHub plan and available repository controls.
2. Protect `master` before merging PR #20 with the controls listed above.
3. Correct PR #20's Release publication race and rerun all required workflows on the resulting new HEAD.
4. Reconfirm PR #20 against its current base SHA, fixed HEAD, exact file set, successful workflows, zero unresolved threads, disabled auto-merge, and GitGuardian disposition.
5. Run the fixed-head gate and retain its JSON evidence.
6. Merge PR #20 only after a separate explicit merge authorization and with an expected-head guard.
7. Retarget PR #12 to `master`, update it to the new `master`, rerun all required workflows, run the gate, and merge only after explicit authorization.
8. Retarget PR #15 to `master`, update it to the new `master`, rerun all required workflows, run the gate, and merge only after explicit authorization.
9. Configure and verify the `production` Environment, Environment-scoped credentials, deployment restrictions, and secret isolation before any production-signing canary.
10. Complete GitGuardian incident disposition before production credentials are used.
11. Run the Draft Release roundtrip canary only after explicit temporary-tag and Draft-Release authorization.
12. Run the production signing canary only after explicit production-secret authorization and any Environment gate that is actually configured.
13. Perform an actual release only under a separate fixed tag, commit, and publication decision.

Any new commit, base movement, changed-file difference, failed or missing workflow, unresolved thread, or auto-merge state change invalidates the previous gate evidence.

## Draft Release roundtrip canary

Workflow: `Draft Release roundtrip canary`

Purpose: exercise the real GitHub tag, Draft Release, asset upload, Release API download, shared verifier, and cleanup path without publishing a Release.

Preconditions:

1. PR #20, PR #12, and PR #15 are merged in order under the fixed-head process above.
2. The selected `source_ref` has successful CI, Hardening, and Rehearsal checks.
3. No Release or tag exists with the generated `draft-roundtrip-<run>-<attempt>` name.
4. The operator has explicitly authorized creation and deletion of the temporary tag and Draft Release.

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

1. The `production` Environment and its protection controls have been verified.
2. Environment secrets and `WINDOWS_TIMESTAMP_URL` are configured.
3. The certificate is the intended production code-signing certificate and is currently valid.
4. Secret use has explicit authorization from the repository owner for the exact run.

Run procedure:

1. Open **Actions → Production signing canary → Run workflow**.
2. Enter `SIGN_CANARY_WITH_PRODUCTION_CERT` exactly.
3. Complete any Environment approval that is actually configured.
4. Confirm the fresh executable is unsigned before signing.
5. Confirm required-mode signing succeeds with the configured HTTPS timestamp URL.
6. Confirm independent SignTool verification succeeds and Authenticode reports `Valid`.
7. Confirm the signer thumbprint matches the signing status and is not the CI test certificate.
8. Confirm the signed executable is deleted before evidence upload.

Only JSON and text evidence is retained. The signed canary binary is not uploaded.

## Manual security disposition

GitGuardian incidents must be dispositioned in the GitGuardian dashboard after direct inspection. A code comment or successful CI run does not change dashboard incident status.

Record the following for each incident:

- detector and incident ID;
- affected historical commit and line;
- whether the value was a runtime-generated test value, fixture, or real credential;
- final-tree search result;
- rotation requirement, if any;
- operator and disposition date.

Do not rewrite shared history solely to hide a false-positive fixture unless a real credential was committed or repository policy requires history removal.
