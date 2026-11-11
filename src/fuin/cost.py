"""What a round's model calls cost: a bound before it starts, a spending limit while it runs, measured usage afterwards.

Three different things, never mixed:
  bound      the most a call can cost: its prompt bound plus the whole token cap, at the catalog price. Not a forecast.
  limit      `--max-spend`: a call starts only if the round's spend so far plus the bound of every call in flight stays
             within it. A finished call counts at its measured tokens; a failed one stays at its bound, because NEAR AI
             can bill a call that failed or was abandoned.
  measured   token counts from the signed answers. Dollars are those tokens at the catalog price fetched now: a
             computation, not a bill. NEAR AI's dashboard is the bill.
Prices are NEAR AI Cloud's public catalog. Chain and enclave fees are testnet NEAR and are listed apart.
"""

import base64
import json
import threading
from decimal import Decimal

import requests

from fuin import inference
from fuin import policy as P

ATTEMPTS = 3  # tries per question in one run of `fuin run` or `fuin ask`; a rerun allows three more
REGISTRY_FEE, TASK_FEE = Decimal("0.0002"), Decimal("0.003")  # testnet NEAR per call, measured: docs/COSTS-AND-DEPENDENCIES.md
MORE = "docs/COSTS-AND-DEPENDENCIES.md lists what the published rounds actually used, which was far below the cap"


def prices(models) -> dict[str, tuple[Decimal, Decimal]]:
    """USD per token (input, output) for each model, from the public catalog. Raises if a price can't be read."""
    r = requests.get(f"{inference.GATEWAY}/v1/model/list", timeout=60)
    r.raise_for_status()
    d = r.json()
    by_id = {m.get("modelId"): m for m in (d if isinstance(d, list) else d.get("models") or d.get("data") or [])}
    usd = lambda c: Decimal(c["amount"]) / (Decimal(10) ** c["scale"])
    out = {}
    for m in models:
        if m not in by_id or by_id[m]["inputCostPerToken"].get("currency") != "USD":
            raise KeyError(f"NEAR AI's catalog has no USD price for {m}")
        out[m] = (usd(by_id[m]["inputCostPerToken"]), usd(by_id[m]["outputCostPerToken"]))
    return out


def bound(question: str, max_tokens: int, price: tuple[Decimal, Decimal]) -> Decimal:
    """The most one call can cost. Prompt tokens never exceeded the question's bytes plus 23 in 2,312 saved answers
    (tests/test_cost.py re-checks the published ones), and an answer can't exceed its cap."""
    return (len(question.encode()) + 64) * price[0] + max_tokens * price[1]


def _usage(response_b64: str) -> tuple[int, int]:
    u = json.loads(base64.b64decode(response_b64)).get("usage") or {}
    return int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)


def tokens(st: dict, model: str) -> tuple[int, int, int]:
    """(answers, prompt tokens, completion tokens) measured from this run's saved, signed answers."""
    rn = st["runs"].get(model) or {}
    rows = [r for r in [*rn.get("rows", []), *rn.get("pending", {}).values()] if "response_b64" in r]
    use = [_usage(r["response_b64"]) for r in rows]
    return len(rows), sum(u[0] for u in use), sum(u[1] for u in use)


def spent(st: dict, pr: dict) -> Decimal:
    """The round's model-call spend so far, from saved state, so a rerun can't reset the limit. Finished answers at
    their measured tokens; failed attempts, and every ask of an asked-once round (whose answers the owner never sees),
    at their bound."""
    total, asked = Decimal(0), P.is_asked_round(st["policy"])
    for m, rn in st.get("runs", {}).items():
        cap, worst = st["policy"]["models"][m]["max_tokens"], lambda i: bound(st["items"][i]["item"]["question"], cap, pr[m])
        if asked:  # the enclave's count already covers the owner's failed asks of an item that got its answer
            have = {r["i"] for r in rn.get("rows", [])}
            total += sum(max(1, r.get("attempts") or 1) * worst(r["i"]) for r in rn.get("rows", []))
            total += sum(worst(x["i"]) for x in rn.get("attempt_log", []) if x.get("i") not in have)
            total += worst(rn["pending_ask"]["i"]) if rn.get("pending_ask") else 0
        else:
            _, p, c = tokens(st, m)
            total += p * pr[m][0] + c * pr[m][1] + sum(worst(x["i"]) for x in rn.get("attempt_log", []) if "i" in x)
    return total


