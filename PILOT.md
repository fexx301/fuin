# Fūin pilot: certify your own private benchmark

This kit is for someone other than Fūin's builder. You keep a set of questions private, run two NEAR AI Cloud models on them, and publish a certificate. A third person then verifies it without seeing your questions. It takes about an hour of your time, plus waiting while the models answer. NEAR AI usage costs cents.

Please time each step and note anything confusing. The report at the end is the point of the pilot.

## 1. What you need

- macOS or Linux with [uv](https://docs.astral.sh/uv/) and [Rust](https://rustup.rs) (for `near-cli-rs`).
- A NEAR AI Cloud account and API key (cloud.near.ai). A dollar of credit is plenty for 40–60 questions.
- The [GitHub CLI](https://cli.github.com), logged in (`gh auth login`). The private round below hosts its encrypted run on a secret gist only while the TEE scorer fetches it, then deletes it.
- 40 or more questions **only you have**, each with one exact answer: a number, or a short name or term. Do **not** reuse anything public; that defeats the purpose. Don't use anything confidential to your employer either: certificates are public, and a sampled round (4B) publishes a sample of its questions.

## 2. Set up (about 15 minutes)

```sh
git clone https://github.com/fexx301/fuin && cd fuin     # or, if you were sent fuin.zip: unzip fuin.zip -d fuin && cd fuin
cargo install --locked near-cli-rs
near account create-account sponsor-by-faucet-service YOURNAME.testnet autogenerate-new-keypair save-to-keychain network-config testnet create
printf 'NEARAI_API_KEY=%s\n' 'paste-your-key-here' > .env      # .env is gitignored; never commit it
```

## 3. Write the suite (your questions stay on your machine)

One JSON object per line in a file outside git, for example `private/suites/mine.jsonl` (`private/` is gitignored):

```json
{"question": "How many legs does a spider have? Answer with the number only.", "answer": "8", "answer_type": "numeric"}
{"question": "Which planet is closest to the sun? Answer with the name only.", "answer": "Mercury", "answer_type": "exact", "accept": ["planet Mercury"]}
```

(These two are public knowledge, only to show the format. Yours must not be.)

- Tell the model what form to answer in ("Answer with the number only"). The scorer is strict.
- `numeric` answers are decimal strings, and an optional `tolerance` (also a string) allows a margin.
- `exact` compares case-insensitively; list alternatives in `accept`.
- An optional `source` (for example `{"url": "..."}`) is revealed only for audited items.

## 4A. A private round (recommended): nothing revealed

Every question and answer is encrypted end to end between you and each model's attested TEE key, so NEAR's gateway never sees them. Every answer is then re-scored inside OutLayer's TEE, and no question is revealed. The trade-off is that only you can see whether your questions and answers are any good.

```sh
M1=Qwen/Qwen3.8-27B; M2=z-ai/glm-5.3-flash
uv run --env-file .env fuin check private/suites/mine.jsonl --owner YOURNAME.testnet --model $M1 --model $M2 --tee
uv run --env-file .env fuin seal private/suites/mine.jsonl --id pilot-1 --owner YOURNAME.testnet --model $M1 --model $M2 --tee --e2ee
uv run --env-file .env fuin run --id pilot-1 --model $M1        # resumable if interrupted
uv run --env-file .env fuin run --id pilot-1 --model $M2
uv run --env-file .env fuin commit --id pilot-1 --model $M1
uv run --env-file .env fuin commit --id pilot-1 --model $M2
uv run --env-file .env fuin close --id pilot-1
uv run --env-file .env fuin tee-key --owner YOURNAME.testnet    # once
uv run --env-file .env fuin tee-score --id pilot-1 --model $M1 --host gist --out pilot-certs
uv run --env-file .env fuin tee-score --id pilot-1 --model $M2 --host gist --out pilot-certs   # writes both certificates
uv run fuin status --id pilot-1        # at any point: what's done and the next command
```

## 4B. A sampled round: a sample of the questions revealed

Skip `--tee --e2ee` and the two `tee-` steps. After `close`, run `uv run fuin reveal --id pilot-1 --out pilot-certs`. A future NEAR block picks the audited items, and their questions and answers become public; `fuin check` says how many before you seal (40 reveal 21, 60 reveal 23).

**Either way:**
- **Back up `private/pilot-1/`.** Without it the round can't be finished.
- Signing on testnet uses the key in your OS keychain. The faucet's testnet NEAR covers everything (each TEE score attaches 0.1 NEAR). The registry contract is shared, and your benchmark ID is scoped to your account.

## 5. Hand over for verification

Send the two `pilot-certs/cert-pilot-1-*.json` files, and nothing else, to someone else. They verify either way:

- **Browser:** open the Fūin page (`site/index.html`), choose "Drop or choose your own cert.json", and pick the file.
- **Command line:** `env -u NEARAI_API_KEY uv run fuin verify pilot-certs/cert-pilot-1-*.json`

## 6. Pilot report (please fill in and send back)

| Item | Your answer |
|---|---|
| Round type (4A private or 4B sampled) and number of questions | |
| Setup time (step 2) | |
| Writing the suite (step 3) | |
| Check → certificates, your hands-on time (step 4) | |
| Waiting for model runs | |
| NEAR AI cost (dashboard before/after) | |
| Testnet NEAR spent (wallet before/after) | |
| Verifier's result and time (browser and/or CLI) | |
| What was confusing or broke | |
| Would you use this for a real benchmark? Why or why not? | |

If the verifier's computer gets anything other than VERIFIED, include its full output. That's a useful finding, not a failure of the pilot.
