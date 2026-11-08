"""Owner tooling: `fuin check` (suite + prerequisites, before sealing) and `fuin status` (where a round stands, what's next)."""

import json
import os
import re
import shutil
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


def disclosure(n: int, tee: bool = False) -> str:
    if tee:
        return (f"{n} items → a TEE-scored round reveals nothing: every item is re-scored inside OutLayer's TEE by the sealed "
                f"scorer build, and all {n} stay private.")
    d, k = core.audit_size(n)
    p = float(core.p_detect(n, d, k)) * 100
    return (f"{n} items → the audit reveals k={k} ({100 * k / n:.1f}%) per round and keeps {n - k} hidden; "
            f"detection power {p:.2f}% for ≥{d} incorrect scores. Each later round of the same suite draws a new sample.")


def prerequisites(owner_account: str | None, models: list[str]) -> list[tuple[bool, str]]:
    """(ok, message) per prerequisite. Network checks degrade to a failed line, never an exception."""
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
            out.append((bal >= 0.2, f"owner {owner_account} exists, {bal:.3f} NEAR" + ("" if bal >= 0.2 else " (keep ≥0.2 NEAR for gas and storage deposits)")))
    except near.RpcError as e:
        out.append((False, f"NEAR RPC check failed: {str(e)[:120]}"))
    return out


def status(bid: str, examples: str = "examples") -> list[str]:
    """Where a round stands, from private state plus the chain, and the next command."""
    p = owner._path(bid)
    if not p.exists():
        return [f"{bid}: not sealed yet (no private/{bid}/state.json).",
                f"next: uv run fuin check SUITE.jsonl --owner YOU.testnet, then uv run --env-file .env fuin seal SUITE.jsonl --id {bid} --owner YOU.testnet --model MODEL"]
    st = owner.load(bid)
    n, lines, nxt, tee_round = len(st["items"]), [], None, P.is_tee_round(st["policy"])
    lines.append(f"{bid}: {n} items, owner {st['owner']}, "
                 + ("private round (TEE-scored, nothing revealed)" if tee_round else f"audit k={st['policy']['audit']['k']}"))
    if "seal" in st:
        lines.append(f"  ✓ sealed at height {st['seal']['height']} (tx {st['seal']['tx']})")
    else:
        lines.append("  ✗ seal not confirmed (the seal transaction failed or was interrupted)")
        nxt = nxt or "re-run fuin seal is not possible for an existing id: inspect private state, or seal under a new --id"
    for m in st["policy"]["models"]:
        rn = st["runs"].get(m)
        if rn is None:
            lines.append(f"  · {m}: not run"); nxt = nxt or f"uv run --env-file .env fuin run --id {bid} --model {m}"
        elif "commit" in rn:
            c = rn["commit"]; lines.append(f"  ✓ {m}: committed run {c['run_index']}, {c['total_score']}/{n} (tx {c['tx']})"
                                           + (", TEE-scored" if rn.get("tee_score") else ", not TEE-scored yet" if tee_round else ""))
        elif len(rn["rows"]) < n:
            lines.append(f"  … {m}: {len(rn['rows'])}/{n} answered, {len(rn.get('attempt_log', []))} retries logged (resumable)")
            nxt = nxt or f"uv run --env-file .env fuin run --id {bid} --model {m}"
        else:
            lines.append(f"  · {m}: {n}/{n} answered, not committed"); nxt = nxt or f"uv run --env-file .env fuin commit --id {bid} --model {m}"
    if "close" in st:
        lines.append(f"  ✓ round closed at height {st['close']['height']} (tx {st['close']['tx']})")
    elif not nxt:
        nxt = f"uv run --env-file .env fuin close --id {bid}   (after this no more runs can join; do it once every model you want is committed)"
    certs = sorted(Path(examples).glob(f"cert-{bid}-*.json"))
    unscored = [m for m, rn in st["runs"].items() if tee_round and "commit" in rn and not rn.get("tee_score")]
    if certs:
        lines.append(f"  ✓ certificates in {examples}/: {', '.join(c.name for c in certs)}")
        if tee_round and not st.get("tee_ground"):  # optional: answer keys checked against their cited near/docs lines
            lines.append(f"  · answer keys not grounded (optional: uv run fuin tee-ground --id {bid} --host gist --out {examples})")
        nxt = nxt or f"env -u NEARAI_API_KEY uv run fuin verify {' '.join(str(c) for c in certs)}"
    elif "close" in st:
        lines.append(f"  · no certificates in {examples}/ (if they were written elsewhere, add --out DIR)")
        if unscored:  # a private round's certificates are written once every run is re-scored in the TEE
            nxt = nxt or f"uv run --env-file .env fuin tee-score --id {bid} --model {unscored[0]} --host gist --out {examples}"
        nxt = nxt or f"uv run fuin reveal --id {bid} --out {examples}   " + (
            "(writes the certificates; a TEE-scored round reveals nothing)" if tee_round else "(waits for a finalized block ≥ close+2)")
    lines.append(f"next: {nxt or 'nothing: the round is complete'}")
    return lines


def print_check(path: str, owner_account: str | None, models: list[str], tee: bool = False) -> int:
    res = check_suite(path)
    print(f"Suite {path}: {res['n']} items")
    for e in res["errors"]:
        print(f"  ✗ {e}")
    for w in res["warnings"]:
        print(f"  ! {w}")
    if not res["errors"]:
        print(f"  ✓ every item is well formed")
        print(f"  disclosure: {disclosure(res['n'], tee)}")
        print("  keep the suite file private (not in git); after sealing, back up private/ — without it the round can't be revealed")
    print("Prerequisites:")
    pre = prerequisites(owner_account, models)
    for ok, msg in pre:
        print(f"  {'✓' if ok else '✗'} {msg}")
    bad = bool(res["errors"]) or not all(ok for ok, _ in pre)
    print("Ready to seal." if not bad else "Not ready: fix the ✗ lines first.")
    return 1 if bad else 0
