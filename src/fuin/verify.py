"""Credential-free certificate verifier (spec: Verifier checks and outcomes).

Outcome: REFUSED <code> if any known evidence is invalid; else CAN'T CERTIFY <code> if evidence is
unavailable or unsupported; else VERIFIED with its scope, warnings and limits.
"""

import base64
import hashlib
import requests
import yaml

from fuin import attestation, core, inference, near, owner, provenance
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


HEX = "0123456789abcdef"


def _validate(c) -> None:
    """Strict schema check: every field the verifier reads has the right type and form. Raises Refused(certificate_invalid)."""
    def need(cond, where):
        if not cond:
            raise Refused(f"certificate_invalid:{where}")

    def h32(v, where):
        need(isinstance(v, str) and len(v) == 64 and all(ch in HEX for ch in v), where)

    def num(v, where):
        need(type(v) is int and v >= 0, where)

    def txt(v, where):
        need(isinstance(v, str) and 0 < len(v) <= 4096, where)

    def b64(v, where):
        need(isinstance(v, str), where)
        try:
            base64.b64decode(v, validate=True)
        except ValueError:
            need(False, where)

    need(isinstance(c, dict) and set(c) == TOP and c.get("version") == 1, "top")
    reg, b, r, a = c["registry"], c["benchmark"], c["run"], c["audit"]
    need(all(isinstance(x, dict) for x in (reg, b, r, a)), "sections")
    for k in ("network", "account", "code_hash", "owner"):
        txt(reg.get(k), f"registry.{k}")
    txt(b.get("id"), "benchmark.id"); h32(b.get("root"), "benchmark.root"); h32(b.get("policy_hash"), "benchmark.policy_hash")
    need(type(b.get("n")) is int and 1 <= b["n"] <= 1_000_000, "benchmark.n")
    need(isinstance(b.get("models"), list) and all(isinstance(m, str) for m in b["models"]), "benchmark.models")
    need(isinstance(b.get("policy"), dict), "benchmark.policy")
    txt(b.get("seal_tx"), "benchmark.seal_tx"); num(b.get("seal_height"), "benchmark.seal_height")
    txt(r.get("model_id"), "run.model_id"); num(r.get("run_index"), "run.run_index"); h32(r.get("preflight_nonce"), "run.preflight_nonce")
    need(isinstance(r.get("model_report"), dict) and isinstance(r["model_report"].get("model_attestations"), list), "run.model_report")
    for j, rep in enumerate(r["model_report"]["model_attestations"]):
        need(isinstance(rep, dict) and isinstance(rep.get("signing_address"), str), f"run.model_report.model_attestations[{j}]")
    h32(r.get("run_root"), "run.run_root"); num(r.get("total_score"), "run.total_score")
    txt(r.get("commit_tx"), "run.commit_tx"); num(r.get("commit_height"), "run.commit_height")
    need(isinstance(r.get("items"), list), "run.items")
    for j, it in enumerate(r["items"]):
        w = f"run.items[{j}]"
        need(isinstance(it, dict), w)
        need(type(it.get("i")) is int, f"{w}.i")
        for k in ("benchmark_leaf", "req_sha256", "resp_sha256"):
            h32(it.get(k), f"{w}.{k}")
        need(type(it.get("score")) is int, f"{w}.score")
        sig = it.get("signature")
        need(isinstance(sig, dict), f"{w}.signature")
        for k in ("text", "signature", "signing_address", "signature_kind"):
            txt(sig.get(k), f"{w}.signature.{k}")
    for k in ("D", "k", "close_height", "seed_height"):
        num(a.get(k), f"audit.{k}")
    need(isinstance(a.get("target"), dict), "audit.target")
    for k in ("close_tx", "close_block_hash", "seed_block_hash"):
        txt(a.get(k), f"audit.{k}")
    h32(a.get("seed"), "audit.seed")
    need(isinstance(a.get("round_runs"), list), "audit.round_runs")
    need(isinstance(a.get("indices"), list) and all(type(x) is int for x in a["indices"]), "audit.indices")
    need(isinstance(a.get("reveals"), list), "audit.reveals")
    for j, x in enumerate(a["reveals"]):
        w = f"audit.reveals[{j}]"
        need(isinstance(x, dict) and type(x.get("i")) is int, w)
        it = x.get("item")
        need(isinstance(it, dict), f"{w}.item")
        txt(it.get("question"), f"{w}.item.question"); txt(it.get("answer"), f"{w}.item.answer")
        need(it.get("answer_type") in ("numeric", "exact"), f"{w}.item.answer_type")
        h32(it.get("request_nonce"), f"{w}.item.request_nonce"); h32(x.get("salt"), f"{w}.salt")
        b64(x.get("request_b64"), f"{w}.request_b64"); b64(x.get("response_b64"), f"{w}.response_b64")
        for k in ("proof_benchmark", "proof_run"):
            need(isinstance(x.get(k), list) and len(x[k]) <= 64, f"{w}.{k}")
            for q, hv in enumerate(x[k]):
                h32(hv, f"{w}.{k}[{q}]")


