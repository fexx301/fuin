# Changelog

## 1.3.0 (2026-11-12)

- **Round 8:** a counted asked-once round on the second, locked asker: 40 new private questions, three models (DeepSeek-V4.1-Flash 18, GLM-5.3-flash 16, Qwen3.6-35B 7), end-to-end encrypted, answer keys 40/40 in their cited lines. The published results are now eight rounds, 23 certificates and 2,422 answers. Evidence: `evidence/2026-11-12-round-near-dev-40-r8/`.
- **Attestation policy v11:** accepts the deployment NEAR rolled out to GLM-5.3-flash on Nov 12 (same signer and OS). Published certificates were never affected. Review: `evidence/2026-11-12-attestation-policy-v11/`.
- **`fuin check --ask`** knows that GLM-5.3-flash and Qwen3.6-35B finished an asked-once round at 4,096 tokens; a cap that was never measured is a warning, not a refusal.
- **README:** corrections from blind review 5 (`evidence/2026-11-12-blind-review-5/`), including what predates the Nov 1 start.

## 1.2.2 (2026-11-12)

- **TEE rounds delete their secret gist on an older GitHub CLI.** `gh` 2.45.0 (Ubuntu 24.04) has no `gist delete --yes`, so each `tee-score` left its ciphertext gist on the owner's account. The delete now retries without the flag, and closes stdin so a prompt fails instead of hanging. Reported and fixed by pilot user zkasuran in pull request #2.
- **Evidence:** a second outside run of the pilot kit, `evidence/2026-11-11-agriculture-pilot/`, with its own stated limits.

## 1.2.1 (2026-11-11)

Two corrections to `--max-spend`, both found by a reviewer:

- **A killed run no longer forgets a call.** Each call is noted in the round's saved state before it is sent. A run that starts and finds one records it as a failed attempt ("interrupted"), counts it at its bound, and the certificate's failed-attempt count includes it.
- **Settlement records the actual cost in full**, also when it is more than was held; later calls are refused if that passes the limit.

This changes every `fuin run`, with or without a limit: a run interrupted mid-call (Ctrl-C included) now adds one failed attempt per lost call to the certificate's owner-reported count.

Evidence: `evidence/2026-11-11-cost-limit/`.

## 1.2.0 (2026-11-11)

- **Cost bound:** `fuin check` and `fuin evaluate` print, before a seal, the most the model calls can cost at NEAR AI's catalog prices, with chain and enclave fees on their own line. A bound, not a forecast.
- **`--max-spend USD`** on `fuin evaluate`, `run` and `ask`: stops before a call could take the round's spend past the limit, counting calls in flight and failed calls at their bound, and leaves the round resumable. With a limit set and no readable price, nothing is sent.
- **`fuin cost --id ID`:** the tokens a round's signed answers used, with dollars computed at the current catalog price. Evidence: `evidence/2026-11-11-cost-limit/`.
- **README:** a short "Next" section for what isn't built.

## 1.1.0 (2026-11-11)

- **`fuin evaluate`:** one guided, resumable command for a whole round: check, an explanation of the chosen kind of round, seal, run or ask, commit, close, score, certificates, verify. It runs the step `fuin status` names, so the two can't disagree. Evidence: `evidence/2026-11-11-guided-command/`.
- **`fuin check --ask` / `--host`:** catches a missing asker key, a model or token cap that doesn't fit the asker's time limit (only where measured; anything else is a warning), and a GitHub CLI that isn't signed in.
- **`fuin report`:** a shareable HTML and JSON report for your certificates, with 95% intervals, what is and isn't comparable, and no private question. Evidence: `evidence/2026-11-11-report/`.
- **Pilot kit:** `PILOT.md` uses `fuin evaluate` and `fuin report`, and its report form asks for interventions, failures, the decision the result supported and a description of the benchmark.
- **`scripts/store_asker_secret.py --owner`:** an owner other than `fuin.testnet` can store a key for the asker's project (not yet tried by a second account).
- **Page:** a light theme and a switch in the nav; dark stays the default.
- The verifier and the certificate format are unchanged.

## 1.0.3 (2026-11-11)

- **Asker v2:** a second locked asker (`edb89964…` in `ask2.fuin.testnet/asker`) counts every attempt when asks of one item overlap, time out or restart. New asked-once rounds seal it. Round 7 is unchanged and verifies against the first asker. Evidence: `evidence/2026-11-11-asker-v2/`.
- **Limits:** the overlap sentence of the asked-once limit prints only for the first asker.

## 1.0.2 (2026-11-11)

- **Interruptions:** `fuin seal`, `commit`, `close` and `ask` can be run again after being interrupted at any point. Each transaction is signed and its hash saved before it is sent, so a receipt can't be lost and a commit can't be published twice. Live rehearsal: `evidence/2026-11-11-interruption-rehearsal/`.
- **Asked-once rounds in the CLI:** `fuin show` no longer crashes on an asked-once certificate, and `fuin status` guides such a round with `fuin ask`, not `fuin run`.
- **Wording:** answer-key and asked-once claims carry their limits beside them.

## 1.0.1 (2026-11-11)

- **Attestation policy v10:** accepts the deployments NEAR rolled out to its model CVMs between Nov 8 and Nov 11, so new rounds pass preflight again. Published certificates were never affected. Review: `evidence/2026-11-11-attestation-policy-v10/`.
- **Limits:** zero-reveal and asked-once rounds print the right limits (the re-ask limit was missing from rounds 4–6), and the asked-once limit states that overlapping asks could undercount retries. From blind review 4: `evidence/2026-11-10-blind-review-4/`.
- **Fixture check:** retries when NEAR AI's model catalog doesn't answer.

## 1.0.0 (2026-11-11)

The first public release, built at NEAR HACKATHON.

**What it does.** Fūin publishes a private benchmark result that anyone can check without an account and without the test set:
- the questions are sealed on NEAR before any model runs;
- every answer carries a signature from the model's attested TEE key on NEAR AI Cloud;
- every answer is scored inside a TEE on OutLayer.

**Three kinds of round:**
- **sampled:** a future NEAR block picks the questions to reveal;
- **TEE-scored:** nothing is revealed;
- **asked once:** a TEE in a locked OutLayer project asks each question itself, after the seal, keeps one answer per question and counts any retry, so nobody can quietly re-ask within a round.

**Also in this release:**
- **End-to-end encryption:** questions and answers can stay encrypted between the owner and the model's TEE, so NEAR's gateway never sees them.
- **Answer keys:** each key is checked inside a TEE against the docs line it cites.
- **Two verifiers that must agree:** the `fuin verify` command and a browser verifier. Both give three outcomes: VERIFIED, REFUSED with a reason code, or CAN'T CERTIFY when evidence is missing or a service is down.
- **Reproducible builds:** the TEE scorer and the asker (Docker), with their hashes pinned in `policy/tee-v2.json`.
- **Seven verified rounds:** 20 certificates, 2,302 TEE-checked answers, seven models, and 39 tamper fixtures.
- **For owners:** `fuin check`, `fuin status`, `fuin policy-update`, a GitHub Action, and `pip install fuin`.
- **Hardened after an external review** (`evidence/2026-11-08-external-review/`): stricter suite and evidence form checks, a pinned deployment trace, NVIDIA verdict tokens verified, and the browser verifier aligned with the command line.
