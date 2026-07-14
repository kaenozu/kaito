# Release operations and approval gates

A green pull request does not by itself authorize a merge, tag, production-secret use, canary execution, or Release publication. Version-controlled safeguards, repository settings, independent approval, and explicit operational authorization remain separate controls.

## Repository protection gate

Protect `master` before merging the unified release and application hardening pull request.

Required branch protection or ruleset controls:

- require a pull request before merging;
- require at least one independent approving review;
- dismiss stale approvals after new commits;
- require approval of the most recent push by someone other than the pusher when supported;
- require all review conversations to be resolved;
- require `verify-windows`, `signing-and-sbom`, `build-rehearsal-package`, `verify-redownloaded-package`, and `packaged-gui-smoke`;
- require the pull request to be current with `master` when supported;
- prevent force pushes and branch deletion;
- apply the rule to administrators or prohibit administrative bypass for release-sensitive changes.

Do not substitute self-approval, a bot comment, a resolved thread, or successful CI for an independent approving review. Save screenshots or exported settings as administrative evidence.

## Unified pull-request process

The former stacked release PRs and application-fix PR are superseded by one clean `master`-based PR. It contains the final reviewed tree without importing the historical implementation commits that produced secret-scanner noise and ordering dependencies.

Before merge:

1. inspect the current PR diff against the live `master` tree;
2. confirm all required Actions jobs succeed on the exact current HEAD;
3. confirm zero unresolved review threads;
4. directly inspect and disposition any new GitGuardian incident against the clean PR;
5. complete the manual GUI checklist in `GUI_ACCEPTANCE.md` on the packaged artifact;
6. obtain an independent approving review anchored to the current HEAD;
7. revalidate the expected HEAD immediately before a separately authorized merge.

After this workflow file exists on `master`, run `Release PR approval gate` for later release-sensitive pull requests. The workflow is manual because `workflow_dispatch` can only be relied on after the workflow is present on the default branch.

## Production Environment

Configure a GitHub Environment named `production` before production signing:

- store `WINDOWS_CERTIFICATE_BASE64` and `WINDOWS_CERTIFICATE_PASSWORD` as Environment secrets;
- store `WINDOWS_TIMESTAMP_URL` as an HTTPS Environment variable;
- restrict deployment branches or tags to the intended release policy;
- verify ordinary pull-request workflows cannot read production secrets;
- add an independent Required Reviewer and prevent self-review when the plan supports those controls.

The stable Release workflow is fixed to required signing. Missing, partial, invalid, expired, incorrectly scoped, or mismatched signing material fails before publication.

If Environment Required Reviewers are unavailable, the one-time issue-comment authorization in `PRODUCTION_SIGNING_AUTHORIZATION.md` is mandatory. An unprotected Environment, a confirmation string alone, repository-owner self-approval, or CI success is not equivalent.

## Draft Release roundtrip canary

Run `Draft Release roundtrip canary` only from `master`, after required checks succeed and an operator is explicitly authorized to create and delete the temporary tag and Draft Release. It uploads the five expected assets, redownloads and verifies them, contains no publication command, and cleans up fail-closed.

## Production signing canary

Run `Production signing canary` only after Environment configuration, deployment restrictions, secret-scanner disposition, and independent authorization are verified. The approval binds repository, workflow, exact current `master` SHA, fresh nonce, expiration, and `APPROVE`; it is consumed once before the signing job accesses Environment secrets.

## Actual Release

A production Release is a separate decision and is split into two operations.

1. After explicit tag authorization, push a new stable tag that points to the exact live `master` HEAD. `Build signed draft Release` requires production signing, refuses every existing Release for the tag, creates a new Draft Release, redownloads all five assets, and verifies them against build evidence.
2. Record the exact tag, commit, Release ID, and successful build run ID. Inspect the exact production-signed Draft artifacts.
3. After separate publication authorization, dispatch `Publish verified Release` from `master` with those exact identities and `PUBLISH_VERIFIED_RELEASE`.
4. The publication workflow downloads the original build-run evidence, redownloads the same Draft assets, runs the shared production verifier, rechecks live identity, and only then makes that Release public.

The build workflow contains no publication command. Existing Releases and tags are never reused, overwritten, or moved. See `RELEASE_PUBLICATION.md`.
