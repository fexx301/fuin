// Run site/verify.js in Node against the bundled certificates and live mutations; compare with the Python verdicts.
// Usage: node scripts/test_site_verifier.mjs   (needs network for the NEAR RPC steps)
import fs from 'node:fs';
globalThis.window = globalThis;
for (const f of ['site/vendor/noble.js', 'site/vendor/dcap.js', 'site/data.js', 'site/verify.js']) {
  const g = f.endsWith('noble.js') ? '\nglobalThis.Noble = Noble;' : f.endsWith('dcap.js') ? '\nglobalThis.Dcap = Dcap;' : '';
  (0, eval)(fs.readFileSync(f, 'utf8') + g);
}
const ctx = globalThis;
const F = ctx.FUIN, V = ctx.FuinVerify;
const cfg = (rec) => ({ supported: F.supported, attested: F.attested_models, registry: F.registry, rpc: F.rpc, pccs: F.pccs, attestationPolicy: F.attestation_policy, recorded: rec });
const clone = (x) => JSON.parse(JSON.stringify(x));
let fails = 0;
const check = async (name, cert, want, net = true, over = {}) => {
  const c = { ...cfg('VERIFIED'), rpc: net ? F.rpc : 'http://127.0.0.1:9', pccs: net ? F.pccs : 'http://127.0.0.1:9', ...over };
  const res = await V.verify(cert, c);
  const got = res.outcome + (res.code ? ' ' + res.code : '');
  const ok = got === want; fails += !ok;
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}: ${got}${ok ? '' : ' (want ' + want + ')'}`);
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
await check('cherry-picked sample', mut((c) => { c.audit.indices = [...Array(c.audit.k).keys()]; }), 'REFUSED audit_sample_mismatch');
await check('answer hint (real round)', F.hint.cert, 'REFUSED request_policy_mismatch');
await check('relabelled as GPT', mut((c) => { c.run.model_id = 'openai/gpt-5.5'; }), "CANT_CERTIFY model_not_tee");
await check('flipped TDX quote byte', mut((c) => { const r = c.run.model_report.model_attestations[0]; const q = r.intel_quote; const k = q.length - 200; r.intel_quote = q.slice(0, k) + (q[k] === '0' ? '1' : '0') + q.slice(k + 1); }), 'REFUSED attestation_invalid');
await check('edited app_compose (MRCONFIGID)', mut((c) => { c.run.model_report.model_attestations[0].info.tcb_info.app_compose += ' '; }), 'REFUSED attestation_invalid');
await check('unapproved config does not hide registry tampering', mut((c) => { c.benchmark.seal_height += 1; }), 'REFUSED record_mismatch', true,
  { attestationPolicy: { version: 'empty', models: {} } });
await check('unapproved config alone', base, 'CANT_CERTIFY measurement_unapproved', true, { attestationPolicy: { version: 'empty', models: {} } });
await check('one-byte salt', mut((c) => { c.audit.reveals[0].salt = 'ab'; }), 'REFUSED certificate_invalid');
await check('RPC down, untampered', base, 'CANT_CERTIFY evidence_unavailable', false);
await check('RPC down, tampered signature', mut((c) => { c.run.items[0].signature.text += 'x'; }), 'REFUSED signature_text_mismatch', false);
// scorer parity with Python on every revealed answer
let parity = 0, total = 0;
for (const r of F.rounds) for (const e of r.certs) { const sc = e.cert.benchmark.policy.scorer.name; const scores = Object.fromEntries(e.cert.run.items.map((i) => [i.i, i.score]));
  for (const x of e.cert.audit.reveals) { total++; if (V.scoreResponse(x.item, V.b64(x.response_b64), sc) === scores[x.i]) parity++; } }
console.log(`scorer parity on revealed answers: ${parity}/${total}`); fails += parity !== total;
process.exit(fails ? 1 : 0);
