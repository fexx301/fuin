"""Build tampered certificates from a real one: one isolated mutation each, with its expected verdict.

Usage: uv run python scripts/make_fixtures.py BASE_CERT OUT_DIR
Writes OUT_DIR/<name>.json and OUT_DIR/manifest.json. Check with scripts/check_fixtures.py.
"""
import base64
import copy
import json
import sys
from pathlib import Path

from eth_account import Account
from eth_account.messages import encode_defunct

base = json.loads(Path(sys.argv[1]).read_text())
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
fixtures = []


def fixture(name, expected, why, env=None):
    def wrap(mutate):
        c = copy.deepcopy(base)
        mutate(c)
        (out / f"{name}.json").write_text(json.dumps(c, indent=1, ensure_ascii=False) + "\n")
        fixtures.append({"file": f"{name}.json", "expected": expected, "mutation": why, **({"env": env} if env else {})})
    return wrap


def first_reveal(c):
    return c["audit"]["reveals"][0]


@fixture("edited-answer", "REFUSED signature_text_mismatch", "one revealed response's answer text edited after signing")
def _(c):
    x = first_reveal(c)
    resp = json.loads(base64.b64decode(x["response_b64"]))
    resp["choices"][0]["message"]["content"] = "1000"  # bytes no longer hash to the signed resp_sha256
    x["response_b64"] = base64.b64encode(json.dumps(resp).encode()).decode()


@fixture("inflated-total", "REFUSED total_score_mismatch", "published total raised by 1; item scores unchanged")
def _(c):
    c["run"]["total_score"] += 1


@fixture("missing-item", "REFUSED item_set_mismatch", "last item row deleted")
def _(c):
    c["run"]["items"].pop()


@fixture("duplicate-item", "REFUSED item_set_mismatch", "row 1 replaced by a copy of row 0")
def _(c):
    c["run"]["items"][1] = copy.deepcopy(c["run"]["items"][0])


@fixture("out-of-range-score", "REFUSED score_range_invalid", "one item score set to 2")
def _(c):
    c["run"]["items"][0]["score"] = 2


@fixture("changed-set", "REFUSED merkle_root_mismatch", "one benchmark leaf replaced, as if the set changed after the seal")
def _(c):
    c["run"]["items"][0]["benchmark_leaf"] = "00" * 32


@fixture("altered-policy", "REFUSED policy_mismatch", "sealed policy's audit k lowered; policy hash left as sealed")
def _(c):
    c["benchmark"]["policy"]["audit"]["k"] = max(1, c["benchmark"]["policy"]["audit"]["k"] - 1)


@fixture("unattested-signer", "REFUSED signer_not_attested_for_model",
         "item 0 re-signed (validly) by a key that is not in the model's attestation reports, as if another model answered")
def _(c):
    it = c["run"]["items"][0]
    acct = Account.from_key(bytes([42]) * 32)  # throwaway key, not attested anywhere
    s = acct.sign_message(encode_defunct(text=it["signature"]["text"]))
    it["signature"] = {**it["signature"], "signature": "0x" + s.signature.hex(), "signing_address": acct.address.lower()}


@fixture("invalid-attestation", "REFUSED attestation_invalid", "one byte of the model's TDX quote signature flipped")
def _(c):
    rep = c["run"]["model_report"]["model_attestations"][0]
    q = bytearray(bytes.fromhex(rep["intel_quote"]))
    q[-100] ^= 0x01
    rep["intel_quote"] = q.hex()


@fixture("changed-audit", "REFUSED audit_sample_mismatch", "owner cherry-picks the sample: indices replaced by the first k items")
def _(c):
    k = c["audit"]["k"]
    c["audit"]["indices"] = list(range(k)) if c["audit"]["indices"] != list(range(k)) else list(range(1, k + 1))


@fixture("external-model", "CANT_CERTIFY model_not_tee", "run relabelled as an external (non-TEE) gateway model")
def _(c):
    c["run"]["model_id"] = "openai/gpt-5.5"


@fixture("evidence-unavailable", "CANT_CERTIFY evidence_unavailable", "unmodified certificate; NEAR RPC unreachable",
         env={"FUIN_TESTNET_RPC": "http://127.0.0.1:9"})
def _(c):
    pass


made = {f["file"] for f in fixtures}
prev = out / "manifest.json"
kept = [f for f in json.loads(prev.read_text())["fixtures"] if f["file"] not in made] if prev.exists() else []  # e.g. answer-hint (a real round)
prev.write_text(json.dumps({"base": sys.argv[1], "fixtures": fixtures + kept}, indent=1) + "\n")
print(f"wrote {len(fixtures)} fixtures to {out}")
