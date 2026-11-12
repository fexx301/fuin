"""Owner tooling: `fuin check` (suite + prerequisites, before sealing) and `fuin status` (where a round stands, what's next)."""

import json
import os
import re
import shutil
import subprocess
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fuin import core, near, owner, scorer
from fuin import policy as P

ITEM_KEYS = {"question", "answer", "answer_type", "accept", "tolerance", "source"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()


def check_suite(path: str) -> dict:
    """Validate a suite file. Returns {"n", "errors": [...], "warnings": [...], "items": [...]}; never raises on bad input."""
    errors, warnings, items = [], [], []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as e:
        return {"n": 0, "errors": [f"can't read {path}: {e}"], "warnings": [], "items": []}
    for ln, line in enumerate(lines, 1):
        if not line.strip():
            continue
        where = f"line {ln}"
        try:
            it = core.loads_strict(line)
        except ValueError as e:
            errors.append(f"{where}: not valid JSON ({e})"); continue
        if not isinstance(it, dict):
            errors.append(f"{where}: must be a JSON object"); continue
        extra = set(it) - ITEM_KEYS - {"request_nonce"}
        if "request_nonce" in it:
            errors.append(f"{where}: don't supply request_nonce; seal generates a secret one per item")
        if extra - {"request_nonce"}:
            warnings.append(f"{where}: unknown fields {sorted(extra - {'request_nonce'})} will be sealed and revealed with the item")
        q, a, t = it.get("question"), it.get("answer"), it.get("answer_type")
        if not (isinstance(q, str) and q.strip()):
            errors.append(f"{where}: question must be a non-empty string")
        if not (isinstance(a, str) and a.strip()):
            errors.append(f"{where}: answer must be a non-empty string (numbers as strings, e.g. \"1000\")")
        if t not in ("numeric", "exact"):
            errors.append(f"{where}: answer_type must be \"numeric\" or \"exact\"")
        if t == "numeric" and isinstance(a, str) and not core.sealed_number_ok(a):
            errors.append(f"{where}: numeric answer {a!r} is not a decimal number (finite, within 10^±{core.NUMBER_EXP})")
        if "tolerance" in it and not core.sealed_number_ok(it["tolerance"], tolerance=True):
            errors.append(f"{where}: tolerance must be a non-negative finite decimal string within 10^±{core.NUMBER_EXP}")
        if "accept" in it and not (isinstance(it["accept"], list) and all(isinstance(x, str) for x in it["accept"])):
            errors.append(f"{where}: accept must be a list of strings")
        elif t == "exact" and any(isinstance(x, str) and not scorer.extract(x) for x in [a, *it.get("accept", [])]):
            errors.append(f"{where}: an accepted answer is empty once the scorer trims it, so an empty answer would score 1")
        offered = isinstance(q, str) and isinstance(a, str) and re.search(rf"\b{re.escape(a)}\b or |\bor {re.escape(a)}\b", q, re.I)
        if isinstance(q, str) and isinstance(a, str) and len(a) >= 3 and _norm(a) and not offered and f" {_norm(a)} " in f" {_norm(q)} ":
            warnings.append(f"{where}: the answer {a!r} appears in the question text")
        if isinstance(q, str) and not re.search(r"answer with|number only|name only|one word|answer \w+ or \w+", q, re.I):
            warnings.append(f"{where}: the question doesn't say what form to answer in; the strict scorer will reject extra words")
        items.append(it)
    seen_q, seen_src = {}, {}
    for i, it in enumerate(items):
        k = _norm(str(it.get("question", "")))
        if k in seen_q:
            errors.append(f"items {seen_q[k]} and {i}: duplicate question")
        seen_q.setdefault(k, i)
        src = it.get("source", {}) if isinstance(it.get("source"), dict) else {}
        key = src.get("url") or (src.get("path"), src.get("line")) if (src.get("url") or src.get("path")) else None
        if key:
            if key in seen_src:
                warnings.append(f"items {seen_src[key]} and {i} cite the same source line: revealing one may disclose the other")
            seen_src.setdefault(key, i)
    if not items and not errors:
        errors.append("the suite has no items")
    if len(items) > core.MAX_ITEMS:  # the registry contract would seal it, but no verifier could check it (review 8)
        errors.append(f"{len(items)} items: a round can have at most {core.MAX_ITEMS:,}, the most the verifiers accept")
    return {"n": len(items), "errors": errors, "warnings": warnings, "items": items}


def disclosure(n: int, tee: bool = False, asked: bool = False) -> str:
    if asked:
        return (f"{n} items → an asked-once round reveals nothing: a TEE asks every item itself, after the seal, and scores it "
                f"there, and all {n} stay private.")
    if tee:
        return (f"{n} items → a TEE-scored round reveals nothing: every item is re-scored inside OutLayer's TEE by the sealed "
                f"scorer build, and all {n} stay private.")
    d, k = core.audit_size(n)
    p = float(core.p_detect(n, d, k)) * 100
    return (f"{n} items → the audit reveals k={k} ({100 * k / n:.1f}%) per round and keeps {n - k} hidden; "
            f"detection power {p:.2f}% for ≥{d} incorrect scores. Each later round of the same suite draws a new sample.")


# Token caps at which a model has finished a whole asked-once round inside NEAR's ~2-minute window: DeepSeek in rounds 7
# and 8, GLM and Qwen3.6-35B in round 8 (evidence/2026-11-12-round-near-dev-40-r8; NEAR's serving speed can change).
# ASK_TOO_LONG: caps measured not to fit (DeepSeek at 8,192, Nov 7). Anything else is untested and only warns.
ASK_FITS = {"deepseek-ai/DeepSeek-V4.1-Flash-1017": 4096, "z-ai/glm-5.3-flash": 4096, "Qwen/Qwen3.6-35B-A3B-FP8": 4096}
ASK_TOO_LONG = {"deepseek-ai/DeepSeek-V4.1-Flash-1017": 8192}
MODES = {"sampled": "Sampled round. You run the models. After the close, a future NEAR block picks the audited questions; those questions "
                    "and answers become public and anyone can re-score them, and the rest stay private. Still possible: re-asking a "
                    "question and committing the best answer (a printed limit).",
         "tee": "TEE-scored round. You run the models, nothing is revealed, and every answer is re-scored inside OutLayer's TEE. Only "
                "you can check your questions and answer keys. Still possible: re-asking a question and committing the best answer "
                "(a printed limit).",
         "ask": "Asked-once round. A TEE asks every question itself, after the seal, keeps one answer per question and counts every "
                "retry; nothing is revealed. Each call must finish within NEAR's ~2-minute window, which only fast models do. Still "
                "possible: sealing the same questions as a separate round."}
HOSTS = {"gist": "The encrypted round is hosted on a secret gist only while the TEE fetches it, then deleted.",
         "fastfs": "The encrypted round is hosted on FastFS: ciphertext only, but public and permanent."}


def explain(mode: str, e2ee: bool = False, host: str | None = None) -> list[str]:
    """The chosen kind of round in plain words: who calls the model, what becomes public, what stays possible."""
    out = [MODES[mode]]
    if e2ee:
        out.append("Questions and answers are encrypted end to end to each model's attested key; NEAR's gateway sees the model, "
                   "the settings, the timing and the sizes, not the text.")
    if mode != "sampled" and host:
        out.append(HOSTS[host])
    return out


def prerequisites(owner_account: str | None, models: list[str], mode: str = "sampled", host: str | None = None,
                  max_tokens: int | None = None) -> list[tuple[bool | None, str]]:
    """(ok, message) per prerequisite; ok None is a warning that doesn't block. Network checks degrade to a failed line,
    never an exception. `mode` adds what a TEE-scored or asked-once round needs before its seal."""
    out = []
    key = bool(os.environ.get("NEARAI_API_KEY")) or (Path(".env").is_file() and "NEARAI_API_KEY=" in Path(".env").read_text())
    out.append((key, "NEARAI_API_KEY set (environment or .env)" if key else "NEARAI_API_KEY missing: put it in .env and run commands with `uv run --env-file .env`"))
    cli = shutil.which("near")
    out.append((bool(cli), f"near-cli-rs found ({cli})" if cli else "near CLI missing: install near-cli-rs (cargo install near-cli-rs) to sign seal/commit/close"))
    pol = owner.attestation_policy()["models"]
    for m in models:
        out.append((m in pol, f"{m} is in the verifier's attestation policy" if m in pol else f"{m} is not in the attestation policy: its runs can't be certified"))
    try:
        reg = near.REGISTRY["account"]
        ok = near.code_hash(reg) == near.REGISTRY["code_hash"] and near.access_key_count(reg) == 0
        out.append((ok, f"registry {reg} reachable, code pinned and locked" if ok else f"registry {reg} doesn't match the pinned, locked code"))
        if owner_account:
            acct = near.rpc("query", {"request_type": "view_account", "finality": "final", "account_id": owner_account})
            bal = int(acct["amount"]) / 1e24
            need = 0.2 if mode == "sampled" else 0.5  # each TEE task attaches 0.1 NEAR and gets most of it back
            out.append((bal >= need, f"owner {owner_account} exists, {bal:.3f} NEAR" + ("" if bal >= need else f" (keep ≥{need} NEAR for gas and deposits)")))
        if mode == "ask":
            out += _ask_prerequisites(owner_account, models, max_tokens)
    except near.RpcError as e:
        out.append((False, f"NEAR RPC check failed: {str(e)[:120]}"))
    if mode != "sampled" and host == "gist":
        gh = shutil.which("gh") and subprocess.run(["gh", "auth", "status"], capture_output=True).returncode == 0
        out.append((bool(gh), "GitHub CLI signed in (the encrypted round goes to a secret gist, deleted after the TEE fetches it)" if gh
                    else "GitHub CLI missing or not signed in: run `gh auth login`, or use --host fastfs (public and permanent)"))
    return out


def _ask_prerequisites(owner_account: str | None, models: list[str], max_tokens: int | None) -> list[tuple[bool | None, str]]:
    from fuin import asker, tee
    if not asker.askers():
        return [(False, "policy/tee-v2.json pins no asker build")]
    out, project = [], asker.askers()[-1]["project"]
    if owner_account:
        stored = near.view(tee.tee_policy()["outlayer"]["contract"], "get_secrets",
                           {"accessor": {"Project": {"project_id": project}}, "profile": "nearai", "owner": owner_account}) is not None
        out.append((stored, f"a NEAR AI key is stored for the asker's project {project} (present; whether it still works shows at the first ask)"
                    if stored else f"no NEAR AI key is stored for the asker's project {project}: from a clone of github.com/fexx301/fuin run "
                    f"`uv run --env-file .env python scripts/store_asker_secret.py --project {project} --owner {owner_account}`"))
    for m in models:
        cap = ASK_FITS.get(m)
        if cap and (max_tokens or cap) <= cap:
            out.append((True, f"{m} at {max_tokens or cap:,} tokens answered within the asker's time limit when measured"))
        elif cap and max_tokens >= ASK_TOO_LONG.get(m, float("inf")):
            out.append((False, f"{m} at {max_tokens:,} tokens did not answer within the asker's time limit when measured: use --max-tokens {cap}"))
        else:
            out.append((None, f"{m}" + (f" at {max_tokens:,} tokens" if max_tokens else "") + " is not tested in an asked-once round: "
                        "a call that runs past NEAR's ~2-minute window fails and is retried, and the retries are counted"))
    return out


def zero_reveal_line(cert: dict) -> str:
    """`fuin show`'s summary for a certificate of a round that reveals nothing: TEE-scored, or asked once by a TEE."""
    b, au = cert["benchmark"], cert["benchmark"]["policy"]["audit"]
    if P.is_asked_round(b["policy"]):
        out = ((cert["run"].get("evidence") or {}).get("tee_asked") or {}).get("output") or {}
        retried = f"; {out['retried']} retried ask(s), counted" if "retried" in out else ""
        return (f"audit: none · an asked-once round reveals nothing: a TEE asked each of the {b['n']} questions itself, after the seal, "
                f"and scored it there (asker {au['asker_wasm_sha256'][:12]}… in {au['asker_project']}){retried} "
                "(fuin verify checks that evidence)")
    return (f"audit: none · a TEE-scored round reveals nothing: all {b['n']} items stay private and were re-scored inside "
            f"OutLayer's TEE by scorer {au['scorer_wasm_sha256'][:12]}… (fuin verify checks that evidence)")


PREFIX = {"key": "uv run --env-file .env fuin ", "plain": "uv run fuin ", "keyless": "env -u NEARAI_API_KEY uv run fuin "}


def render(step) -> str:
    """A next step as `fuin status` prints it. A step is (who needs what, the fuin arguments, a note) or plain guidance."""
    if step is None:
        return "nothing: the round is complete"
    if isinstance(step, str):
        return step
    kind, argv, note = step
    return PREFIX[kind] + " ".join(argv) + (f"   {note}" if note else "")


def status(bid: str, examples: str = "examples") -> list[str]:
    lines, step = progress(bid, examples)
    return lines + [f"next: {render(step)}"]


def progress(bid: str, examples: str = "examples") -> tuple[list[str], object]:
    """Where a round stands, from private state plus the chain, and the next step: `fuin status` prints it and
    `fuin evaluate` runs it, so the two can't disagree. The three kinds of round differ in who calls the model
    (`fuin run` for the owner, `fuin ask` for the TEE) and in what writes the certificates."""
    p = owner._path(bid)
    if not p.exists():
        return [f"{bid}: not sealed yet (no private/{bid}/state.json)."], (
            f"uv run fuin check SUITE.jsonl --owner YOU.testnet, then uv run --env-file .env fuin seal SUITE.jsonl --id {bid} --owner YOU.testnet --model MODEL"
            "   (add --tee to reveal nothing, or --ask to have a TEE ask every question once)")
    st = owner.load(bid)
    n, lines, nxt, tee_round, asked = len(st["items"]), [], None, P.is_tee_round(st["policy"]), P.is_asked_round(st["policy"])
    ask = lambda m, note="": ("key", ["ask", "--id", bid, "--model", m, "--host", "gist"], note)  # the preflight report needs the key
    run = lambda m: ask(m) if asked else ("key", ["run", "--id", bid, "--model", m], "")
    lines.append(f"{bid}: {n} items, owner {st['owner']}, "
                 + ("asked-once round (a TEE asks every question, nothing revealed)" if asked
                    else "private round (TEE-scored, nothing revealed)" if tee_round else f"sampled round, audit k={st['policy']['audit']['k']}"))
    if "seal" in st:
        lines.append(f"  ✓ sealed at height {st['seal']['height']} (tx {st['seal']['tx']})")
    else:
        lines.append("  ✗ seal not confirmed (the seal transaction failed or was interrupted)")
        nxt = nxt or "run the same `fuin seal` command again: it finishes the interrupted seal with the salts and nonces saved then"
    for m in st["policy"]["models"]:
        rn = st["runs"].get(m)
        if rn is None:
            lines.append(f"  · {m}: not {'asked' if asked else 'run'}"); nxt = nxt or run(m)
        elif "commit" in rn:
            c = rn["commit"]; lines.append(f"  ✓ {m}: committed run {c['run_index']}, {c['total_score']}/{n} (tx {c['tx']})"
                                           + (", asked once in a TEE" if asked and rn.get("tee_asked") else ", TEE-scored" if rn.get("tee_score")
                                              else ", not TEE-scored yet" if tee_round and not asked else ""))
        elif len(rn["rows"]) < n:
            lines.append(f"  … {m}: {len(rn['rows'])}/{n} answered, {len(rn.get('attempt_log', []))} retries logged (resumable"
                         + ("; a recorded answer is never re-asked)" if asked else ")"))
            nxt = nxt or run(m)
        elif asked and not rn.get("tee_asked"):  # every item answered, but the enclave hasn't attested the run yet
            lines.append(f"  … {m}: {n}/{n} asked, the TEE's aggregate not collected"); nxt = nxt or ask(m, "(asks nothing again; collects the aggregate)")
        elif asked and not rn.get("tee_asked_check"):
            lines.append(f"  … {m}: {n}/{n} asked, not yet checked against the seal")
            nxt = nxt or ("plain", ["ask-check", "--id", bid, "--model", m, "--host", "gist"], "")
        else:
            lines.append(f"  · {m}: {n}/{n} answered, not committed"); nxt = nxt or ("key", ["commit", "--id", bid, "--model", m], "")
    if "close" in st:
        lines.append(f"  ✓ round closed at height {st['close']['height']} (tx {st['close']['tx']})")
    elif not nxt:
        nxt = ("key", ["close", "--id", bid], "(after this no more runs can join; do it once every model you want is committed)")
    certs = sorted(Path(examples).glob(f"cert-{bid}-*.json"))
    unscored = [m for m, rn in st["runs"].items() if tee_round and not asked and "commit" in rn and not rn.get("tee_score")]
    if certs:
        lines.append(f"  ✓ certificates in {examples}/: {', '.join(c.name for c in certs)}")
        if tee_round and not st.get("tee_ground"):  # optional: answer keys checked against their cited near/docs lines
            lines.append(f"  · answer keys not grounded (optional: uv run fuin tee-ground --id {bid} --host gist --out {examples})")
        nxt = nxt or ("keyless", ["verify", *(str(c) for c in certs)], "")
    elif "close" in st:
        lines.append(f"  · no certificates in {examples}/ (if they were written elsewhere, add --out DIR)")
        if unscored:  # a private round's certificates are written once every run is re-scored in the TEE
            nxt = nxt or ("key", ["tee-score", "--id", bid, "--model", unscored[0], "--host", "gist", "--out", examples], "")
        nxt = nxt or ("plain", ["reveal", "--id", bid, "--out", examples],
                      "(writes the certificates; an asked-once round reveals nothing)" if asked
                      else "(writes the certificates; a TEE-scored round reveals nothing)" if tee_round else "(waits for a finalized block ≥ close+2)")
    return lines, nxt


def print_check(path: str, owner_account: str | None, models: list[str], tee: bool = False, mode: str | None = None,
                host: str | None = None, max_tokens: int | None = None) -> int:
    mode = mode or ("tee" if tee else "sampled")
    tee = mode != "sampled"
    res = check_suite(path)
    print(f"Suite {path}: {res['n']} items")
    for e in res["errors"]:
        print(f"  ✗ {e}")
    for w in res["warnings"]:
        print(f"  ! {w}")
    if not res["errors"]:
        print(f"  ✓ every item is well formed")
        print(f"  disclosure: {disclosure(res['n'], tee, mode == 'ask')}")
        print("  keep the suite file private (not in git); after sealing, back up private/ — without it the round can't be revealed")
    print("Prerequisites:")
    pre = prerequisites(owner_account, models, mode, host, max_tokens)
    for ok, msg in pre:
        print(f"  {'!' if ok is None else '✓' if ok else '✗'} {msg}")
    if not res["errors"]:
        from fuin import cost
        caps = {m: max_tokens or 4096 for m in models}  # 4,096 is `fuin seal`'s default cap
        print("\n".join(cost.estimate([it["question"] for it in res["items"]], caps, mode)))
    bad = bool(res["errors"]) or any(ok is False for ok, _ in pre)
    print("Ready to seal." if not bad else "Not ready: fix the ✗ lines first.")
    return 1 if bad else 0
