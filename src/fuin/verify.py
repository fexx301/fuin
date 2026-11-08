"""Credential-free certificate verifier (spec: Verifier checks and outcomes).

Outcome: REFUSED <code> if any known evidence is invalid; else CAN'T CERTIFY <code> if evidence is
unavailable or unsupported; else VERIFIED with its scope, warnings and limits.
"""

import base64
import hashlib
import json
import re
import requests
import yaml

from fuin import attestation, tee, core, e2ee, inference, near, owner, provenance
from fuin import policy as P

TOP = {"version", "registry", "benchmark", "run", "audit"}
LIMITS = [
    "Every published signature and commitment is checked; score correctness and request-policy compliance are checked on the revealed sample, and on every item only when the certificate carries a TEE score.",
    "Model instances can share a key even with different configurations. Matching a signer does not identify the serving instance or prove its exact configuration.",
    "Accepted configurations are recorded from NEAR's attested reports in the verifier's policy: the application (compose hash) and the OS (MRTD, RTMR0-2), as observed, not rebuilt from source. The serving container is traced from NEAR's attested deployment log at preflight to a public compose file (image digest, weights, revision); a redeploy during the run would not show. The image's build provenance is verified where NEAR publishes it (SLSA v1 through sigstore, from a workflow in NEAR AI's GitHub organisation); other images are named in the warnings.",
    "Run numbering exposes committed attempts only, not discarded API calls, private rehearsals or uncommitted runs.",
    "An owner could send the same sealed request more than once and commit the best signed answer; every signature stays valid, so a certificate can't show that.",
    "Sampling assumes the selected future finalized block is unpredictable and not adversarially biased (SHA-256 as a pseudorandom expander); not validator-proof randomness.",
    "Reveals permanently disclose the sampled questions and answers; later rounds grow the disclosed union.",
    "The seal precedes the result commitment; this does not prove when inference happened.",
    "The registry contract is locked (no access keys), and its code rebuilds byte for byte from contract/ on macOS arm64 with the recorded toolchain (GitHub's runners: .github/workflows/registry-rebuild.yml), not on Linux; "
    "the seal and commit values are checked against the owner's signed transactions, while run numbering and the close rely on "
    "the deployed code.",
    "Each item's 0/1 score is public (it is part of the run commitment), so a certificate shows which hidden items a model "
    "answered correctly, though not what they ask.",
]
LIMIT_SAMPLING, LIMIT_REVEALS, LIMIT_TIMING = LIMITS[4], LIMITS[5], LIMITS[6]
LIMIT_RESAMPLE = next(x for x in LIMITS if x.startswith("An owner could send the same sealed request"))
ASKED_LIMIT = ("Each item was asked inside the enclave, after the seal, and its answer recorded once; that rests on OutLayer's storage "
               "not being rolled back by its operator, as every TEE result rests on Intel TDX and OutLayer. A retried ask (one whose "
               "first request ran out of time, so no answer had left the enclave) is a second draw, and the owner sets the task's time "
               "limit: a single draw per item could differ from the total by at most the retried count. An owner could still seal the "
               "same questions as another round and publish the better one: separate rounds aren't linked.")
ZERO_REVEAL_LIMIT = ("Nothing is revealed, so no one but the owner can check the questions or the expected answers: the total is "
                     "exact against the owner's sealed answer key, which is unchecked, and the choice of questions is the owner's.")
ZERO_REVEAL_GROUNDED_LIMIT = ("Nothing is revealed, so no one but the owner can check the questions; the choice of questions is the owner's. "
                              "Answer keys were checked inside a TEE only against their cited line (see the answer keys check).")
GROUND_LIMIT = ("A grounded answer key appears in the line of near/docs the owner cited; that doesn't prove it is the right answer "
                "to its question: a cited line can contain a wrong value, and a short key (a number, a word) can appear in a line by chance. Flagged keys were not checked. "
                "The flags show which hidden items were flagged, not what they ask; GitHub saw which near/docs files the round cites.")
SEAL_BOUND_LIMIT = ("Request nonces are bound to the seal block's hash, so no signed answer predates the seal; answers between the "
                    "seal and the commitment are not individually timestamped.")
E2EE_LIMIT = ("Questions and answers were end-to-end encrypted to the model's attested key; NEAR's gateway still saw the model, "
              "the generation settings, the nonce, the timing and the sizes.")
