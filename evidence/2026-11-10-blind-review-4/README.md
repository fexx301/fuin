# Blind review 4 (Codex, gpt-6-astra), 2026-11-10

A fresh clone of `12a6ed4`, run with no API key and no project memory, given the neutral judging prompt used for reviews 1 to 3. The verdict is in [review.md](review.md), copied as written except that links to the reviewer's local clone are shortened to repository paths. The run hit a usage limit partway and was resumed in the same session, so `scripts/review.sh` never reached its final banner; the reviewer finished the remaining certificates and fixtures itself.

**Scores:** technical 8, design 7, impact 6, originality 8, sustainability 6. Overall 7.0/10. Everything it ran held: 20 certificates and both pilot certificates VERIFIED, 39 fixtures matched, 155 Python tests, the contract and scorer tests, and the browser verifier agreed on every verdict.

## Fixed

| Finding | Change |
|---|---|
| The verifier printed the wrong limits for zero-reveal and asked rounds: three limits were picked from the list by position, and inserting the re-ask limit on Nov 7 shifted them. Rounds 4–6 printed without the re-ask limit; rounds 4–7 kept "does not prove when inference happened". | The limits are looked up by their wording, with a test (`7546d19`). Checked on a certificate of each kind of round. |
| "Refused to ask any question twice" overstated round 7, which had one counted retry. | README, page and tables say one answer per question, with every retry counted (`c96f561`). |
| `docs/LIMITS.md` had an older asked-once limit than the one printed. | It matches word for word, and the limits test now covers the asked-once, answer-key and grounded zero-reveal limits (`c96f561`). |
| The opening said every answer is "re-scored"; round 7 scores as it asks. | "scored" (`c96f561`). |
| The answer-key claim read as more than a string match. | The claim table says it is a string match in the cited line, not a check that the key is right (`c96f561`). |
| The quick check's timing was optimistic: its `uv sync` took over ten minutes. | The README and AGENTS.md say so (`c96f561`). |

## Not fixed, now a printed limit

**Overlapping asks could undercount retries.** In `ask/src/main.rs`, a task that claims a pending record re-reads it and uses the newer record for its final compare-and-set. Two asks of the same item that overlap by milliseconds could record one retry fewer than happened. Neither answer leaves the enclave until one is final, so the owner can't choose between them. The asker is locked and can't be changed: a fix needs a new asker in a new locked project and a new round. The asked-once limit, printed with every such VERIFIED, now states this (`220dc8e`).

## Not changed

- **No outside owner with their own real questions.** The pilot used script-generated questions. Still true.
- **Live-service dependencies and hand-reviewed policies.** Listed in `docs/COSTS-AND-DEPENDENCIES.md` and `MAINTAINING.md`; see `evidence/2026-11-11-attestation-policy-v10/` for one such review.
