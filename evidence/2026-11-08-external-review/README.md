# External review, 2026-11-08

A read-only bug-and-gaps review of commit `162a8df` by another AI model, working from the code alone. None of its findings let a forged or tampered certificate pass as VERIFIED. They were cases where the verifiers disagreed, where malformed input got the wrong kind of non-verdict, or where a README claim was stronger than the check behind it.

Each finding was first reproduced on the current `main` (`77bf771`), then fixed in its own commit:

| # | Finding | Outcome | Commit |
|---|---|---|---|
| 1 | A tolerance of "Infinity" (or a huge exponent) passed `fuin check`, and the sealed Python scorer then marked any number correct; the browser and TEE scorers rejected it | **Fixed.** One rule (finite, within 10^±100, tolerance >= 0) in `fuin check` and both verifiers' form checks; fixture `infinite-tolerance` | `6e85929` |
| 2 | Malformed nested attestation evidence crashed into CAN'T CERTIFY `verifier_error` (as if a service were down); the browser said REFUSED | **Fixed.** Both form checks validate inside the reports; fixtures `malformed-event-log`, `malformed-gpu-evidence` | `d3e825a` |
| 3 | The deployment trace accepted a mutable image tag, unknown weights or revision, and an unchecked compose file | **Fixed.** Both verifiers require all four; all 20 published traces already had them | `170a5a6` |
| 4 | With two reports sharing a signing key, the trace used the first, not the accepted one | **Fixed** in both verifiers; fixture `shared-key-other-model-first` must stay VERIFIED | `b91b892` |
| 5 | NVIDIA's GPU verdict token was decoded without checking its signature, issuer, expiry or nonce | **Fixed.** ES384 against NVIDIA's published keys, plus issuer, validity window and the report's nonce | `6171516` |
| 6 | The TEE scorer cut its output at 900 bytes | **Already fixed** in scorer v8/v9: an oversized output is refused, never cut | — |
| 7 | Browser gaps: no binding of the report's model to the run's; event-log digests not compared; sampled v3 unsupported | **Fixed** (binding, digests); fixture `edited-event-digest`. Sampled v3 in the browser stays CAN'T CERTIFY `policy_unsupported`, as labelled | `b91b892` |
| 8 | The contract accepts any round size; the verifiers cap at 1,000,000 | **Fixed** in `fuin check` (the contract is locked) | `a938700` |
| 9 | A 404 for a logged compose file read as an outage | **Fixed:** CAN'T CERTIFY `deployment_untraced` in both verifiers | `2469ec4` |
| 10 | Python accepted generation settings the TEE can't rebuild | **Fixed** for TEE-scored and asked rounds, in both verifiers | `df6bed1` |
| 11 | A round id could reach outside `private/` | **Fixed** | `2c367ba` |
| 12 | Two models sharing a last name segment overwrote each other's certificate | **Fixed;** published names unchanged | `4d705a8` |
| 13 | An empty round raised an "unreachable" assertion | **Fixed:** a clear ValueError | `e41bb15` |
| 14 | The owner's receipt helper doesn't re-check signer and receiver | **Not changed.** Owner-side only: the verifier checks the owner's signed seal and commit transactions itself | — |
| 15 | A seal that fails after saving local state blocks a retry under the same id | **Not changed.** Deliberate: salts and nonces are kept so nothing sealed can be lost; use a new id | — |
| 16 | Finding the seed block scans heights one by one | **Not changed.** The first final block at close+2 is almost always within a few heights | — |
| 17 | The browser fetches Intel collateral from Phala's PCCS mirror | **Documented** in `docs/COSTS-AND-DEPENDENCIES.md`: the mirror can withhold collateral but can't forge a quote | — |

After the fixes: 153 tests pass, and 39 tamper fixtures get their expected verdicts in both verifiers.