E2EE_KEY_LIMIT = ("The key each answer is encrypted back to travels in an unsigned header, so an owner could have chosen answers "
                  "encrypted to another key and commit them unreadable (each scores 0): a total could be lowered without the "
                  "certificate showing it.")
E2EE_KEY_LIMIT_COUNTED = ("The key each answer is encrypted back to travels in an unsigned header, so an owner could have chosen "
                          "answers encrypted to another key and commit them unreadable (each scores 0); the TEE scorer counts "
                          "such answers, and the count is printed with the TEE score.")


class Refused(Exception):
    pass


class CantCertify(Exception):
    pass


def _req(cond, code):
    if not cond:
        raise Refused(code)


HEX = "0123456789abcdef"


def _hex(v) -> bool:
    """A hex string of whole bytes (either case), as bytes.fromhex reads it."""
    return isinstance(v, str) and len(v) % 2 == 0 and re.fullmatch(r"[0-9a-fA-F]*", v) is not None


def _json_obj(v):
    """A JSON object given as a dict or as JSON text; None if it isn't one."""
    if isinstance(v, dict):
        return v
    try:
        return json.loads(v) if isinstance(v, str) else None
    except ValueError:
        return None


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
    need(type(b.get("n")) is int and 1 <= b["n"] <= core.MAX_ITEMS, "benchmark.n")
    need(isinstance(b.get("models"), list) and all(isinstance(m, str) for m in b["models"]), "benchmark.models")
    need(isinstance(b.get("policy"), dict), "benchmark.policy")
    txt(b.get("seal_tx"), "benchmark.seal_tx"); num(b.get("seal_height"), "benchmark.seal_height")
    txt(r.get("model_id"), "run.model_id"); num(r.get("run_index"), "run.run_index"); h32(r.get("preflight_nonce"), "run.preflight_nonce")
    need(isinstance(r.get("model_report"), dict) and isinstance(r["model_report"].get("model_attestations"), list), "run.model_report")
    for j, rep in enumerate(r["model_report"]["model_attestations"]):
        w = f"run.model_report.model_attestations[{j}]"
        need(isinstance(rep, dict), w)
        for k in ("signing_address", "model_name", "intel_quote", "request_nonce"):  # every field the checks below read
            need(isinstance(rep.get(k), str), f"{w}.{k}")
        need(isinstance(rep.get("event_log"), list) and isinstance(rep.get("nvidia_payload"), (str, dict)), w)
        info = rep.get("info")
        need(isinstance(info, dict) and isinstance(info.get("tcb_info"), dict) and isinstance(info["tcb_info"].get("app_compose"), str),
             f"{w}.info.tcb_info.app_compose")
        # nested evidence too, so malformed input is refused here rather than crashing a later check (review 2)
        need(re.fullmatch(r"0x[0-9a-fA-F]{40}", rep["signing_address"]) is not None, f"{w}.signing_address")
        need(_hex(rep["intel_quote"]), f"{w}.intel_quote")
        need(len(rep["event_log"]) <= 1000, f"{w}.event_log")
        for q, e in enumerate(rep["event_log"]):
            need(isinstance(e, dict) and type(e.get("imr")) is int and type(e.get("event_type")) is int and isinstance(e.get("event"), str)
                 and _hex(e.get("event_payload")) and (e.get("digest") is None or _hex(e["digest"])), f"{w}.event_log[{q}]")
        need(isinstance(_json_obj(rep["nvidia_payload"]), dict), f"{w}.nvidia_payload")
        need(isinstance(_json_obj(info["tcb_info"]["app_compose"]), dict), f"{w}.info.tcb_info.app_compose")
    h32(r.get("run_root"), "run.run_root"); num(r.get("total_score"), "run.total_score")
    txt(r.get("commit_tx"), "run.commit_tx"); num(r.get("commit_height"), "run.commit_height")
    ev = r.get("evidence", {})
    need(isinstance(ev, dict) and (ev.get("attempt_log") is None or isinstance(ev["attempt_log"], list)), "run.evidence")
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
    txt(b.get("seal_block_hash"), "benchmark.seal_block_hash")
    tee_round = P.is_tee_round(b["policy"])  # a zero-reveal round has no sample, so no seed fields
    for k in ("k", "close_height") + (() if tee_round else ("D", "seed_height")):
        num(a.get(k), f"audit.{k}")
    for k in ("close_tx", "close_block_hash") + (() if tee_round else ("seed_block_hash",)):
        txt(a.get(k), f"audit.{k}")
    if not tee_round:
        need(isinstance(a.get("target"), dict), "audit.target")
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
        if it["answer_type"] == "numeric":  # finite and within 10^±100, as all three scorers can read it (core.sealed_number_ok)
            need(core.sealed_number_ok(it["answer"]), f"{w}.item.answer")
            need("tolerance" not in it or core.sealed_number_ok(it["tolerance"], tolerance=True), f"{w}.item.tolerance")
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
    counted = {}  # an end-to-end-encrypted run's unreadable answers, when its TEE scorer attests the count
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
                is_tee = attestation.is_tee_model(r["model_id"], catalog)
            except (requests.RequestException, ValueError, KeyError):
                is_tee = None
            raise CantCertify("model_not_tee" if is_tee is False else "policy_unsupported")

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
        tee_round, asked = P.is_tee_round(b["policy"]), P.is_asked_round(b["policy"])
        if tee_round:  # zero-reveal: no sample at all; every item is re-scored (or asked and scored) in the TEE instead
            d, k = 0, 0
            _req(a.get("mode") == b["policy"]["audit"]["mode"] and a["k"] == 0 and a["indices"] == [] and a["reveals"] == [], "audit_sample_mismatch")
            pa = b["policy"]["audit"]
            how = (f"asked once per item inside the TEE by asker {pa['asker_wasm_sha256'][:12]}… in {pa['asker_project']}" if asked
                   else f"TEE-scored by scorer {pa['scorer_wasm_sha256'][:12]}…")
            ok("policy", f"fuin-v1; {b['policy']['scorer']['name']} sha256 {b['policy']['scorer']['sha256'][:12]}…; {how}, nothing revealed; "
                         f"{b['policy']['request']['template']}" + (" (end-to-end encrypted)" if P.is_e2ee(b["policy"]) else ""))
        else:
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
            pub64 = None
            if P.is_e2ee(b["policy"]):  # v3: the question was encrypted to the signer's attested key; re-encrypt it from the salt
                att = next((c for c in r["model_report"]["model_attestations"]
                            if c["signing_address"].lower() == it["signature"]["signing_address"].lower()), None)
                try:
                    pub64 = e2ee.model_pub(att)
                except (ValueError, KeyError, TypeError) as e:
                    raise Refused("attestation_invalid") from e
            expected, _ = inference.sealed_request(b["policy"], r["model_id"], x, b["seal_block_hash"], pub64)
            _req(req == expected, "request_policy_mismatch")
            readable = e2ee.decrypted_response(resp, bytes.fromhex(x["salt"]), r["model_id"]) if pub64 else resp
            _req(scorer.score_response(x["item"], readable) == it["score"], "score_mismatch")
        ok("reveals", "none: a TEE-scored round reveals nothing; every item is re-scored inside the TEE (below)" if tee_round
           else f"{k}/{k} revealed items: proofs pass, exact request rebuilt, re-score matches (0 mismatches)")

        tee_ev, tee_info = (r.get("evidence") or {}).get("tee_score"), None
        if tee_round and not asked and tee_ev is None:
            deferred.append(("tee_score_missing", "the sealed policy promises a TEE score and the certificate carries none"))
        asked_ev, asked_info = (r.get("evidence") or {}).get("tee_asked"), None
        if asked and asked_ev is None:
            deferred.append(("tee_asked_missing", "the sealed policy promises enclave-asked answers and the certificate carries no aggregate"))
        if asked and asked_ev is not None:
            try:
                asked_info = tee.check_asked_local(asked_ev, cert)
            except tee.TeeRefused as e:
                raise Refused(str(e)) from e
            except tee.TeeUnapproved as e:
                deferred.append((str(e), "the asker build or its project is not one this verifier pins"))
        check_ev, check_info = (r.get("evidence") or {}).get("tee_asked_check"), None
        if asked and check_ev is None:
            deferred.append(("tee_asked_check_missing", "nothing shows the asked answers' requests were made after the seal"))
        if asked and check_ev is not None:
            try:
                check_info = tee.check_asked_check_local(check_ev, cert)
            except tee.TeeRefused as e:
                raise Refused(str(e)) from e
            except tee.TeeUnapproved as e:
                deferred.append((str(e), "the asked-check's scorer build is not one this verifier pins"))
        if tee_ev is not None:  # optional: every item re-scored inside a TEE (fuin/tee.py); local half first
            try:
                tee_info = tee.check_local(tee_ev, cert)
            except tee.TeeRefused as e:
                raise Refused(str(e)) from e
            except tee.TeeUnapproved as e:
                deferred.append((str(e), "the TEE scorer build is not the one this verifier pins"))
        ground_ev, ground_info = (r.get("evidence") or {}).get("tee_ground"), None
        if ground_ev is not None:  # optional: every answer key checked against its cited near/docs line inside a TEE
            try:
                ground_info = tee.check_ground_local(ground_ev, cert)
            except tee.TeeRefused as e:
                raise Refused(str(e)) from e
            except tee.TeeUnapproved as e:
                deferred.append((str(e), "the grounding build, or the near/docs commit it cites, is not one this verifier pins"))

        # D. network checks
        used = {it["signature"]["signing_address"].lower() for it in items}

        def attest():
            nonlocal trace
            results = [attestation.check_report(c, r["preflight_nonce"], pol_att) for c in reports if str(c.get("signing_address", "")).lower() in used]
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
            # the accepted report itself, not the first with this signer: instances can share a key (review 4)
            rep = next(c for c in reports if c["signing_address"].lower() == acc[0]["signing_address"].lower() and c["model_name"] == r["model_id"])
            try:
                tr = provenance.trace(rep, r["preflight_nonce"], acc[0]["td"])
            except provenance.TraceInvalid as e:
                raise Refused("attestation_invalid") from e
            except (requests.RequestException, RuntimeError) as e:  # GitHub or Intel unreachable
                deferred.append(("evidence_unavailable", f"deployment trace: {str(e)[:200]}"))
                return
            except (provenance.TraceUnavailable, ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError) as e:  # VERIFIED requires the trace; a compose file that isn't a mapping is no trace
                deferred.append(("deployment_untraced", str(e)[:200]))
                return
            trace = tr
            svc = tr["services"]
            ok("deployment trace", f"compose-manager log (quote {tr['cm_quote_status']}) → {tr['repo']}: "
               + "; ".join(f"{x['service']} @{x['tag']} {x['file']} image …{x['image'][-12:]} weights {x['model_path'].split('/')[-1] if x['model_path'] else '?'}"
                           + (f" rev {x['model_revision'][:10]}" if x['model_revision'] else "")
                           + ((f" + LoRA adapter {x['adapter']['weights'] or x['adapter']['path']}"
                               + (f" rev {x['adapter']['revision'][:10]}" if x['adapter']['revision'] else "")) if x.get("adapter") else "")
                           + (f" (same instance also serves LoRA adapters under other names: {', '.join(x['lora_modules'])})"
                              if x.get("lora_modules") else "") for x in svc[:2])
               + (f" (+{len(svc) - 2} more replicas)" if len(svc) > 2 else ""))
            for x in svc[:1]:
                if x.get("adapter") and not x["adapter"]["revision"]:
                    warnings.append(f"{r['model_id']} is a LoRA adapter loaded from {x['adapter']['path']} on the traced base weights; "
                                    "the adapter is not pinned to a published revision")
            built = []  # SLSA v1 provenance where NEAR publishes it; its absence or an outage is a warning, never a verdict
            for img in sorted({x["image"] for x in svc}):
                short = f"{img.split('@')[0].removeprefix('docker.io/')}@…{img[-8:]}"  # e.g. lmsysorg/sglang@…d85856b1
                try:
                    bp = provenance.build_provenance(img)
                except provenance.ProvenanceInvalid as e:
                    warnings.append(f"image {short}: build provenance present but INVALID ({e})")
                    continue
                except Exception as e:  # noqa: BLE001 — registry, TUF or network trouble: not checked, said so
                    warnings.append(f"image {short}: build provenance not checked ({type(e).__name__})")
                    continue
                if bp is None:
                    warnings.append(f"image {short}: no published build provenance (SLSA)")
                else:
                    built.append(f"{short} built by {bp['repository'].removeprefix('https://')} {bp['workflow']} "
                                 f"@{(bp['commit'] or '?')[:8]} (SLSA v1, sigstore)")
            if built:
                ok("build provenance", "; ".join(built))

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
            # the signed transactions' own arguments, not only the contract's state: the contract wasn't built reproducibly,
            # so the values the owner committed are read from what the owner signed
            signed = {"seal": {"benchmark_id": b["id"], "root": b["root"], "n": b["n"], "policy_hash": b["policy_hash"], "models": b["models"]},
                      "commit_run": {"benchmark_id": b["id"], "model_id": r["model_id"], "run_root": r["run_root"], "total_score": r["total_score"]},
                      "close_round": {"benchmark_id": b["id"]}}
            for tx, method, h in ((b["seal_tx"], "seal", b["seal_height"]), (r["commit_tx"], "commit_run", r["commit_height"]),
                                  (a["close_tx"], "close_round", a["close_height"])):
                rc = near.tx_receipt(tx, reg["owner"], reg["account"], method)
                _req(rc["block_height"] == h and rc["args"] == signed[method], "record_mismatch")
            _req(got["seal_height"] < r["commit_height"] < got["close_height"], "commit_order_invalid")
            seal_hdr = near.block(b["seal_height"])
            _req(seal_hdr is not None and seal_hdr["hash"] == b["seal_block_hash"], "record_mismatch")
            if near.access_key_count(reg["account"]):
                warnings.append(f"{reg['account']} still has an access key: its code can be replaced, so records are not guaranteed append-only")
            history = sorted(x["run_index"] for x in got["runs"] if x["model_id"] == r["model_id"])
            rec = got
            ok("registry", f"{reg['account']} code {near.REGISTRY['code_hash'][:10]}…; seal {b['seal_height']} < commit {r['commit_height']} < close {a['close_height']}; "
                          f"the signed seal and commit arguments match; committed runs for this model: {history}")

        def sample():
            if rec is None:  # registry unavailable: already deferred
                return
            close_hdr = near.block(a["close_height"])
            _req(close_hdr is not None and close_hdr["hash"] == a["close_block_hash"], "audit_sample_mismatch")
            if tee_round:
                ctx = owner.audit_context(cert, rec, close_hdr["hash"])
                _req(ctx["runs"] == a["round_runs"], "audit_sample_mismatch")
                ok("round closed", f"closed at {a['close_height']}; no sample: a TEE-scored round reveals nothing")
                return
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

        def tee_remote():
            if tee_info is None:
                return
            try:
                detail = tee.check_remote(tee_ev, cert)
            except tee.TeeRefused as e:
                raise Refused(str(e)) from e
            except tee.TeeUnapproved as e:
                deferred.append((str(e), "OutLayer worker measurements not approved at the execution's block, or legacy format"))
                return
            u = tee_info.get("unreadable")
            if u is not None:
                counted["unreadable"] = u
            ok("tee score", f"all {n} items rebuilt and re-scored inside an OutLayer TDX enclave by scorer {tee_info['pin'][:12]}… "
                            f"(task {tee_info['task']}): total {r['total_score']}/{n} and both roots match"
                            + (f"; {u} unreadable answer{'' if u == 1 else 's'} (counted inside the TEE)" if u is not None else "")
                            + f"; {detail}")

        def ground_remote():
            if ground_info is None:
                return
            try:
                detail = tee.check_remote(ground_ev, cert)
            except tee.TeeRefused as e:
                raise Refused(str(e)) from e
            except tee.TeeUnapproved as e:
                deferred.append((str(e), "OutLayer worker measurements not approved at the grounding's block, or legacy format"))
                return
            f = ground_info["flagged"]
            ok("answer keys", f"{n - len(f)}/{n} answer keys appear in their cited line of near/docs at {ground_info['commit'][:8]}, "
                              f"checked inside an OutLayer TDX enclave by build {ground_info['pin'][:12]}… (task {ground_info['task']})"
                              + (f"; {len(f)} flagged, not checked (a derived answer or a broader alternative): item{'' if len(f) == 1 else 's'} "
                                 + ", ".join(map(str, f)) if f else "") + f"; {detail}")

        def asked_remote():
            if asked_info is None:
                return
            if check_info is None:
                return
            try:
                detail = tee.check_remote(asked_ev, cert)
                tee.check_remote(check_ev, cert)
                lock = tee.check_asked_lock(cert)
            except tee.TeeRefused as e:
                raise Refused(str(e)) from e
            except tee.TeeUnapproved as e:
                deferred.append((str(e), "OutLayer worker measurements not approved at the aggregate's block, or legacy format"))
                return
            u, rt = asked_info.get("unreadable"), asked_info["retried"]
            if u is not None:
                counted["unreadable"] = u
            ok("asked once", f"all {n} answers asked once inside an OutLayer TDX enclave by asker {asked_info['pin'][:12]}… in "
                             f"{asked_info['project']} (aggregate task {asked_info['task']}): total {r['total_score']}/{n} and both roots match; "
                             f"{rt} retried ask{'' if rt == 1 else 's'} (no answer had left the enclave); every request rebuilt with the seal "
                             f"block's hash by scorer {check_info['pin'][:12]}… (task {check_info['task']}) equals the signed one, so every ask "
                             f"came after the seal"
                             + (f"; {u} unreadable answer{'' if u == 1 else 's'}" if u is not None else "") + f"; {lock}; {detail}")

        for step in (attest, registry, sample, tee_remote, ground_remote, asked_remote):
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
    log = r.get("evidence", {}).get("attempt_log")
    warnings.append("owner-reported failed inference attempts: " + ("not recorded" if log is None else str(len(log)))
                    + " (not verifiable; an owner could omit them)")
    tee_scored = any(c[0] in ("tee score", "asked once") for c in checks)
    if asked:
        rt = asked_info["retried"] if asked_info else 0
        scope = (f"signature evidence verified; commitments and total consistent ({r['total_score']}/{n}); every item asked inside an "
                 f"OutLayer TDX enclave after the seal and scored there, its answer recorded once, so the total is exact under the TEE "
                 f"trust assumptions" + (f"; {rt} ask{'' if rt == 1 else 's'} retried after a timeout, so a single draw per item could "
                 f"differ from this total by at most {rt}" if rt else "; no ask retried, so each item is a single draw")
                 + f"; nothing revealed: all {n} items stay private")
    elif tee_round:
        scope = (f"signature evidence verified; commitments and total consistent ({r['total_score']}/{n}); every item rebuilt and "
                 f"re-scored inside an OutLayer TDX enclave from the sealed bytes, so the total is exact, not statistical, under the TEE "
                 f"trust assumptions; nothing revealed: all {n} items stay private")
    else:
        p = core.p_detect(n, d, k)
        scope = (f"signature evidence verified; commitments and total consistent ({r['total_score']}/{n}); "
                 f"audit passed {k}/{n} with zero mismatches; detection power {float(p) * 100:.4f}% for ≥{d} incorrect item "
                 f"scores under the stated sampling assumptions (not the probability that the total is correct); "
                 f"directly revealed {k}, unrevealed {n - k} (indirect disclosure, such as shared sources, is not computed here)")
        if tee_scored:
            scope += (f"; every item re-scored inside an OutLayer TDX enclave from the sealed bytes: the total {r['total_score']}/{n} is "
                      "exact, not statistical, under the TEE trust assumptions")
    v2 = P.is_seal_bound(b["policy"])
    asked_ok = any(c[0] == "asked once" for c in checks)
    limits = [x for x in LIMITS if not (tee_round and x in (LIMIT_SAMPLING, LIMIT_REVEALS)) and not (v2 and x == LIMIT_TIMING)
              and not (asked_ok and x == LIMIT_RESAMPLE)] + ([ASKED_LIMIT] if asked_ok else [])
    grounded = any(c[0] == "answer keys" for c in checks)
    limits += ([ZERO_REVEAL_GROUNDED_LIMIT if grounded else ZERO_REVEAL_LIMIT] if tee_round else []) + ([GROUND_LIMIT] if grounded else []) + ([SEAL_BOUND_LIMIT] if v2 else []) + ([E2EE_LIMIT, E2EE_KEY_LIMIT_COUNTED if "unreadable" in counted else E2EE_KEY_LIMIT] if P.is_e2ee(b["policy"]) else []) + ([tee.TEE_LIMIT] if tee_scored else [])
    return {"outcome": "VERIFIED", "scope": scope, "checks": checks, "warnings": warnings, "limits": limits, "trace": trace}


def _check_sig_text(sig: dict, text: str) -> str | None:
    from eth_account import Account
    from eth_account.messages import encode_defunct
    try:
        rec = Account.recover_message(encode_defunct(text=text), signature=sig["signature"])
    except (ValueError, TypeError, KeyError):
        return "bad_signature"
    return None if rec.lower() == str(sig.get("signing_address", "")).lower() else "bad_signature"
