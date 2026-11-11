# Maintaining Fūin

What breaks, how you'll notice, and how to fix it. Costs and every outside service are listed in [docs/COSTS-AND-DEPENDENCIES.md](docs/COSTS-AND-DEPENDENCIES.md); how the code fits together, in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## What runs on its own

| Workflow | When | What it proves |
|---|---|---|
| `reverify.yml` (`scripts/review.sh`) | 06:17 and 18:17 UTC, and by hand | Every published certificate still VERIFIES; every tamper fixture gets its verdict; the tests pass; the scorer and the locked asker rebuild to their pins; the browser verifier agrees. |
| `policy-drift.yml` | daily, 07:37 UTC | Whether NEAR has redeployed a model. Needs the repository secret `NEARAI_API_KEY`; opens one issue with a drafted policy. |
| `registry-rebuild.yml` | on a change to `contract/`, and by hand | Whether the locked registry's deployed code rebuilds from `contract/` on GitHub's macOS arm64 runner. |
| `publish.yml` | on a version tag `v*` | Builds the package and publishes it to PyPI. |
| `pages.yml` | on a change to `site/`, and by hand | Publishes the browser verifier and results page to fexx301.github.io/fuin. |

A red `reverify` run is either a service outage (the log says `evidence_unavailable`; run it again) or a real change. **It never retries a verdict.**

## When NEAR redeploys a model

You'll see a `policy-drift` issue, or an owner's `fuin run` stops at preflight with `measurement_unapproved`.

1. **Get the draft:** download the `policy-drift` artifact, or run `uv run --env-file .env fuin policy-update` yourself. It writes `policy/attestation-v<N+1>.json`, holding only configurations whose evidence holds (Intel quote, nonce binding, RTMR3 event log, NVIDIA's verdict).
2. **Review it.** For each new entry, read the notes it printed:
   - the compose hash and the deployment trace to a public `nearai/cvm-compose-files` commit;
   - whether the OS measurements (MRTD, RTMR0–2) are ones NEAR already uses;
   - the image digests.

   A new OS, or an image without build provenance, deserves a closer look and a line in the evidence.
3. **Accept it:** point `owner.ATTESTATION_POLICY` at the new file, run `uv run pytest -q` and `scripts/review.sh`, and commit with a note in `evidence/`. Old certificates keep verifying: each records the policy version its owner checked.

## When a published certificate stops verifying

- **`evidence_unavailable`:** a service didn't answer. Run it again; check the services table.
- **`measurement_unapproved` on an old certificate:** the verifier's policy no longer includes a configuration that certificate needs. Policies only ever add entries, so this means a mistake in the latest policy.
- **`tee_unapproved`:** OutLayer's worker measurements weren't approved at that execution's block, or a pin was removed from `policy/tee-v2.json`. Pins are never removed while a published certificate uses them.

## Changing the TEE scorer

1. Change `tee/`, run `cd tee && cargo test --release` and the parity checks.
2. Run `tee/build-docker.sh` twice; both builds must give the same sha256.
3. Upload it (`fuin.tee.fastfs_upload`), add it to `policy/tee-v2.json` with the commit it was built from, and make it `current`.

A round seals its scorer build, so old rounds keep theirs. `review.sh` rebuilds `current` from HEAD.

## Changing the asker

The asker runs in a project whose owner has no keys, so **it can't be changed**: that is what makes "asked once" checkable. To ship a new asker:
1. build it with `ask/build-docker.sh`, twice;
2. rehearse it in an unlocked project (its certificates are refused `tee_asked_unlocked`, as designed);
3. create a fresh account and project, store the owner's NEAR AI key with `scripts/store_asker_secret.py --project …`, and delete the account's keys;
4. pin the (build, project) pair in `tee-v2.json` with the commit it was built from.

`review.sh` rebuilds every pinned asker at its commit.

## Rules that keep certificates honest

Every change has to keep one promise: **a certificate is VERIFIED only when every check holds, REFUSED only on evidence that's actually wrong, and CAN'T CERTIFY otherwise.**
- **Both verifiers change together.** A new check goes into `src/fuin/verify.py` and `site/verify.js`, and `scripts/test_site_verifier.mjs` must still agree on every certificate and fixture.
- **Every new check gets a tamper fixture**, made by `scripts/make_fixtures.py`, with its expected verdict in `examples/tampered/manifest.json` and a row in `docs/REFUSALS.md`.
- **Sealed things are never edited.** Scorers (`scorer*.py`), attestation policies and TEE builds are added, never changed: old certificates name them.
- **Outages defer, they don't decide.** A network failure must end in CAN'T CERTIFY `evidence_unavailable`, after every offline check has run.

## Before every push

- Run `uv run python scripts/leak_guard.py`. It must print 0 leaks, because a hidden question can never reach a tracked file.
- Never commit anything under `private/`: suites, salts, keys and round state.

## Releasing

1. Update `CHANGELOG.md` and the version in `pyproject.toml`, then tag `vX.Y.Z`.
2. The `publish` workflow builds and uploads to PyPI through trusted publishing; no token is stored.
3. The GitHub Action (`action.yml`) is referenced by tag, so move `v1` when a release is compatible.
