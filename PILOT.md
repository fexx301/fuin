# Fūin pilot: certify your own private benchmark

This kit is for someone other than Fūin's builder. You keep a set of questions private, run two NEAR AI Cloud models on them, and publish a certificate. A third person then verifies it without seeing your questions. It takes about an hour of your time, plus waiting while the models answer. NEAR AI usage costs cents.

Please time each step and note anything confusing. The report at the end is the point of the pilot.

## 1. What you need

- macOS or Linux (on Windows, WSL; see the note below) with [uv](https://docs.astral.sh/uv/) and [Rust](https://rustup.rs) (for `near-cli-rs`). `cargo install` puts `near` in `~/.cargo/bin`, which must be on your `PATH` (open a new shell, or run `source "$HOME/.cargo/env"`).
- Somewhere for the testnet key. macOS Keychain works as is. On Linux, `near-cli-rs` uses the Secret Service (GNOME Keyring or KWallet) if one is running; if not (as on WSL), it prints `Failed to save the access key ... to the keychain` and saves the key to `~/.near-credentials/testnet/YOURNAME.testnet.json` instead, in plain text. Fūin signs with either.
- Network access to: NEAR AI Cloud (`cloud-api.near.ai` and the models' `*.completions.near.ai`), Intel's attestation service (`api.trustedservices.intel.com`), NVIDIA's (`nras.attestation.nvidia.com`), FastNEAR's testnet RPC (`archival-rpc.testnet.fastnear.com`), OutLayer (`testnet-api.outlayer.ai`, `test.fastfs.io`), and GitHub (`api.github.com`, `raw.githubusercontent.com`, gists). If `fuin run` stops at the preflight with `cant_certify/evidence_unavailable`, one of these was unreachable; the message names the error.
- A NEAR AI Cloud account and API key (cloud.near.ai). A dollar of credit is plenty: the outside pilot's 46 questions on two models cost $0.09.
- The [GitHub CLI](https://cli.github.com), logged in (`gh auth login`). The private round below hosts its encrypted run on a secret gist only while the TEE scorer fetches it, then deletes it.
- 40 or more questions **only you have**, each with one exact answer: a number, or a short name or term. Do **not** reuse anything public; that defeats the purpose. Take them from a task you actually care about, with answers a person wrote or checked. Questions made by a script (arithmetic, filled-in templates) run fine but say little about the models, and this pilot is about a real workload. Don't use anything confidential to your employer either: certificates are public, and a sampled round (4B) publishes a sample of its questions.

**Windows (WSL):** WSL's DNS can fail to resolve `api.trustedservices.intel.com`, which sits behind a long CNAME chain, even when Windows resolves it. Point WSL at a public resolver: put `[network]` and `generateResolvConf = false` in `/etc/wsl.conf`, write `nameserver 1.1.1.1` (or `8.8.8.8`) to `/etc/resolv.conf`, then run `wsl --shutdown` from Windows and reopen WSL.

## 2. Set up (about 15 minutes)

```sh
git clone https://github.com/fexx301/fuin && cd fuin     # or, if you were sent fuin.zip: unzip fuin.zip -d fuin && cd fuin
sudo apt-get install -y build-essential pkg-config libssl-dev libdbus-1-dev libudev-dev   # Debian or Ubuntu (WSL too) only: near-cli-rs needs them to build
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

One command does the whole round. It checks your suite and setup, says what this kind of round makes public, asks before sealing (a seal can't be undone), then runs every step and ends by verifying the certificates:

```sh
uv run --env-file .env fuin evaluate private/suites/mine.jsonl --id pilot-1 --owner YOURNAME.testnet \
    --model Qwen/Qwen3.8-27B --model z-ai/glm-5.3-flash --tee --e2ee --out pilot-certs
```

If it stops for any reason (a dropped connection, a closed laptop), run the same command again: it skips what is done and never asks a model twice. `uv run fuin status --id pilot-1 --out pilot-certs` shows where the round stands at any point. Please note each time it stopped and what the message said.

## 4B. A sampled round: a sample of the questions revealed

The same command without `--tee --e2ee`. A future NEAR block picks the audited items, and their questions and answers become public; the check at the start says how many before you confirm (40 reveal 21, 60 reveal 23).

The commands `fuin evaluate` runs, one step at a time, are listed in [docs/USE.md](docs/USE.md), if you prefer to run them yourself.

**Either way:**
- **Back up `private/pilot-1/`.** Without it the round can't be finished.
- Signing on testnet uses the key `near-cli-rs` saved (OS keychain or `~/.near-credentials`). The faucet's 10 testnet NEAR covers everything: an outside pilot's whole private round spent about 0.012. The registry contract is shared, and your benchmark ID is scoped to your account.

## 5. Hand over for verification

Make a report folder and send it, and nothing else, to **someone other than you**: a colleague, or anyone with a computer.

```sh
uv run fuin report pilot-certs/*.json --out pilot-report     # pilot-report/report.html, report.json and certs/
```

The folder holds the certificates and a page with each model's score, its 95% interval, the settings and the verification result. It holds none of your questions. Your verifier checks the certificates either way:

- **Command line:** `pip install fuin` (or `uv tool install fuin`), then `fuin verify pilot-report/certs/*.json`. No account and no key.
- **Browser:** open the [Fūin page](https://fexx301.github.io/fuin/), choose "Drop or choose your own cert.json", and pick a file from `pilot-report/certs/`.

The browser checks everything except the GPU attestation (NVIDIA's service doesn't answer browsers), so a sound certificate shows PARTLY CHECKED there; the command line checks that too and shows VERIFIED. `CAN'T CERTIFY` with `evidence_unavailable` means a service didn't answer, which is an outage, not a fault in the certificate: run it again.

## 6. Pilot report (please fill in and send back)

| Item | Your answer |
|---|---|
| Round type (4A private or 4B sampled), number of questions, models | |
| The Fūin version you ran (`git rev-parse --short HEAD`) | |
| Setup time (step 2) | |
| Writing the suite (step 3) | |
| Check → certificates, your hands-on time (step 4) | |
| Waiting for model runs | |
| NEAR AI cost (dashboard before/after) | |
| Testnet NEAR spent (wallet before/after) | |
| Each time the command stopped or failed: the message, and what got it going again | |
| Each time you needed help from Fūin's builder, and for what | |
| Who verified (their role, not their name), on what computer, the result and how long it took | |
| What was confusing | |
| What decision did the result support? (for example: which model you'd use for this task, or that neither is good enough) | |
| Would you use this for a real benchmark? Why or why not? | |

**Describe the benchmark without disclosing it** (a short paragraph each):

- **What it tests:** the kind of task and why it matters to you. No question text.
- **How you chose the questions:** where they came from, and what you left out.
- **How the answer keys were checked:** who reviewed them, and how a wrong key would have been caught.

If the verifier's computer gets anything other than VERIFIED, include its full output. That's a useful finding, not a failure of the pilot.

With your agreement, the report and the description are published in this repository as a case study, with your certificates. Your questions never are.
