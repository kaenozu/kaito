# Release operations and approval gates

A green pull request does not by itself authorize a merge, tag, signing-secret use, canary execution, or Release publication. This document separates version-controlled safeguards from repository settings and human approvals.

## Non-negotiable authorization boundaries

The following actions require an explicit decision for the exact target:

- marking a Draft pull request Ready for Review;
- merging or enabling auto-merge;
- creating, moving, or deleting a tag;
- creating, publishing, or deleting a Release outside an authorized canary;
- using production signing secrets, a production certificate, or a production timestamp service.

Do not substitute self-approval, a bot comment, a resolved thread, or successful CI for an independent approving review.

## Repository protection gate

Protect `master` before merging PR #11. The first release-pipeline merge must not occur while repository policy is only documented but unenforced.

Required branch protection or ruleset controls:

- require a pull request before merging;
- require at least one independent approving review;
- dismiss stale approvals after new commits;
- require approval of the most recent push by someone other than the pusher when supported;
- require all review conversations to be resolved;
- require the actual Actions check contexts `verify-windows`, `signing-and-sbom`, `build-rehearsal-package`, and `verify-redownloaded-package`;
- require the pull request to be current with `master` when supported;
- prevent force pushes and branch deletion;
- apply the rule to administrators or prohibit administrative bypass during this release sequence.

Save screenshots or exported settings as evidence. Workflow display names such as `CI` or `Release rehearsal` are not substitutes for selecting the actual required check contexts shown by GitHub.

The repository is private. Verify the active GitHub plan before relying on private-repository Environment protection features. If Environment Required Reviewers are unavailable, production signing remains blocked until the independent one-time authorization control documented in `PRODUCTION_SIGNING_AUTHORIZATION.md` is merged and active.

## Fixed-head approval gate and bootstrap exception

The `Release PR approval gate` is a manual `workflow_dispatch` workflow. GitHub can run a manually dispatched workflow only after that workflow file exists on the default branch.

The gate is introduced by PR #15, so it cannot be used as a precondition for merging PR #11, PR #12, or PR #15. Those three pull requests are the explicit bootstrap set.

For the bootstrap set, use all of the following instead:

1. active native `master` protection;
2. a human independent `APPROVED` review anchored to the current PR HEAD;
3. exact comparison of current base, merge base, ahead/behind counts, and changed-file set;
4. successful required Actions jobs on that exact HEAD;
5. zero unresolved review threads;
6. disabled auto-merge;
7. immediate state revalidation before a separately authorized merge using an expected-head guard.

After PR #15 is merged, the fixed-head approval gate becomes mandatory for later release-sensitive pull requests in addition to native protection. Any new commit, base movement, changed-file difference, failed or missing workflow, unresolved thread, or stale approval invalidates prior evidence.

## Ordered pull-request sequence

1. Confirm the GitHub plan and identify a human reviewer with `write`, `maintain`, or `admin` permission who is not the pull-request author.
2. Configure and verify `master` protection with the controls and exact check contexts above.
3. Directly inspect and disposition GitGuardian incidents `34773149` and `34773150`.
4. Reconfirm PR #11 against current `master`, fixed HEAD `9174b11a87d80e4654c987b7d1708427367b5ee0`, exact current-master comparison, successful required jobs, resolved threads, and disabled auto-merge.
5. Obtain an independent approval on the fixed PR #11 HEAD.
6. Merge PR #11 only after separate explicit merge authorization and with the expected-head guard.
7. Retarget PR #12 to `master`, synchronize it, rerun all required jobs, obtain a fresh independent approval, revalidate, and merge only after separate authorization.
8. Retarget PR #15 to `master`, synchronize it, rerun all required jobs, obtain a fresh independent approval, revalidate, and merge only after separate authorization.
9. After PR #15 is on `master`, use the fixed-head approval gate for subsequent release-sensitive pull requests.
10. Process the production-signing dual-control follow-up only after PR #15, with the same independent review and explicit merge authorization.

PR #11 metadata has previously reported one extra file already present on current `master`. The direct comparison against the current `master` tree is authoritative only when the discrepancy is explained and reconfirmed immediately before approval and merge; otherwise the result is `INCONCLUSIVE`.

## Production Environment

Configure a GitHub Environment named `production` before production signing:

- store `WINDOWS_CERTIFICATE_BASE64` and `WINDOWS_CERTIFICATE_PASSWORD` as Environment secrets, not repository-wide secrets;
- store `WINDOWS_TIMESTAMP_URL` as an Environment variable and require HTTPS;
- restrict deployment branches or tags to the intended release policy;
- verify ordinary pull-request workflows cannot read production secrets;
- add an independent Required Reviewer and prevent self-review when the plan supports those controls.

If an independent Environment reviewer is unavailable, the one-time issue-comment authorization in `PRODUCTION_SIGNING_AUTHORIZATION.md` is required. An unprotected Environment, a confirmation string alone, or repository-owner self-approval is not equivalent.

## Draft Release roundtrip canary

Run `Draft Release roundtrip canary` only after PR #11, PR #12, and PR #15 are merged in order and the selected source ref has successful required checks. The operator must have explicit authorization to create and delete a temporary tag and Draft Release.

The workflow must:

- create only a unique temporary tag and Draft Release;
- upload the exact five expected assets;
- redownload and verify the package through the shared rehearsal verifier;
- contain no publication command;
- delete the Draft Release and tag in fail-closed cleanup;
- refuse silent cleanup if the Release becomes public;
- retain metadata-only evidence.

## Production signing canary

Run `Production signing canary` only after the Environment, secrets, deployment restrictions, GitGuardian disposition, and independent authorization control are verified.

The authorization must bind the repository, workflow, exact current `master` SHA, fresh nonce, expiry, and `APPROVE` decision. The approver must be a different human with write-capable permission. The approval is unedited, expires within 30 minutes, and is consumed once before the signing job can access Environment secrets.

The signing job signs only a fresh canary executable, requires strict timestamped SignTool and Authenticode verification, rejects the CI test certificate, deletes the signed executable, and uploads metadata-only evidence. It does not create a tag or Release.

## Manual security disposition

GitGuardian incidents must be dispositioned in the GitGuardian dashboard after direct inspection. Record:

- detector and incident ID;
- affected historical commit and line;
- whether the value was a runtime-generated test value, fixture, or real credential;
- final-tree search result;
- rotation or revocation requirement;
- reviewer and disposition date.

Do not mark an uncertain value as a false positive. Rotate and revoke immediately if a real credential was committed. Do not rewrite shared history solely to hide a verified test fixture unless repository policy requires it.

## Actual Release

A production Release remains a separate decision after all pull requests, repository controls, canaries, and security dispositions pass. The authorization must identify the exact tag, commit, version, signing mode, and publication action. No earlier approval implicitly authorizes publication.
