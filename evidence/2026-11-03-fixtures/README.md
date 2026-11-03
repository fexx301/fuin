# Tamper fixtures

`scripts/make_fixtures.py` writes one isolated mutation per file plus `examples/tampered/manifest.json`; `scripts/check_fixtures.py` verifies each in a fresh process and compares with the manifest. `check-output.txt` is the recorded run.

**answer-hint** is a real round, not an edit: `scripts/make_hint_fixture.py` seals a 1-item fixture benchmark (a question outside every hidden suite), has the owner append the answer to the prompt, gets the model's signature on that hinted request, and commits it honestly on chain. Every check passes except the request rebuild → REFUSED `request_policy_mismatch`. Round: `fixture-answer-hint-2`.

`fixture-answer-hint-1` (sealed, committed and closed on testnet, Nov 3) is an **unpublished** fixture round: its question turned out to be one of the hidden 60, so its certificate was deleted before any commit. The chain holds only its hashes.