def verify(cert: dict, *, attestation_policy: dict | None = None, catalog: dict | None = None) -> dict:
    """Returns {"outcome": "VERIFIED"|"REFUSED"|"CANT_CERTIFY", "code", "checks": [...], "warnings", "scope"}.

    Order: schema → model support (local policy) → every local check → network checks. Local tampering is REFUSED even
    when a service is down; an unavailable service only defers the verdict to CAN'T CERTIFY.
    """
    checks, warnings = [], []
    pol_att = attestation_policy or owner.attestation_policy()
    deferred: list[tuple[str, str]] = []  # (CAN'T CERTIFY code, detail), reported only if nothing is REFUSED
    trace = None

    def ok(name, detail=""):
        checks.append((name, "pass", detail))

    def out(outcome, code, detail=None):
        res = {"outcome": outcome, "code": code, "checks": checks, "warnings": warnings}
        return {**res, "detail": detail} if detail else res

    def online(step):
        """Run a network step: contradictions raise Refused; an outage is deferred."""
        try:
            step()
        except (near.RpcError, requests.RequestException, RuntimeError) as e:
            deferred.append(("evidence_unavailable", str(e)[:300]))

    try:
        # A. schema
        _validate(cert)
        b, r, a = cert["benchmark"], cert["run"], cert["audit"]
        n, items = b["n"], r["items"]

        # B. model support: the verifier's own attestation policy decides; the catalog only words the reason
        if r["model_id"] not in pol_att.get("models", {}):
            try:
                tee = attestation.is_tee_model(r["model_id"], catalog)
            except (requests.RequestException, ValueError, KeyError):
                tee = None
            raise CantCertify("model_not_tee" if tee is False else "policy_unsupported")

        # C. local checks
        _req(len(items) == n and [it["i"] for it in items] == list(range(n)), "item_set_mismatch")
        _req(all(it["score"] in (0, 1) for it in items), "score_range_invalid")
        _req(r["total_score"] == sum(it["score"] for it in items), "total_score_mismatch")
        ok("rows", f"{n} items, scores in {{0,1}}, total {r['total_score']}/{n}")

        bl = [bytes.fromhex(it["benchmark_leaf"]) for it in items]
        _req(core.merkle_root(bl).hex() == b["root"], "merkle_root_mismatch")
        rl = [core.run_leaf(it["i"], bl[it["i"]], bytes.fromhex(it["req_sha256"]), bytes.fromhex(it["resp_sha256"]), it["score"]) for it in items]
        _req(core.merkle_root(rl).hex() == r["run_root"], "run_root_mismatch")
        ok("commitments", "benchmark root and run root rebuilt from all n rows")

        _req(P.policy_hash(b["policy"]) == b["policy_hash"], "policy_mismatch")
        _req(P.unsupported_reason(b["policy"], n, b["models"]) is None, "policy_mismatch")
        _req(r["model_id"] in b["policy"]["models"], "policy_mismatch")
        d, k = core.audit_size(n)
        _req((a["D"], a["k"], a["target"]) == (d, k, {"numerator": 95, "denominator": 100}), "audit_sample_mismatch")
        ok("policy", f"fuin-v1; {b['policy']['scorer']['name']} sha256 {b['policy']['scorer']['sha256'][:12]}…; k={b['policy']['audit']['k']}")

        reports = r["model_report"]["model_attestations"]
        signers = {c["signing_address"].lower() for c in reports}
        for it in items:
            sig = it["signature"]
            text = f"{r['model_id']}:{it['req_sha256']}:{it['resp_sha256']}"
            _req(sig["signature_kind"] == "provider_tee" and sig["text"] == text, "signature_text_mismatch")
            code = _check_sig_text(sig, text)
            _req(code is None, code or "")
            _req(sig["signing_address"].lower() in signers, "signer_not_attested_for_model")
        ok("signatures", f"{n}/{n} provider_tee EIP-191 signatures over model:sha256(req):sha256(resp)")

        rv = [x["i"] for x in a["reveals"]]
        _req(len(rv) == k and rv == sorted(set(rv)) and all(0 <= i < n for i in rv), "reveal_mismatch")
        scorer = P.scorer_for(b["policy"])
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
            _req(scorer.score_response(x["item"], resp) == it["score"], "score_mismatch")
        ok("reveals", f"{k}/{k} revealed items: proofs pass, exact request rebuilt, re-score matches (0 mismatches)")

        # D. network checks
        used = {it["signature"]["signing_address"].lower() for it in items}

        def attest():
            nonlocal trace
            results = [attestation.check_report(c, r["preflight_nonce"], pol_att) for c in reports if c["signing_address"].lower() in used]
            for x in results:
                if x["outcome"][0] == "refused":
                    raise Refused(x["outcome"][1])
            acc = [x for x in results if x["outcome"][0].startswith("accepted")]
            if len(acc) != 1 or len(used) != 1 or acc[0]["model"] != r["model_id"]:
                deferred.append((next((x["outcome"][1] for x in results if x["outcome"][0] == "cant_certify"), "measurement_unapproved"), ""))
                return
            if acc[0]["outcome"][0] == "accepted_with_warning":
                warnings.append(f"TCB status {acc[0]['quote_status']} advisories {acc[0]['advisories']}")
            ok("attestation", f"signer {acc[0]['signing_address']} quote {acc[0]['quote_status']}, NRAS {acc[0].get('nras_ok')}, "
               f"compose {acc[0]['compose_hash'][:12]}… under {pol_att['version']}")
            rep = next(c for c in reports if c["signing_address"].lower() in used)
            try:
                tr = provenance.trace(rep, r["preflight_nonce"], acc[0]["td"])
            except provenance.TraceInvalid as e:
                raise Refused("attestation_invalid") from e
            except (provenance.TraceUnavailable, requests.RequestException, RuntimeError, ValueError, KeyError, yaml.YAMLError) as e:
                warnings.append(f"deployment not traced: {str(e)[:120]}")
                return
            trace = tr
            svc = tr["services"]
            ok("deployment trace", f"compose-manager log (quote {tr['cm_quote_status']}) → {tr['repo']}: "
               + "; ".join(f"{x['service']} @{x['tag']} {x['file']} image …{x['image'][-12:]} weights {x['model_path'].split('/')[-1] if x['model_path'] else '?'}"
                           + (f" rev {x['model_revision'][:10]}" if x['model_revision'] else "") for x in svc[:2])
               + (f" (+{len(svc) - 2} more replicas)" if len(svc) > 2 else ""))

        rec = None

        def registry():
            nonlocal rec
            reg = cert["registry"]
            _req({kk: reg.get(kk) for kk in near.REGISTRY} == near.REGISTRY, "registry_mismatch")
            _req(near.code_hash(reg["account"]) == near.REGISTRY["code_hash"], "registry_mismatch")
            got = near.view(reg["account"], "get_benchmark", {"owner": reg["owner"], "benchmark_id": b["id"]})
            _req(got is not None, "record_mismatch")
            _req((got["root"], got["n"], got["policy_hash"], got["models"], got["seal_height"]) ==
                 (b["root"], n, b["policy_hash"], b["models"], b["seal_height"]), "record_mismatch")
            mine = [x for x in got["runs"] if x["model_id"] == r["model_id"] and x["run_index"] == r["run_index"]]
            _req(len(mine) == 1 and (mine[0]["run_root"], mine[0]["total_score"], mine[0]["commit_height"]) ==
                 (r["run_root"], r["total_score"], r["commit_height"]), "record_mismatch")
            _req(got["close_height"] == a["close_height"], "record_mismatch")
            for tx, method, h in ((b["seal_tx"], "seal", b["seal_height"]), (r["commit_tx"], "commit_run", r["commit_height"]),
                                  (a["close_tx"], "close_round", a["close_height"])):
                _req(near.tx_receipt(tx, reg["owner"], reg["account"], method)["block_height"] == h, "record_mismatch")
            _req(got["seal_height"] < r["commit_height"] < got["close_height"], "commit_order_invalid")
            if near.access_key_count(reg["account"]):
                warnings.append(f"{reg['account']} still has an access key: its code can be replaced, so records are not guaranteed append-only")
            history = sorted(x["run_index"] for x in got["runs"] if x["model_id"] == r["model_id"])
            rec = got
            ok("registry", f"{reg['account']} code {near.REGISTRY['code_hash'][:10]}…; seal {b['seal_height']} < commit {r['commit_height']} < close {a['close_height']}; committed runs for this model: {history}")

        def sample():
            if rec is None:  # registry unavailable: already deferred
                return
            close_hdr = near.block(a["close_height"])
            _req(close_hdr is not None and close_hdr["hash"] == a["close_block_hash"], "audit_sample_mismatch")
            threshold = a["close_height"] + 2
            seed_hdr = near.select_seed_block(threshold, wait_s=0)
            _req(seed_hdr["height"] == a["seed_height"] and seed_hdr["hash"] == a["seed_block_hash"], "audit_sample_mismatch")
            _req(near.check_seed_block(seed_hdr, threshold), "audit_sample_mismatch")
            ctx = owner.audit_context(cert, rec, close_hdr["hash"])
            _req(ctx["runs"] == a["round_runs"], "audit_sample_mismatch")
            seed = core.audit_seed(owner.near_b58decode(seed_hdr["hash"]), core.context_hash(ctx))
            derived = core.sample_indices(seed, n, k)
            _req(seed.hex() == a["seed"] and derived == a["indices"], "audit_sample_mismatch")
            _req(rv == derived, "reveal_mismatch")
            ok("audit sample", f"seed block {seed_hdr['height']} (first final block ≥ close+2); indices {a['indices']}")

        for step in (attest, registry, sample):
            online(step)
    except Refused as e:
        code, _, where = str(e).partition(":")
        return out("REFUSED", code, f"field {where}" if where else None)
    except CantCertify as e:
        return out("CANT_CERTIFY", str(e))
    except Exception as e:  # noqa: BLE001 — never crash, never VERIFIED on an unexpected path
        return out("CANT_CERTIFY", "verifier_error", f"{type(e).__name__}: {str(e)[:200]}")
    if deferred:
        return out("CANT_CERTIFY", deferred[0][0], deferred[0][1] or None)
    warnings.append("container image build provenance (cosign/SLSA) not verified" if trace else "image provenance not verified")
    log = r.get("evidence", {}).get("attempt_log")
    warnings.append("owner-reported failed inference attempts: " + ("not recorded" if log is None else str(len(log)))
                    + " (not verifiable; an owner could omit them)")
    p = core.p_detect(n, d, k)
    scope = (f"signature evidence verified; commitments and total consistent ({r['total_score']}/{n}); "
             f"audit passed {k}/{n} with zero mismatches; detection power {float(p) * 100:.4f}% for ≥{d} incorrect item "
             f"scores under the stated sampling assumptions (not the probability that the total is correct); "
             f"directly revealed {k}, unrevealed {n - k} (indirect disclosure, such as shared sources, is not computed here)")
    limits = LIMITS if not trace else [l if not l.startswith("Accepted configurations") else
        "Accepted configurations are recorded from NEAR's endpoints in the verifier's policy. The serving container is traced from "
        "NEAR's attested deployment log at preflight to a public compose file (image digest, weights, revision); a redeploy during "
        "the run would not show, and the image's build provenance is not verified." for l in LIMITS]
    return {"outcome": "VERIFIED", "scope": scope, "checks": checks, "warnings": warnings, "limits": limits, "trace": trace}


def _check_sig_text(sig: dict, text: str) -> str | None:
    from eth_account import Account
    from eth_account.messages import encode_defunct
    try:
        rec = Account.recover_message(encode_defunct(text=text), signature=sig["signature"])
    except (ValueError, TypeError, KeyError):
        return "bad_signature"
    return None if rec.lower() == str(sig.get("signing_address", "")).lower() else "bad_signature"
