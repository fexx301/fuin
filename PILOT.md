# Fūin pilot: certify your own private benchmark

This kit is for someone other than Fūin's builder. You keep a set of questions private, run two NEAR AI Cloud models on them, and publish a certificate. A third person then verifies it without seeing your questions. It takes about an hour of your time, plus waiting while the models answer. NEAR AI usage costs cents.

Please time each step and note anything confusing. The report at the end is the point of the pilot.

## 1. What you need

- macOS or Linux with [uv](https://docs.astral.sh/uv/) and [Rust](https://rustup.rs) (for `near-cli-rs`).
- A NEAR AI Cloud account and API key (cloud.near.ai). A dollar of credit is plenty for 40–60 questions.
- 40 or more questions **only you have**, each with one exact answer: a number, or a short name or term. Do **not** reuse anything public; that defeats the purpose. Small suites reveal most of their items: 20 questions reveal 16, 40 reveal 21, 60 reveal 23.

## 2. Set up (about 15 minutes)

```sh
git clone https://github.com/fexx301/fuin && cd fuin
cargo install --locked near-cli-rs
near account create-account sponsor-by-faucet-service YOURNAME.testnet autogenerate-new-keypair save-to-keychain network-config testnet create
printf 'NEARAI_API_KEY=%s\n' 'paste-your-key-here' > .env      # .env is gitignored; never commit it
```

## 3. Write the suite (your questions stay on your machine)

One JSON object per line in a file outside git, for example `private/suites/mine.jsonl` (`private/` is gitignored):

```json
{"question": "How many shards did our staging network run in March? Answer with the number only.", "answer": "6", "answer_type": "numeric"}
{"question": "Which internal service owns invoice retries? Answer with the name only.", "answer": "ledgerd", "answer_type": "exact", "accept": ["ledgerd service"]}
```

- Tell the model what form to answer in ("Answer with the number only"). The scorer is strict.
- `numeric` answers are decimal strings, and an optional `tolerance` (also a string) allows a margin.
- `exact` compares case-insensitively; list alternatives in `accept`.
- An optional `source` (for example `{"url": "..."}`) is revealed only for audited items.

## 4. Check, seal, run, commit, close, reveal

```sh
uv run --env-file .env fuin check private/suites/mine.jsonl --owner YOURNAME.testnet \
    --model Qwen/Qwen3.8-27B --model z-ai/glm-5.3-flash
uv run --env-file .env fuin seal private/suites/mine.jsonl --id pilot-1 --owner YOURNAME.testnet \
    --model Qwen/Qwen3.8-27B --model z-ai/glm-5.3-flash
uv run --env-file .env fuin run --id pilot-1 --model Qwen/Qwen3.8-27B        # resumable if interrupted
uv run --env-file .env fuin run --id pilot-1 --model z-ai/glm-5.3-flash
uv run --env-file .env fuin commit --id pilot-1 --model Qwen/Qwen3.8-27B
uv run --env-file .env fuin commit --id pilot-1 --model z-ai/glm-5.3-flash
uv run --env-file .env fuin close --id pilot-1
uv run fuin reveal --id pilot-1 --out pilot-certs
uv run fuin status --id pilot-1        # at any point: what's done and the next command
```

- **Back up `private/pilot-1/`.** Without it the round can't be revealed.
- `fuin check` tells you, before sealing, how many questions the audit will reveal (40 → 21, 60 → 23). Questions the audit picks become public; the rest stay private.
- Signing on testnet uses the key in your OS keychain. The registry contract is shared, and your benchmark ID is scoped to your account.

## 5. Hand over for verification

Send the two `pilot-certs/cert-pilot-1-*.json` files, and nothing else, to someone else. They verify either way:

- **Browser:** open the Fūin page (`site/index.html`), choose "Drop or choose your own cert.json", and pick the file.
- **Command line:** `env -u NEARAI_API_KEY uv run fuin verify pilot-certs/cert-pilot-1-*.json`

## 6. Pilot report (please fill in and send back)

| Item | Your answer |
|---|---|
| Number of questions | |
| Setup time (step 2) | |
| Writing the suite (step 3) | |
| Check → reveal, your hands-on time (step 4) | |
| Waiting for model runs | |
| NEAR AI cost (dashboard before/after) | |
| Testnet NEAR spent (wallet before/after) | |
| Verifier's result and time (browser and/or CLI) | |
| What was confusing or broke | |
| Would you use this for a real benchmark? Why or why not? | |

If the verifier's computer gets anything other than VERIFIED, include its full output. That's a useful finding, not a failure of the pilot.
