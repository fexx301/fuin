// Run site/verify.js in Node against the bundled certificates and live mutations; compare with the Python verdicts.
// Usage: node scripts/test_site_verifier.mjs   (needs network for the NEAR RPC steps)
import fs from 'node:fs';
globalThis.window = globalThis;
for (const f of ['site/vendor/noble.js', 'site/vendor/yaml.js', 'site/vendor/dcap.js', 'site/data.js', 'site/verify.js']) {
  const g = f.endsWith('noble.js') ? '\nglobalThis.Noble = Noble;' : f.endsWith('yaml.js') ? '\nglobalThis.Yaml = Yaml;' : f.endsWith('dcap.js') ? '\nglobalThis.Dcap = Dcap;' : '';
  (0, eval)(fs.readFileSync(f, 'utf8') + g);
}
const ctx = globalThis;
const F = ctx.FUIN, V = ctx.FuinVerify;
const cfg = (rec) => ({ supported: F.supported, attested: F.attested_models, registry: F.registry, rpc: F.rpc, pccs: F.pccs, attestationPolicy: F.attestation_policy, tee: F.tee, recorded: rec });
const clone = (x) => JSON.parse(JSON.stringify(x));
// the page must carry the verifier's current pins: rebuild site/data.js (scripts/build_page.py) whenever policy/ changes
const pinsNow = JSON.parse(fs.readFileSync('policy/tee-v2.json', 'utf8')).scorers.map((s) => s.wasm_sha256).sort();
const pinsOk = JSON.stringify(pinsNow) === JSON.stringify([...F.tee.pins].sort());
console.log(`${pinsOk ? 'ok  ' : 'FAIL'} page data carries policy/tee-v2.json's scorer pins${pinsOk ? '' : ' (stale site/data.js: run scripts/build_page.py)'}`);
let fails = pinsOk ? 0 : 1;
// LoRA-served models: the page's trace matcher agrees with fuin.provenance.served_as on the shared cases (expected values in tests/test_os_and_trace.py)
const SERVED = { 'vllm base': null, 'vllm adapter': ['U/L', '196c06e3'], 'sglang adapter': [null, null], 'sglang prefix': 'none', 'not served': 'none' };
for (const [name, cmd, model] of JSON.parse(fs.readFileSync('tests/fixtures/served-as-cases.json', 'utf8'))) {
  const got = V.servedAs(cmd, model), want = SERVED[name];
  const ok = want === 'none' ? got === null : want === null ? got && got.adapter === null : got && got.adapter && got.adapter.weights === want[0] && got.adapter.revision === want[1];
  fails += !ok; console.log(`${ok ? 'ok  ' : 'FAIL'} served as: ${name}`);
}
const check = async (name, cert, want, net = true, over = {}) => {
  const c = { ...cfg('VERIFIED'), rpc: net ? F.rpc : 'http://127.0.0.1:9', rpcFallback: net ? F.rpc_fallback : [], pccs: net ? F.pccs : 'http://127.0.0.1:9', ...over };
  // a certificate carrying a TEE score must have had it checked here whenever the verdict is VERIFIED
  const verdict = (res) => res.outcome + (res.code ? ' ' + res.code : '') + (res.outcome === 'VERIFIED' && cert.run.evidence && cert.run.evidence.tee_score && res.tee !== 'live' ? ' (TEE not checked)' : '') + (res.outcome === 'VERIFIED' && cert.run.evidence && cert.run.evidence.tee_ground && res.ground !== 'live' ? ' (answer keys not checked)' : '') + (res.outcome === 'VERIFIED' && res.trace !== 'live' ? ' (trace not checked)' : '');
  let got = verdict(await V.verify(cert, c)), retries = 0;
  // a public RPC's rate limit is an outage, not a verdict on the certificate: wait it out, at most twice
  while (net && got === 'CANT_CERTIFY evidence_unavailable' && want !== got && retries < 2) {
    retries++; await new Promise((s) => setTimeout(s, 45000)); got = verdict(await V.verify(cert, c));
  }
  const ok = got === want; fails += !ok;
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}: ${got}${ok ? '' : ' (want ' + want + ')'}${retries ? ` (after ${retries} retry for an RPC outage)` : ''}`);
};
for (const r of F.rounds) for (const e of r.certs) await check(e.file, e.cert, 'VERIFIED');
const base = F.rounds.find((r) => r.id === 'near-dev-60-r1').certs.find((e) => /qwen/i.test(e.cert.run.model_id)).cert;  // r1 qwen, by id: round order changes as rounds are added
const mut = (fn) => { const c = clone(base); fn(c); return c; };
await check('edited answer', mut((c) => { const x = c.audit.reveals[0]; const j = JSON.parse(atob(x.response_b64)); j.choices[0].message.content = '1000'; x.response_b64 = btoa(unescape(encodeURIComponent(JSON.stringify(j)))); }), 'REFUSED signature_text_mismatch');
await check('inflated total', mut((c) => c.run.total_score++), 'REFUSED total_score_mismatch');
await check('changed leaf', mut((c) => { c.run.items[3].benchmark_leaf = '00'.repeat(32); }), 'REFUSED merkle_root_mismatch');
await check('changed revealed question', mut((c) => { c.audit.reveals[0].item.question += ' '; }), 'REFUSED reveal_mismatch');
await check('altered policy', mut((c) => { c.benchmark.policy.audit.k = 5; }), 'REFUSED policy_mismatch');
await check('wrong key', mut((c) => { const it = c.run.items[0]; const s = ctx.Noble.signText(it.signature.text); it.signature.signature = s.signature; it.signature.signing_address = s.address; }), 'REFUSED signer_not_attested_for_model');
const other = F.rounds.find((r) => r.id === 'near-dev-60-r1').certs.find((e) => !/qwen/i.test(e.cert.run.model_id)).cert.run;
await check('commit pointed at another model\'s real commit (height too)', mut((c) => { c.run.commit_tx = other.commit_tx; c.run.commit_height = other.commit_height; }), 'REFUSED record_mismatch');
await check('cherry-picked sample', mut((c) => { c.audit.indices = [...Array(c.audit.k).keys()]; }), 'REFUSED audit_sample_mismatch');
await check('answer hint (real round)', F.hint.cert, 'REFUSED request_policy_mismatch');
await check('relabelled as GPT', mut((c) => { c.run.model_id = 'openai/gpt-5.5'; }), "CANT_CERTIFY model_not_tee");
await check('flipped TDX quote byte', mut((c) => { const r = c.run.model_report.model_attestations[0]; const q = r.intel_quote; const k = q.length - 200; r.intel_quote = q.slice(0, k) + (q[k] === '0' ? '1' : '0') + q.slice(k + 1); }), 'REFUSED attestation_invalid');
await check('edited app_compose (MRCONFIGID)', mut((c) => { c.run.model_report.model_attestations[0].info.tcb_info.app_compose += ' '; }), 'REFUSED attestation_invalid');
await check('unapproved config does not hide registry tampering', mut((c) => { c.benchmark.seal_height += 1; }), 'REFUSED record_mismatch', true,
  { attestationPolicy: { version: 'empty', models: {} } });
await check('unapproved config alone', base, 'CANT_CERTIFY measurement_unapproved', true, { attestationPolicy: { version: 'empty', models: {} } });
const polOS = clone(F.attestation_policy);
for (const e of Object.values(polOS.models[base.run.model_id])) e.os_measurements = [{ mr_td: '00'.repeat(48), rt_mr0: '00'.repeat(48), rt_mr1: '00'.repeat(48), rt_mr2: '00'.repeat(48) }];
await check('unapproved OS measurements (MRTD, RTMR0-2)', base, 'CANT_CERTIFY measurement_unapproved', true, { attestationPolicy: polOS });
await check('os_image_hash differs from the policy', mut((c) => { c.run.model_report.model_attestations[0].info.os_image_hash = '00'.repeat(32); }), 'CANT_CERTIFY measurement_unapproved');
await check('uploaded certificate: no recorded GPU result', base, 'PARTIAL GPU not checked in a browser', true, { recorded: null });
await check('deployment log edited', mut((c) => { const a = c.run.model_report.model_attestations[0].compose_manager_attestation; const up = a.actions.find((x) => x.action === 'compose_up'); up.file = up.file + '.x'; }), 'REFUSED attestation_invalid');
await check('deployment attestation removed', mut((c) => { delete c.run.model_report.model_attestations[0].compose_manager_attestation; }), 'CANT_CERTIFY deployment_untraced');
await check('one-byte salt', mut((c) => { c.audit.reveals[0].salt = 'ab'; }), 'REFUSED certificate_invalid');
// TEE score: the same mutations as the CLI fixtures (scripts/make_fixtures.py), on the round-3 TEE base
const teeBase = F.rounds.find((r) => r.id === 'near-dev-300-r3').certs.find((e) => /glm/i.test(e.cert.run.model_id)).cert;
const tmut = (fn) => { const c = clone(teeBase); fn(c.run.evidence.tee_score); return c; };
const rehash = async (ev) => { ev.record.output_hash = V.hex(await V.sha256(new TextEncoder().encode(V.jcs(ev.output)))); };
await check('TEE total edited', tmut((ev) => { ev.output.total++; }), 'REFUSED tee_score_invalid');
const rehashed = clone(teeBase); rehashed.run.evidence.tee_score.output.total++; await rehash(rehashed.run.evidence.tee_score);
await check('TEE total edited, output hash recomputed', rehashed, 'REFUSED tee_score_mismatch');
await check('TEE task id forged', tmut((ev) => { ev.record.task_id++; }), 'REFUSED tee_attestation_invalid');
await check('TEE scorer build not pinned', tmut((ev) => { ev.record.wasm_hash = '11'.repeat(32); }), 'CANT_CERTIFY tee_unapproved');
await check('TEE total edited and build not pinned', tmut((ev) => { ev.record.wasm_hash = '11'.repeat(32); ev.output.total++; }), 'REFUSED tee_score_invalid');
await check('TEE record pointed at another real transaction', tmut((ev) => { ev.transaction_hash = ev.record.transaction_hash = teeBase.benchmark.seal_tx; }), 'REFUSED tee_score_invalid');
// a zero-reveal round: its TEE score is the only score check, so removing or contradicting it must never verify
const zr = F.rounds.find((r) => r.certs[0].cert.benchmark.policy.audit.mode === F.supported.tee_audit);
if (zr) {
  const zb = zr.certs[0].cert, zmut = (fn) => { const c = clone(zb); fn(c); return c; };
  await check('zero-reveal: TEE score removed', zmut((c) => { delete c.run.evidence.tee_score; }), 'CANT_CERTIFY tee_score_missing');
  await check('zero-reveal: sealed scorer swapped', zmut((c) => { c.run.evidence.tee_score.record.wasm_hash = '11'.repeat(32); }), 'REFUSED tee_score_mismatch');
  await check('zero-reveal: seal block hash changed', zmut((c) => { c.benchmark.seal_block_hash = '1'.repeat(32); }), 'REFUSED tee_score_mismatch');
  await check('zero-reveal: a sample smuggled in', zmut((c) => { c.audit.indices = [0]; }), 'REFUSED audit_sample_mismatch');
  await check('zero-reveal: uploaded, no recorded GPU result', zb, 'PARTIAL GPU not checked in a browser', true, { recorded: null });
} else { console.log('FAIL no zero-reveal round in site/data.js'); fails++; }
// scorer v4 on an end-to-end-encrypted rehearsal: the TEE attests how many answers didn't decrypt
await check('scorer v4 rehearsal (unreadable count attested)', JSON.parse(fs.readFileSync('evidence/2026-11-05-scorer-v4-unreadable-count/cert-e2ee-rehearsal-2-glm-5.3-flash.json', 'utf8')), 'VERIFIED');
await check('RPC down, untampered', base, 'CANT_CERTIFY evidence_unavailable', false);
await check('RPC down, tampered signature', mut((c) => { c.run.items[0].signature.text += 'x'; }), 'REFUSED signature_text_mismatch', false);
// scorer parity with Python on every revealed answer
let parity = 0, total = 0;
for (const r of F.rounds) for (const e of r.certs) { const sc = e.cert.benchmark.policy.scorer.name; const scores = Object.fromEntries(e.cert.run.items.map((i) => [i.i, i.score]));
  for (const x of e.cert.audit.reveals) { total++; if (V.scoreResponse(x.item, V.b64(x.response_b64), sc) === scores[x.i]) parity++; } }
console.log(`scorer parity on revealed answers: ${parity}/${total}`); fails += parity !== total;
// scorer parity with Python on 3,600 generated edge cases (Unicode case folding, whitespace, digits): scripts/make_scorer_parity.py
const gen = JSON.parse(fs.readFileSync('tests/fixtures/scorer-parity.json', 'utf8')).cases;
let genOk = 0; for (const c of gen) genOk += V.scoreText(c.item, c.content, false) === c.v1 && V.scoreText(c.item, c.content, true) === c.v2;
console.log(`scorer parity on generated edge cases: ${genOk}/${gen.length}`); fails += genOk !== gen.length;
process.exit(fails ? 1 : 0);
