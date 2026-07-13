# Production signing authorization

This control is used when a private-repository `production` Environment cannot provide an independent Required Reviewer. It does not replace branch protection, pull-request approval, Environment-scoped secrets, or explicit authorization to use production signing material.

## Security objective

The workflow requester must not be able to approve their own production-signing operation. Production secrets are exposed only to a second job after a separate human with `write`, `maintain`, or `admin` permission approves the exact current `master` commit.

## Authorization issue

Create a normal open issue whose title begins with:

```text
[Production signing authorization]
```

Record the operational reason, the exact current `master` SHA, and the intended canary run. Do not use a pull request as the authorization record.

## Approval comment

A human other than the eventual workflow requester must add an unedited comment in this exact format and field order:

```text
KAITO_PRODUCTION_SIGNING_APPROVAL_V1
repository=kaenozu/kaito
workflow=production-signing-canary
target_commit=<40-character lowercase current master SHA>
nonce=<32-character lowercase hexadecimal nonce>
expires_at=<UTC ISO-8601 timestamp no more than 30 minutes after comment creation>
decision=APPROVE
```

The approver must have `write`, `maintain`, or `admin` permission. Bot comments, self-approval, read-only reviewers, edited comments, expired approvals, reordered or extra fields, and approvals for a non-current `master` commit are rejected.

## Workflow dispatch

Run `Production signing canary` from the default branch and provide:

- confirmation: `SIGN_CANARY_WITH_PRODUCTION_CERT`
- authorization issue number
- approval comment ID
- the exact approved current `master` SHA
- the exact approved nonce

The authorization job executes the verifier from the trusted workflow commit, not from the input commit. It verifies repository state through the GitHub API and writes a consumption comment before the signing job is allowed to start.

## Single-use consumption

A successful authorization creates a comment beginning with:

```text
KAITO_PRODUCTION_SIGNING_AUTHORIZATION_CONSUMED_V1
```

The comment records the approval comment ID, nonce, target commit, requester, approver, run URL, run attempt, and consumption time. Any prior consumption of the same comment ID or nonce causes the workflow to fail closed. Global workflow concurrency serializes authorization consumption.

## Secret boundary

The authorization job has no production certificate, password, or timestamp variable. The Windows signing job is the only job attached to the `production` Environment. It checks out only the independently approved current `master` commit, signs a fresh canary executable, performs strict SignTool and Authenticode verification, deletes the signed binary, and uploads metadata-only evidence.

## Remaining administrative requirements

Before use, verify in repository settings that:

- `master` protection is active and bypass is prohibited for the release sequence;
- the `production` Environment exists;
- `WINDOWS_CERTIFICATE_BASE64` and `WINDOWS_CERTIFICATE_PASSWORD` are Environment secrets;
- `WINDOWS_TIMESTAMP_URL` is an HTTPS Environment variable;
- deployment branch or tag restrictions are configured;
- ordinary pull-request workflows cannot access production secrets;
- GitGuardian incidents have been directly dispositioned.

If no independent write-capable human exists, production signing remains blocked. The repository owner, a bot, or a successful CI run is not an independent approver.
