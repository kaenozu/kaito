# kaito v0.12.0 release candidate

## Automated implementation complete

This release candidate includes the application fixes, release hardening, v0.12.0 metadata, finalized changelog, stable upgrade E2E, and a two-phase release process.

The production process now separates:

1. building, signing, creating a new Draft Release, redownloading it, and verifying it; and
2. a separate publication workflow that binds the exact tag, commit, Draft Release ID, and successful build run before reverification and publication.

Existing tags and Releases are never moved, reused, or overwritten. The tag-triggered build workflow contains no publication command.

## Human-only gates

These gates require accountable judgment, physical interaction, or control of production identity. Automation must not substitute for them.

- Decide whether distribution is private or public, including the intended update endpoint and support commitment.
- Select and take responsibility for the production Windows signing identity, trust chain, expiration, and renewal plan.
- Have a person other than the change author independently review the exact current PR HEAD and accept responsibility for the approval. AI review may assist but is not the accountable approval required by this policy.
- Execute the complete interaction-level Windows GUI acceptance checklist against the exact packaged artifact on a supported Windows system and record tester, Windows version, artifact digest, date, and evidence.
- Inspect the exact production-signed Draft installer as an end user, including signer identity, Windows trust presentation, SmartScreen or Defender behavior, upgrade from the prior stable version, and uninstall behavior; make the product-risk decision.
- Give separate explicit authorizations for merge, production signing, stable tag creation, and public Release publication. None is implied by green CI or completion of another gate.

## Status rule

Until every human-only gate and every repository or security administration gate is recorded against the exact current HEAD, the PR remains Draft and the release decision remains pending_external_acceptance.
