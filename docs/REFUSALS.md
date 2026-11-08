# Refusals

The verifier's three outcomes are VERIFIED, REFUSED (the evidence is wrong, with a reason code) and CAN'T CERTIFY (evidence is missing, unsupported or a service didn't answer). Each fixture below is a real certificate with one change, and both verifiers (`fuin verify` and the browser page) must give it exactly its expected verdict:

```sh
uv run python scripts/check_fixtures.py examples/tampered/manifest.json
```

You see 39 `ok` lines. Each fixture makes one change, listed in `examples/tampered/manifest.json`, and gets exactly its expected verdict:

| Fixture | What changed | Verdict |
|---|---|---|
| edited-answer | a revealed answer edited after signing | REFUSED `signature_text_mismatch` |
| inflated-total | published total +1 | REFUSED `total_score_mismatch` |
| missing-item / duplicate-item | a row deleted / duplicated | REFUSED `item_set_mismatch` |
| out-of-range-score | a score of 2 | REFUSED `score_range_invalid` |
| changed-set | a benchmark leaf changed after the seal | REFUSED `merkle_root_mismatch` |
| altered-policy | sealed audit size lowered | REFUSED `policy_mismatch` |
| unattested-signer | an answer signed by a key that isn't the model's | REFUSED `signer_not_attested_for_model` |
| invalid-attestation | one byte of the TDX quote flipped | REFUSED `attestation_invalid` |
| edited-deployment-log | NEAR's attested deployment log edited | REFUSED `attestation_invalid` |
| emptied-deployment-quote | the deployment log's TDX quote replaced with an empty string | REFUSED `attestation_invalid` |
| malformed-evidence | the attempt log's container replaced with a string | REFUSED `certificate_invalid` |
| changed-audit | the owner cherry-picks a different sample | REFUSED `audit_sample_mismatch` |
| swapped-commit | the commit transaction pointed at another model's real commit in the same round, height included | REFUSED `record_mismatch` |
| answer-hint | a real round where the owner put the answer in the prompt; signed and committed | REFUSED `request_policy_mismatch` |
| external-model | relabelled as a non-TEE gateway model | CAN'T CERTIFY `model_not_tee` |
| deployment-untraced | NEAR's deployment attestation removed, so the serving container can't be traced | CAN'T CERTIFY `deployment_untraced` |
| tee-edited-total | the TEE's reported total raised by one | REFUSED `tee_score_invalid` |
| tee-rehashed-total | the same, with the record's output hash recomputed to match | REFUSED `tee_score_mismatch` |
| tee-forged-task | OutLayer's task id edited in the record | REFUSED `tee_attestation_invalid` |
| tee-unpinned-scorer | the record names a scorer build other than the pinned one | CAN'T CERTIFY `tee_unapproved` |
| zero-reveal-unscored | a zero-reveal round's certificate with its TEE score removed, so nothing checks its scores | CAN'T CERTIFY `tee_score_missing` |
| zero-reveal-scorer-swapped | the TEE record names a build other than the one sealed in the round's policy | REFUSED `tee_score_mismatch` |
| evidence-unavailable | NEAR RPC unreachable | CAN'T CERTIFY `evidence_unavailable` |
| infinite-tolerance | a revealed numeric item's tolerance set to Infinity, which would mark any number correct (review 1) | REFUSED `certificate_invalid` |
| malformed-event-log | an attestation report's event-log entry replaced with a string; it used to crash a later check (review 2) | REFUSED `certificate_invalid` |
| malformed-gpu-evidence | an attestation report's GPU evidence replaced with a JSON list (review 2) | REFUSED `certificate_invalid` |
| edited-event-digest | a logged RTMR3 event digest replaced; both verifiers compare each logged digest with the event (review 7) | REFUSED `attestation_invalid` |
| shared-key-other-model-first | a report for another model with the same signing key listed first; the verifier must use the accepted report (review 4), so this stays VERIFIED | stays VERIFIED |
| ground-other-round | the grounding's benchmark root swapped for another round's, output hash recomputed: it no longer covers this round's sealed keys | REFUSED `tee_ground_mismatch` |
| ground-hidden-flag | a flagged answer key un-flagged and the count lowered, output hash recomputed; the Intel-signed quote binds the original output | REFUSED `tee_attestation_invalid` |
| ground-fork-commit | the grounding cites a near/docs commit the verifier doesn't pin (GitHub serves a fork's commits under near/docs too) | CAN'T CERTIFY `tee_unapproved` |
| ground-unpinned-build | the grounding's record names a build the verifier doesn't pin as a grounder | CAN'T CERTIFY `tee_unapproved` |
| asked-unscored | an enclave-asked round's certificate with its aggregate removed, so nothing shows each answer was asked once | CAN'T CERTIFY `tee_asked_missing` |
| asked-unchecked | the asked-check removed, so nothing shows the answers' requests were made after the seal | CAN'T CERTIFY `tee_asked_check_missing` |
| asked-other-project | the aggregate's record names another project: the same code there has other storage, so its asks could repeat | REFUSED `tee_asked_mismatch` |
| asked-total-edited | the aggregate's total raised and its output hash recomputed; it now contradicts the committed run | REFUSED `tee_asked_mismatch` |
| asked-check-edited | the asked-check's run root replaced and its output hash recomputed; it no longer equals the committed run | REFUSED `tee_asked_mismatch` |
| asked-hidden-retry | a retried ask hidden (retried 1 -> 0) with the output hash recomputed; the Intel-signed quote binds the original output | REFUSED `tee_attestation_invalid` |
