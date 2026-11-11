# Use Fūin on your own benchmark

## Check certificates

Install the command once, then anyone can check a certificate with no account and no key:

```sh
pip install fuin                                        # or: uv tool install fuin; puts `fuin` on your PATH, with the verifier's pinned policies
fuin verify cert.json                                  # VERIFIED, REFUSED or CAN'T CERTIFY, with every check printed
```

To check certificates in your own CI, use the GitHub Action in this repository. The step fails unless every certificate is VERIFIED; it retries once when a public service doesn't answer, and never retries a REFUSED:

```yaml
- uses: fexx301/fuin@v1
  with:
    certs: certs/*.json
```

To publish your own certified scores, run a round as below or follow [PILOT.md](../PILOT.md).

## Run a round

```sh
# put NEARAI_API_KEY in .env (gitignored); have a NEAR testnet account in near-cli-rs's keychain
uv run --env-file .env fuin check my-suite.jsonl --owner you.testnet \
    --model Qwen/Qwen3.8-27B --model z-ai/glm-5.3-flash      # validates the suite, explains disclosure, checks prerequisites
uv run --env-file .env fuin seal my-suite.jsonl --id my-bench-1 --owner you.testnet \
    --model Qwen/Qwen3.8-27B --model z-ai/glm-5.3-flash
uv run --env-file .env fuin run --id my-bench-1 --model Qwen/Qwen3.8-27B   # resumable
uv run --env-file .env fuin run --id my-bench-1 --model z-ai/glm-5.3-flash
uv run --env-file .env fuin commit --id my-bench-1 --model Qwen/Qwen3.8-27B
uv run --env-file .env fuin commit --id my-bench-1 --model z-ai/glm-5.3-flash
uv run --env-file .env fuin close --id my-bench-1
uv run fuin reveal --id my-bench-1 --out examples
uv run --env-file .env fuin tee-score --id my-bench-1 --model z-ai/glm-5.3-flash --host gist   # optional: every answer re-scored in a TEE
uv run fuin tee-ground --id my-bench-1 --host gist     # optional, once per round: every answer key checked against its cited near/docs line in a TEE
uv run fuin status --id my-bench-1      # at any point: which steps are done and the exact next command
```

To reveal nothing, seal with `--tee` (every item scored inside the TEE by the sealed scorer build; run `tee-score` for every model after `close`, and the certificates are written once all are scored). Add `--e2ee` to encrypt each question and answer end to end between you and the model's attested key, so NEAR's gateway never sees them. To have a TEE ask every question once, seal with `--ask` instead, then run `fuin ask --id my-bench-1 --model <model> --host gist` for each model before `commit`: it needs your NEAR AI key stored for the asker's project once (`uv run --env-file .env python scripts/store_asker_secret.py --project ask2.fuin.testnet/asker`), and the model must answer within the asker's time limit (DeepSeek-V4.1-Flash at a cap of 4,096 tokens does).

When NEAR redeploys a model, a run's preflight stops with no accepted attestation. `uv run --env-file .env fuin policy-update` fetches fresh reports. For any configuration whose evidence holds (Intel quote, nonce binding, RTMR3, NVIDIA's verdict) but isn't approved yet, it drafts `policy/attestation-v<N+1>.json` with the measurements and deployment trace for review. It approves nothing itself: the verifier keeps its current policy until a person points `owner.ATTESTATION_POLICY` at the reviewed file.

For a second person trying Fūin on their own private questions, [PILOT.md](../PILOT.md) is a step-by-step kit with a report form. A fellow builder ([JUICEWRLD998](https://github.com/JUICEWRLD998)) ran it unmodified on Nov 6, on Windows 11 under WSL2: a private round of 46 script-generated questions on two models. Both certificates verify on another machine. It cost him $0.09 of NEAR AI usage, and he said he'd use Fūin for a real benchmark because a private test set can hardly be gamed. Each problem he hit (WSL's DNS, build packages, the keychain, two unclear messages, a dropped request to Intel) is now fixed or documented: [evidence/2026-11-06-outside-pilot](../evidence/2026-11-06-outside-pilot/).

**If a command is interrupted,** run the same command again. `fuin seal`, `run`, `commit`, `close` and `ask` pick up where they stopped: a seal keeps its saved salts and nonces, a transaction that was already sent is looked up rather than sent twice, and an answer already recorded is never asked for again. `fuin status --id my-bench-1` shows what is done and the next command.

`fuin check` catches malformed items, duplicate questions, answers that appear in their own question, questions that don't say what form to answer in, and two items citing the same source line (revealing one can disclose the other). It also states the disclosure for your suite size, for example "60 items → reveals 23 (38.3%)" or "1,000 items → reveals 29 (2.9%)". `fuin seal` runs the same suite check and refuses a suite with errors, because a seal can't be undone.

Each suite line is `{"question", "answer", "answer_type": "numeric"|"exact", "accept"?, "tolerance"?, "source"?}`. Salts, nonces and raw bytes stay in `private/` (gitignored); back that folder up, because without it a round can't be revealed. `scripts/leak_guard.py` checks that no hidden item appears in tracked files except as its own round's reveal.
