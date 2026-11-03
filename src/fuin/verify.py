"""Credential-free certificate verifier (spec: Verifier checks and outcomes).

Outcome: REFUSED <code> if any known evidence is invalid; else CAN'T CERTIFY <code> if evidence is
unavailable or unsupported; else VERIFIED with its scope, warnings and limits.
"""

import base64
import hashlib
import requests

from fuin import attestation, core, inference, near, owner
from fuin import policy as P

TOP = {"version", "registry", "benchmark", "run", "audit"}
LIMITS = [
    "Every published signature and commitment is checked; score correctness and request-policy compliance are checked on the revealed sample only.",
    "Model instances can share a key even with different configurations. Matching a signer does not identify the serving instance or prove its exact configuration.",
    "Accepted configurations are recorded from NEAR's endpoints in the verifier's policy. The accepted compose hash pins NEAR's compose-manager launcher, not the model containers; image provenance not verified.",
    "Run numbering exposes committed attempts only, not discarded API calls, private rehearsals or uncommitted runs.",
    "Sampling assumes the selected future finalized block is unpredictable and not adversarially biased (SHA-256 as a pseudorandom expander); not validator-proof randomness.",
    "Reveals permanently disclose the sampled questions and answers; later rounds grow the disclosed union.",
    "The seal precedes the result commitment; this does not prove when inference happened.",
]


class Refused(Exception):
    pass


class CantCertify(Exception):
    pass


def _req(cond, code):
    if not cond:
        raise Refused(code)


