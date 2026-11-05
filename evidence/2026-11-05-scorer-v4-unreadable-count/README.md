# Scorer v4: unreadable answers counted inside the TEE, 2026-11-05

**The gap it closes.** In an end-to-end-encrypted round (request template v3), the key each answer is encrypted back to travels in an unsigned header. An owner could send a different key for a chosen item, read the answer under their own key, and commit a copy that the item's salt-derived key can't open. That answer scores 0, and with scorer v3 nothing in the certificate shows it.

**The change.** For v3 rounds, scorer v4 counts the answers that came back non-empty but don't decrypt with their item's key, and puts the count (`unreadable`) in its attested output. Rounds without encryption get the same output as before.
- **Owner side:** `fuin tee-score` checks its own count against the TEE's.
- **Verifiers:** the CLI and the browser accept the count only on a v3 round, and only between 0 and n.
- **Output:** the count is printed with the TEE score, and the limit says it is counted.

**Build.** `tee/build-docker.sh` at commit `54a5b6e` gives `cd36c4868612a295a1230bf9aa8d8a93250282910b2776d9e7ac6f8098bea46a` (735,258 bytes). It is served from FastFS and is the current pin in `policy/tee-v2.json`; v2 and v3 stay accepted for the rounds that sealed them.

**Checks:**

| Check | Result |
|---|---|
| Rust: the synthetic encrypted round, one answer encrypted to another key | total 2/3, `unreadable` 1 (`tee/tests/round.rs`) |
| The same round inside OutLayer with v4 | task 22259: total 2/3, `unreadable` 1, matching Python (`tests/fixtures/tee-synthetic-evidence-v4.json`) |
| That record on a round without encryption | REFUSED `tee_score_mismatch` (`tests/test_tee.py`) |
| End-to-end rehearsal on testnet, `e2ee-rehearsal-2` (3 synthetic questions, GLM-5.3-flash) | VERIFIED: `0 unreadable answers (counted inside the TEE)` (`cert-e2ee-rehearsal-2-glm-5.3-flash.json`, `verify-output.txt`) |

**Rehearsal transactions.**
- Seal: `2JVMgFer8Wg13zyqHz7UWsbhj36aSifj7iNcKx84uRgc` (276403051).
- Commit: `vx2BKpTykroDo6xUyMSWuB5NxhpzT644UuT5ueEmBBF`.
- Close: `Gd4nEcUL662zCMcF377pbA4qd7wSa7CY4oyJHjXv74GX` (276403125).
- TEE score: `8qMMvAAeDgjpWGNS2xt8Hk4L174Mgih3E3FLoNQnneP9` (task 22261).

The certificate contains no question text: the round reveals nothing, and its questions were encrypted end to end.

**What it doesn't change.** Round 5 sealed scorer v3, so its certificates keep the limit without a count. Its owner-reported count is 0 (`../2026-11-05-round-near-dev-96-r5/`). A non-zero count doesn't by itself prove that an owner did anything wrong, but it is visible and attested.