class Budget:
    """The spending limit, shared by the worker threads: reserve a call's bound before it starts, settle it after."""

    def __init__(self, limit: Decimal, already: Decimal):
        self.limit, self.used, self._lock = limit, already, threading.Lock()

    def reserve(self, amount: Decimal) -> bool:
        with self._lock:
            if self.used + amount > self.limit:
                return False
            self.used += amount
            return True

    def settle(self, reserved: Decimal, actual: Decimal) -> None:
        with self._lock:
            self.used += min(actual, reserved) - reserved

    def stop(self, what: str) -> str:
        return (f"spending limit ${self.limit} reached: ${self.used:.4f} is spent or reserved, so {what} was not sent. "
                "Nothing is lost: run the same command again with a higher --max-spend")


def budget(st: dict, max_spend: float | None) -> tuple["Budget | None", dict | None]:
    """The limit for this run, or (None, None) without --max-spend. With a limit and no readable price it refuses to start."""
    if max_spend is None:
        return None, None
    try:
        pr = prices(st["policy"]["models"])
    except (requests.RequestException, KeyError, ValueError) as e:
        raise SystemExit(f"--max-spend is set, but NEAR AI's price list can't be read ({str(e)[:120]}), so nothing was sent. "
                         "Try again, or run without the limit.") from None
    return Budget(Decimal(str(max_spend)), spent(st, pr)), pr


def _usd(x: Decimal) -> str:
    return f"${x:.2f}" if x >= Decimal("0.005") or x == 0 else "under $0.01"


def estimate(questions: list[str], caps: dict[str, int], mode: str) -> list[str]:
    """The lines `fuin check` and `fuin evaluate` print before a seal: a bound on model spend, then chain fees apart."""
    n, m = len(questions), len(caps)
    out = ["Cost before you start (a bound, not a forecast and not a bill):"]
    try:
        pr, total = prices(caps), Decimal(0)
        out.append("  Model calls (NEAR AI Cloud, real money), at the catalog prices read just now:")
        for model, cap in caps.items():
            one = sum(bound(q, cap, pr[model]) for q in questions)
            total += one
            out.append(f"    {model}: ${pr[model][0] * 10**6:.2f} in / ${pr[model][1] * 10**6:.2f} out per million tokens; "
                       f"at most {_usd(one)} if all {n} answers used the whole {cap:,}-token cap")
        out.append(f"    Round: at most {_usd(total)} with one attempt per question. A question gets up to {ATTEMPTS} attempts each time "
                   f"the command runs, and a failed call can still be billed, so only --max-spend caps the total.")
        out.append(f"    {MORE}.")
    except (requests.RequestException, KeyError, ValueError) as e:
        out.append(f"  Model calls: prices not available right now ({str(e)[:100]}). {MORE}.")
    tasks = {"sampled": 0, "tee": m + 1, "ask": n * m + 2 * m + 1}[mode]  # +1: the in-enclave key, made once
    fee = (2 + m) * REGISTRY_FEE + tasks * TASK_FEE
    out.append(f"  Chain and enclave fees (NEAR testnet, free from the faucet): about {fee:.3f} NEAR: {2 + m} registry calls at about "
               f"{REGISTRY_FEE} each" + (f" and {tasks} TEE tasks at about {TASK_FEE} each (0.1 NEAR is attached to each task and refunded)" if tasks else ""))
    return out


def measured(st: dict) -> list[str]:
    """What the round has used so far, from its signed answers. Tokens are measured; dollars are computed."""
    out, asked = ["Measured so far (tokens from the signed answers; dollars at the catalog price read just now, not a bill):"], P.is_asked_round(st["policy"])
    try:
        pr = prices(st["policy"]["models"])
    except (requests.RequestException, KeyError, ValueError):
        pr = None
    for m, rn in st.get("runs", {}).items():
        failed = len(rn.get("attempt_log", []))
        if asked:
            sent = sum(max(1, r.get("attempts") or 1) for r in rn.get("rows", []))
            out.append(f"  {m}: not available, because an asked-once round's answers never leave the enclave; {sent} asks counted by the TEE"
                       + (f", each at most {_usd(bound('', st['policy']['models'][m]['max_tokens'], pr[m]))} plus its prompt" if pr else ""))
            continue
        k, p, c = tokens(st, m)
        usd = f" = {_usd(p * pr[m][0] + c * pr[m][1])}" if pr else " (prices not available right now)"
        out.append(f"  {m}: {k} answers, {p:,} prompt + {c:,} completion tokens{usd}"
                   + (f"; {failed} failed attempt{'' if failed == 1 else 's'} left no token count and may have been billed" if failed else ""))
    out.append("  A call still in flight when a process is killed leaves no record here. NEAR AI's dashboard is the bill.")
    return out
