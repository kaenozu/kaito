# Verified Release publication

The stable release process is deliberately split into two separately authorized operations.

## Phase 1: build and verify a Draft Release

Pushing a new stable tag that points to the live `master` HEAD starts `Build signed draft Release`.

The workflow:

1. refuses any pre-existing Release for the tag;
2. requires the `production` Environment and valid Windows signing material;
3. builds and signs the executable and installer;
4. creates a brand-new Draft Release through the GitHub API;
5. uploads exactly five assets without reusing another Release;
6. redownloads every asset;
7. verifies checksums, SBOM, metadata, tag, commit, and signatures;
8. leaves the Release in Draft state.

The workflow records the exact Release ID, build run ID, tag, and commit. It contains no publication command.

## Phase 2: publish the same verified Draft Release

Dispatch `Publish verified Release` from `master` only after the exact production-signed Draft artifacts have been accepted.

Required inputs:

- confirmation: `PUBLISH_VERIFIED_RELEASE`
- tag: the exact stable tag
- target commit: the exact live `master` SHA and tag target
- Release ID: the exact Draft Release ID created in phase 1
- build run ID: the exact successful phase-1 run

The publication workflow fails closed unless all identities still match. It downloads the immutable phase-1 workflow artifact as the checksum reference, redownloads the Draft Release assets, executes the shared production verifier, and then rechecks live `master`, build-run state, Release ID, Draft state, tag, and asset count immediately before publication.

A new build, changed tag, changed `master`, changed Release, missing artifact, failed signature, or mismatched checksum requires a new release attempt. Existing Releases and tags are never reused or moved.