def verify(cert: dict, *, attestation_policy: dict | None = None, catalog: dict | None = None) -> dict:
    """Returns {"outcome": "VERIFIED"|"REFUSED"|"CANT_CERTIFY", "code", "checks": [...], "warnings", "scope"}."""
    checks, warnings = [], []
    pol_att = attestation_policy or owner.attestation_policy()

    def ok(name, detail=""):
        checks.append((name, "pass", detail))

    deferred: list[str] = []  # CAN'T CERTIFY codes, reported only if nothing is REFUSED
    try:
        # 1. schema, rows, score range, totals
        _req(isinstance(cert, dict) and set(cert) == TOP and cert["version"] == 1, "certificate_invalid")
        b, r, a = cert["benchmark"], cert["run"], cert["audit"]
        n, items = b["n"], r["items"]
        _req(isinstance(n, int) and n >= 1 and len(items) == n and [it["i"] for it in items] == list(range(n)), "item_set_mismatch")
        _req(all(it["score"] in (0, 1) and type(it["score"]) is int for it in items), "score_range_invalid")
        _req(r["total_score"] == sum(it["score"] for it in items), "total_score_mismatch")
        ok("rows", f"{n} items, scores in {{0,1}}, total {r['total_score']}/{n}")

        # 2. model is a TEE model at all
        if not attestation.is_tee_model(r["model_id"], catalog):
            raise CantCertify("model_not_tee")

        # 3. roots
        bl = [bytes.fromhex(it["benchmark_leaf"]) for it in items]
        _req(core.merkle_root(bl).hex() == b["root"], "merkle_root_mismatch")
        rl = [core.run_leaf(it["i"], bl[it["i"]], bytes.fromhex(it["req_sha256"]), bytes.fromhex(it["resp_sha256"]), it["score"]) for it in items]
        _req(core.merkle_root(rl).hex() == r["run_root"], "run_root_mismatch")
        ok("commitments", "benchmark root and run root rebuilt from all n rows")

        # 4. sealed policy
        _req(P.policy_hash(b["policy"]) == b["policy_hash"], "policy_mismatch")
        if P.unsupported_reason(b["policy"], n, b["models"]):
            raise Refused("policy_mismatch")
        _req(r["model_id"] in b["policy"]["models"], "policy_mismatch")
        ok("policy", f"fuin-v1; {b['policy']['scorer']['name']} sha256 {b['policy']['scorer']['sha256'][:12]}…; k={b['policy']['audit']['k']}")

        # 5. signatures (every item)
        reports = r["model_report"].get("model_attestations", [])
        signers = {c["signing_address"].lower() for c in reports}
        for it in items:
            sig = it["signature"]
            text = f"{r['model_id']}:{it['req_sha256']}:{it['resp_sha256']}"
            if sig.get("signature_kind") != "provider_tee" or sig.get("text") != text:
                raise Refused("signature_text_mismatch")
            code = _check_sig_text(sig, text)
            _req(code is None, code or "")
            _req(sig["signing_address"].lower() in signers, "signer_not_attested_for_model")
        ok("signatures", f"{n}/{n} provider_tee EIP-191 signatures over model:sha256(req):sha256(resp)")

        # 6. attestation of the signer (online: Intel PCS, NVIDIA NRAS)
        used = {it["signature"]["signing_address"].lower() for it in items}
        results = [attestation.check_report(c, r["preflight_nonce"], pol_att) for c in reports if c["signing_address"].lower() in used]
        if any(x["outcome"][0] == "refused" for x in results):
            raise Refused(next(x["outcome"][1] for x in results if x["outcome"][0] == "refused"))
        acc = [x for x in results if x["outcome"][0].startswith("accepted")]
        if len(acc) != 1 or len(used) != 1 or acc[0]["model"] != r["model_id"]:
            deferred.append(next((x["outcome"][1] for x in results if x["outcome"][0] == "cant_certify"), "measurement_unapproved"))
        else:
            if acc[0]["outcome"][0] == "accepted_with_warning":
                warnings.append(f"TCB status {acc[0]['quote_status']} advisories {acc[0]['advisories']}")
            ok("attestation", f"signer {acc[0]['signing_address']} quote {acc[0]['quote_status']}, NRAS {acc[0].get('nras_ok')}, "
               f"compose {acc[0]['compose_hash'][:12]}… under {pol_att['version']}")

        # 7. registry records (finalized RPC)
        reg = cert["registry"]
        _req({k: reg.get(k) for k in near.REGISTRY} == near.REGISTRY, "registry_mismatch")
        _req(near.code_hash(reg["account"]) == near.REGISTRY["code_hash"], "registry_mismatch")
        rec = near.view(reg["account"], "get_benchmark", {"owner": reg["owner"], "benchmark_id": b["id"]})
        _req(rec is not None, "record_mismatch")
        _req((rec["root"], rec["n"], rec["policy_hash"], rec["models"], rec["seal_height"]) ==
             (b["root"], n, b["policy_hash"], b["models"], b["seal_height"]), "record_mismatch")
        mine = [x for x in rec["runs"] if x["model_id"] == r["model_id"] and x["run_index"] == r["run_index"]]
        _req(len(mine) == 1 and (mine[0]["run_root"], mine[0]["total_score"], mine[0]["commit_height"]) ==
             (r["run_root"], r["total_score"], r["commit_height"]), "record_mismatch")
        _req(rec["close_height"] == a["close_height"], "record_mismatch")
        for tx, method, h in ((b["seal_tx"], "seal", b["seal_height"]), (r["commit_tx"], "commit_run", r["commit_height"]),
                              (a["close_tx"], "close_round", a["close_height"])):
            rc = near.tx_receipt(tx, reg["owner"], reg["account"], method)
            _req(rc["block_height"] == h, "record_mismatch")
        _req(rec["seal_height"] < r["commit_height"] < rec["close_height"], "commit_order_invalid")
        if near.access_key_count(reg["account"]):
            warnings.append(f"{reg['account']} still has an access key: its code can be replaced, so records are not guaranteed append-only")
        history = sorted(x["run_index"] for x in rec["runs"] if x["model_id"] == r["model_id"])
        ok("registry", f"{reg['account']} code {near.REGISTRY['code_hash'][:10]}…; seal {b['seal_height']} < commit {r['commit_height']} < close {a['close_height']}; committed runs for this model: {history}")

        # 8. audit sample
        d, k = core.audit_size(n)
        _req((a["D"], a["k"], a["target"]) == (d, k, {"numerator": 95, "denominator": 100}), "audit_sample_mismatch")
        close_hdr = near.block(a["close_height"])
        _req(close_hdr is not None and close_hdr["hash"] == a["close_block_hash"], "audit_sample_mismatch")
        threshold = a["close_height"] + 2
        seed_hdr = near.select_seed_block(threshold, wait_s=0)
        _req(seed_hdr["height"] == a["seed_height"] and seed_hdr["hash"] == a["seed_block_hash"], "audit_sample_mismatch")
        _req(near.check_seed_block(seed_hdr, threshold), "audit_sample_mismatch")
        ctx = owner.audit_context(cert, rec, close_hdr["hash"])
        _req(ctx["runs"] == a["round_runs"], "audit_sample_mismatch")
        seed = core.audit_seed(owner.near_b58decode(seed_hdr["hash"]), core.context_hash(ctx))
        _req(seed.hex() == a["seed"] and core.sample_indices(seed, n, k) == a["indices"], "audit_sample_mismatch")
        ok("audit sample", f"seed block {seed_hdr['height']} (first final block ≥ close+2); indices {a['indices']}")

        # 9. reveals
        _req([x["i"] for x in a["reveals"]] == a["indices"], "reveal_mismatch")
        for x in a["reveals"]:
            i, it = x["i"], items[x["i"]]
            leaf = core.benchmark_leaf(i, bytes.fromhex(x["salt"]), x["item"])
            _req(leaf == bl[i], "reveal_mismatch")
            _req(core.verify_proof(leaf, i, n, [bytes.fromhex(h) for h in x["proof_benchmark"]], bytes.fromhex(b["root"])), "reveal_mismatch")
            _req(core.verify_proof(rl[i], i, n, [bytes.fromhex(h) for h in x["proof_run"]], bytes.fromhex(r["run_root"])), "reveal_mismatch")
            req, resp = base64.b64decode(x["request_b64"]), base64.b64decode(x["response_b64"])
            _req(hashlib.sha256(req).hexdigest() == it["req_sha256"], "signature_text_mismatch")
            _req(hashlib.sha256(resp).hexdigest() == it["resp_sha256"], "signature_text_mismatch")
            expected = inference.build_request(r["model_id"], x["item"]["question"], x["item"]["request_nonce"], b["policy"]["models"][r["model_id"]])
            _req(req == expected, "request_policy_mismatch")
            _req(P.scorer_for(b["policy"]).score_response(x["item"], resp) == it["score"], "score_mismatch")
        ok("reveals", f"{k}/{k} revealed items: proofs pass, exact request rebuilt, re-score matches (0 mismatches)")
    except Refused as e:
        return {"outcome": "REFUSED", "code": str(e), "checks": checks, "warnings": warnings}
    except CantCertify as e:
        return {"outcome": "CANT_CERTIFY", "code": str(e), "checks": checks, "warnings": warnings}
    except (near.RpcError, requests.RequestException) as e:
        return {"outcome": "CANT_CERTIFY", "code": "evidence_unavailable", "detail": str(e)[:300], "checks": checks, "warnings": warnings}
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as e:
        return {"outcome": "REFUSED", "code": "certificate_invalid", "detail": repr(e)[:200], "checks": checks, "warnings": warnings}
    if deferred:
        return {"outcome": "CANT_CERTIFY", "code": deferred[0], "checks": checks, "warnings": warnings}
    warnings.append("image provenance not verified")
    p = core.p_detect(n, d, k)
    scope = (f"signature evidence verified; commitments and total consistent ({r['total_score']}/{n}); "
             f"audit passed {k}/{n} with zero mismatches; detection power {float(p) * 100:.4f}% for ≥{d} incorrect item "
             f"scores under the stated sampling assumptions; disclosed {k}, hidden {n - k}")
    return {"outcome": "VERIFIED", "scope": scope, "checks": checks, "warnings": warnings, "limits": LIMITS}


def _check_sig_text(sig: dict, text: str) -> str | None:
    from eth_account import Account
    from eth_account.messages import encode_defunct
    try:
        rec = Account.recover_message(encode_defunct(text=text), signature=sig["signature"])
    except (ValueError, TypeError, KeyError):
        return "bad_signature"
    return None if rec.lower() == str(sig.get("signing_address", "")).lower() else "bad_signature"
