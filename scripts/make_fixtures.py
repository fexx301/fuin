"""Build tampered certificates from a real one: one isolated mutation each, with its expected verdict.

Usage: uv run python scripts/make_fixtures.py BASE_CERT OUT_DIR [TEE_CERT [ZERO_REVEAL_CERT [GROUNDED_CERT [ASKED_CERT]]]]
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


@fixture("edited-deployment-log", "REFUSED attestation_invalid",
         "one entry of NEAR's attested compose-manager action log edited (tag changed); its hash no longer matches the quote")
def _(c):
    acts = c["run"]["model_report"]["model_attestations"][0]["compose_manager_attestation"]["actions"]
    up = next(a for a in reversed(acts) if a["action"] == "compose_up")
    up["tag"] = "v0.0.999"


@fixture("deployment-untraced", "CANT_CERTIFY deployment_untraced",
         "NEAR's compose-manager attestation removed from the model report, so the serving container can't be traced")
def _(c):
    c["run"]["model_report"]["model_attestations"][0].pop("compose_manager_attestation")


@fixture("emptied-deployment-quote", "REFUSED attestation_invalid",
         "the compose-manager attestation kept but its TDX quote replaced with an empty string")
def _(c):
    c["run"]["model_report"]["model_attestations"][0]["compose_manager_attestation"]["quote"] = ""


@fixture("malformed-evidence", "REFUSED certificate_invalid", "run.evidence (the attempt log's container) replaced with a string")
def _(c):
    c["run"]["evidence"] = "x"


@fixture("changed-audit", "REFUSED audit_sample_mismatch", "owner cherry-picks the sample: indices replaced by the first k items")
def _(c):
    k = c["audit"]["k"]
    c["audit"]["indices"] = list(range(k)) if c["audit"]["indices"] != list(range(k)) else list(range(1, k + 1))


def _sibling_run():  # another model's run in the base's round (examples/ holds every model of each round)
    for p in sorted(Path(sys.argv[1]).parent.glob("cert-*.json")):
        o = json.loads(p.read_text())
        if o["benchmark"]["id"] == base["benchmark"]["id"] and o["run"]["model_id"] != base["run"]["model_id"]:
            return o["run"]


@fixture("swapped-commit", "REFUSED record_mismatch", "commit transaction and height replaced by another model's real commit in the same round")
def _(c):
    o = _sibling_run()
    c["run"]["commit_tx"], c["run"]["commit_height"] = o["commit_tx"], o["commit_height"]


@fixture("external-model", "CANT_CERTIFY model_not_tee", "run relabelled as an external (non-TEE) gateway model")
def _(c):
    c["run"]["model_id"] = "openai/gpt-5.5"


@fixture("evidence-unavailable", "CANT_CERTIFY evidence_unavailable", "unmodified certificate; NEAR RPC unreachable",
         env={"FUIN_TESTNET_RPC": "http://127.0.0.1:9"})
def _(c):
    pass


# TEE-score fixtures: from a certificate that carries a TEE score (optional third argument), one change each
if len(sys.argv) > 3:
    import hashlib
    tee_base = json.loads(Path(sys.argv[3]).read_text())

    def tee_fixture(name, expected, why):
        def wrap(mutate):
            c = json.loads(json.dumps(tee_base))
            mutate(c["run"]["evidence"]["tee_score"])
            (out / f"{name}.json").write_text(json.dumps(c, indent=1, ensure_ascii=False) + "\n")
            fixtures.append({"file": f"{name}.json", "expected": expected, "mutation": why, "base": sys.argv[3]})
            return mutate
        return wrap

    def rehash(ev):
        ev["record"]["output_hash"] = hashlib.sha256(json.dumps(ev["output"], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()

    @tee_fixture("tee-edited-total", "REFUSED tee_score_invalid", "the TEE's reported total raised by one; no longer the output OutLayer attested")
    def _(ev):
        ev["output"]["total"] += 1

    @tee_fixture("tee-rehashed-total", "REFUSED tee_score_mismatch", "TEE total raised and the record's output hash recomputed to match; it now contradicts the committed total")
    def _(ev):
        ev["output"]["total"] += 1
        rehash(ev)

    @tee_fixture("tee-forged-task", "REFUSED tee_attestation_invalid", "OutLayer task id changed in the record; the Intel-signed quote binds the original task hash")
    def _(ev):
        ev["record"]["task_id"] += 1

    @tee_fixture("tee-unpinned-scorer", "CANT_CERTIFY tee_unapproved", "record claims a scorer build other than the one the verifier pins")
    def _(ev):
        ev["record"]["wasm_hash"] = "11" * 32

# Zero-reveal fixtures: from a TEE-scored round's certificate, which reveals nothing (optional fourth argument)
if len(sys.argv) > 4:
    zr_base = json.loads(Path(sys.argv[4]).read_text())

    def zr_fixture(name, expected, why):
        def wrap(mutate):
            c = json.loads(json.dumps(zr_base))
            mutate(c)
            (out / f"{name}.json").write_text(json.dumps(c, indent=1, ensure_ascii=False) + "\n")
            fixtures.append({"file": f"{name}.json", "expected": expected, "mutation": why, "base": sys.argv[4]})
            return mutate
        return wrap

    @zr_fixture("zero-reveal-unscored", "CANT_CERTIFY tee_score_missing", "a zero-reveal round's certificate with its TEE score removed, so nothing checks its scores")
    def _(c):
        del c["run"]["evidence"]["tee_score"]

    @zr_fixture("zero-reveal-scorer-swapped", "REFUSED tee_score_mismatch", "the TEE record names a scorer build other than the one sealed in the round's policy")
    def _(c):
        c["run"]["evidence"]["tee_score"]["record"]["wasm_hash"] = "11" * 32

# Answer-key grounding fixtures: from a certificate that carries a TEE grounding (optional fifth argument)
if len(sys.argv) > 5:
    g_base = json.loads(Path(sys.argv[5]).read_text())

    def g_fixture(name, expected, why):
        def wrap(mutate):
            c = json.loads(json.dumps(g_base))
            ev = c["run"]["evidence"]["tee_ground"]
            mutate(ev)
            (out / f"{name}.json").write_text(json.dumps(c, indent=1, ensure_ascii=False) + "\n")
            fixtures.append({"file": f"{name}.json", "expected": expected, "mutation": why, "base": sys.argv[5]})
            return mutate
        return wrap

    @g_fixture("ground-other-round", "REFUSED tee_ground_mismatch", "the grounding's benchmark root swapped for another round's, output hash recomputed: it no longer covers this round's sealed keys")
    def _(ev):
        ev["output"]["benchmark_root"] = "22" * 32
        rehash(ev)

    @g_fixture("ground-hidden-flag", "REFUSED tee_attestation_invalid", "a flagged answer key un-flagged and the count lowered, output hash recomputed; the Intel-signed quote binds the original output")
    def _(ev):
        f = bytearray.fromhex(ev["output"]["flags"])
        i = next(i for i in range(len(f) * 8) if f[i // 8] & (0x80 >> (i % 8)))
        f[i // 8] &= ~(0x80 >> (i % 8)) & 0xFF
        ev["output"]["flags"], ev["output"]["flagged"] = f.hex(), ev["output"]["flagged"] - 1
        rehash(ev)

    @g_fixture("ground-fork-commit", "CANT_CERTIFY tee_unapproved", "the grounding cites a near/docs commit the verifier doesn't pin (GitHub serves a fork's commits under near/docs too)")
    def _(ev):
        ev["output"]["commit"] = "33" * 20
        rehash(ev)

    @g_fixture("ground-unpinned-build", "CANT_CERTIFY tee_unapproved", "the grounding's record names a build the verifier doesn't pin as a grounder")
    def _(ev):
        ev["record"]["wasm_hash"] = "11" * 32


# Enclave-asked fixtures: from an asked round's certificate (optional sixth argument)
if len(sys.argv) > 6:
    a_base = json.loads(Path(sys.argv[6]).read_text())

    def a_fixture(name, expected, why):
        def wrap(mutate):
            c = json.loads(json.dumps(a_base))
            mutate(c)
            (out / f"{name}.json").write_text(json.dumps(c, indent=1, ensure_ascii=False) + "\n")
            fixtures.append({"file": f"{name}.json", "expected": expected, "mutation": why, "base": sys.argv[6]})
            return mutate
        return wrap

    @a_fixture("asked-unscored", "CANT_CERTIFY tee_asked_missing", "an enclave-asked round's certificate with its aggregate removed, so nothing shows each answer was asked once")
    def _(c):
        del c["run"]["evidence"]["tee_asked"]

    @a_fixture("asked-other-project", "REFUSED tee_asked_mismatch", "the aggregate's record names another project: the same code there has other storage, so its asks could repeat")
    def _(c):
        c["run"]["evidence"]["tee_asked"]["record"]["project_id"] = "fuin.testnet/fuin-ask-spike"

    @a_fixture("asked-total-edited", "REFUSED tee_asked_mismatch", "the aggregate's total raised and its output hash recomputed; it now contradicts the committed run")
    def _(c):
        ev = c["run"]["evidence"]["tee_asked"]
        ev["output"]["total"] += 1
        rehash(ev)

    @a_fixture("asked-unchecked", "CANT_CERTIFY tee_asked_check_missing", "the asked-check removed, so nothing shows the answers' requests were made after the seal")
    def _(c):
        del c["run"]["evidence"]["tee_asked_check"]

    @a_fixture("asked-check-edited", "REFUSED tee_asked_mismatch", "the asked-check's run root replaced and its output hash recomputed; it no longer equals the committed run")
    def _(c):
        ev = c["run"]["evidence"]["tee_asked_check"]
        ev["output"]["run_root"] = "00" * 32
        rehash(ev)

    @a_fixture("asked-hidden-retry", "REFUSED tee_attestation_invalid", "a retried ask hidden (retried 1 -> 0) with the output hash recomputed; the Intel-signed quote binds the original output")
    def _(c):
        ev = c["run"]["evidence"]["tee_asked"]
        ev["output"]["retried"] = 0
        rehash(ev)


made = {f["file"] for f in fixtures}
prev = out / "manifest.json"
kept = [f for f in json.loads(prev.read_text())["fixtures"] if f["file"] not in made] if prev.exists() else []  # e.g. answer-hint (a real round)
prev.write_text(json.dumps({"base": sys.argv[1], "fixtures": fixtures + kept}, indent=1) + "\n")
print(f"wrote {len(fixtures)} fixtures to {out}")
