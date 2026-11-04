/* Fūin in-browser verifier: a port of src/fuin/verify.py for every check a browser can do.
 * Local: schema, rows, Merkle roots (RFC 8785 + domain-tagged SHA-256), sealed policy, every EIP-191 signature,
 * revealed proofs, exact request bytes, re-score. Network (NEAR RPC, CORS-enabled): registry record, transaction
 * receipts, seed block, audit sample. Not in a browser: Intel TDX / NVIDIA GPU attestation and the deployment trace
 * (run `fuin verify`). Needs globals: Noble (vendor/noble.js), crypto.subtle, fetch.
 */
(function (root) {
  'use strict';
  const enc = new TextEncoder();
  const dec = new TextDecoder('utf-8', { fatal: true });

  class Refused extends Error { constructor(code, where) { super(code); this.code = code; this.where = where; } }
  class CantCertify extends Error { constructor(code) { super(code); this.code = code; } }
  class Unavailable extends Error {}
  const req = (cond, code, where) => { if (!cond) throw new Refused(code, where); };

  // ---- bytes ----
  const hex = (b) => Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
  const isHex32 = (s) => typeof s === 'string' && /^[0-9a-f]{64}$/.test(s);
  const unhex = (s) => Uint8Array.from(s.match(/../g) || [], (x) => parseInt(x, 16));
  const concat = (parts) => {
    const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
    let o = 0; for (const p of parts) { out.set(p, o); o += p.length; } return out;
  };
  const sha256 = async (...parts) => new Uint8Array(await crypto.subtle.digest('SHA-256', concat(parts)));
  const u64 = (n) => { const b = new Uint8Array(8); new DataView(b.buffer).setBigUint64(0, BigInt(n)); return b; };
  const eq = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);
  const b64 = (s) => {
    if (typeof s !== 'string' || !/^[A-Za-z0-9+/]*={0,2}$/.test(s) || s.length % 4) throw new Refused('certificate_invalid', 'base64');
    const bin = atob(s); return Uint8Array.from(bin, (c) => c.charCodeAt(0));
  };
  const B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
  const b58decode = (s) => {
    let n = 0n; for (const c of s) { const v = B58.indexOf(c); if (v < 0) throw new Error('bad base58'); n = n * 58n + BigInt(v); }
    let h = n.toString(16); if (h.length % 2) h = '0' + h; if (n === 0n) h = '';
    const lead = s.length - s.replace(/^1+/, '').length;
    return concat([new Uint8Array(lead), unhex(h)]);
  };

  // ---- RFC 8785 canonical JSON (integers and strings, as fuin items and policies use) ----
  function jcs(v) {
    if (v === null) return 'null';
    if (typeof v === 'boolean') return v ? 'true' : 'false';
    if (typeof v === 'number') { if (!Number.isFinite(v)) throw new Error('non-finite'); return JSON.stringify(v); }
    if (typeof v === 'string') return JSON.stringify(v);
    if (Array.isArray(v)) return '[' + v.map(jcs).join(',') + ']';
    return '{' + Object.keys(v).sort().map((k) => JSON.stringify(k) + ':' + jcs(v[k])).join(',') + '}';
  }

  // ---- Merkle (index order, duplicate last node at odd widths) ----
  const parent = (l, r) => sha256(new Uint8Array([1]), l, r);
  async function merkleRoot(leaves) {
    let level = leaves;
    while (level.length > 1) {
      if (level.length % 2) level = [...level, level[level.length - 1]];
      const next = []; for (let j = 0; j < level.length; j += 2) next.push(await parent(level[j], level[j + 1])); level = next;
    }
    return level[0];
  }
  async function verifyProof(leaf, i, n, proof, root) {
    if (!(n >= 1 && i >= 0 && i < n)) return false;
    let node = leaf, idx = i, width = n, used = 0;
    while (width > 1) {
      if (used >= proof.length) return false;
      const sib = proof[used++];
      if (idx % 2 === 0) { if (idx === width - 1 && !eq(sib, node)) return false; node = await parent(node, sib); }
      else node = await parent(sib, node);
      idx = Math.floor(idx / 2); width = Math.ceil(width / 2);
    }
    return used === proof.length && eq(node, root);
  }
  const benchmarkLeaf = (i, salt, item) => sha256(new Uint8Array([0]), u64(i), salt, enc.encode(jcs(item)));
  const runLeaf = (i, bl, rq, rs, score) => sha256(new Uint8Array([2]), u64(i), bl, rq, rs, new Uint8Array([score]));

  // ---- audit size: exact hypergeometric, BigInt ----
  function comb(n, k) { if (k < 0 || k > n) return 0n; k = Math.min(k, n - k); let r = 1n; for (let i = 1; i <= k; i++) r = (r * BigInt(n - k + i)) / BigInt(i); return r; }
  function auditSize(n) {
    const d = Math.ceil(n / 10);
    for (let k = 1; k <= n; k++) { const tot = comb(n, k), miss = k <= n - d ? comb(n - d, k) : 0n; if (100n * (tot - miss) >= 95n * tot) return { d, k, p: Number(tot - miss) / Number(tot) }; }
    throw new Error('unreachable');
  }
  async function sampleIndices(seed, n, k) {
    const N = BigInt(n), limit = ((1n << 256n) / N) * N, chosen = new Set();
    for (let c = 0; c < (1 << 20); c++) {
      const x = BigInt('0x' + hex(await sha256(seed, u64(c))));
      if (x < limit) { chosen.add(Number(x % N)); if (chosen.size === k) return [...chosen].sort((a, b) => a - b); }
    }
    throw new Error('sampler counter exhausted');
  }

  // ---- scorers (ports of fuin-scorer-v1 and -v2) ----
  const NUMBER = /^[-+]?\d+(\.\d+)?([eE][-+]?\d+)?$/;
  function stripSet(s, set) { let a = 0, b = s.length; while (a < b && set.includes(s[a])) a++; while (b > a && set.includes(s[b - 1])) b--; return s.slice(a, b); }
  function decimal(s) { // exact: value = m * 10^e
    const m = s.match(/^([-+]?)(\d+)(?:\.(\d+))?(?:[eE]([-+]?\d+))?$/); if (!m) throw new Error('bad decimal');
    const frac = m[3] || ''; return { m: BigInt((m[1] === '-' ? '-' : '') + m[2] + frac), e: (m[4] ? parseInt(m[4], 10) : 0) - frac.length };
  }
  function absDiffLE(a, b, tol) {
    const e = Math.min(a.e, b.e, tol.e), sc = (x) => x.m * 10n ** BigInt(x.e - e);
    const d = sc(a) - sc(b); return (d < 0n ? -d : d) <= sc(tol);
  }
  function scoreText(item, content, v2) {
    let s = content.trim(); if (s.endsWith('.')) s = s.slice(0, -1);
    s = stripSet(s.trim(), v2 ? '`"\'*_' : '`"\'').trim();
    if (item.answer_type === 'numeric') {
      s = s.replace(/(?<=\d)[,_](?=\d)/g, '');
      if (!NUMBER.test(s)) return 0;
      try { return absDiffLE(decimal(s), decimal(item.answer), decimal(item.tolerance || '0')) ? 1 : 0; } catch { return 0; }
    }
    if (item.answer_type === 'exact') return [item.answer, ...(item.accept || [])].some((a) => a.toLowerCase() === s.toLowerCase()) ? 1 : 0;
    throw new Error('unsupported answer_type');
  }
  function scoreResponse(item, bytes, scorerName) {
    let content;
    try { content = JSON.parse(dec.decode(bytes)).choices[0].message.content; } catch { return 0; }
    return typeof content === 'string' ? scoreText(item, content, scorerName === 'fuin-scorer-v2') : 0;
  }

  // ---- EIP-191 signature recovery (noble secp256k1 + keccak) ----
  function recovers(sig, text) {
    try { return root.Noble.recoverAddress(text, sig.signature) === String(sig.signing_address).toLowerCase(); } catch { return false; }
  }

  // ---- NEAR RPC ----
  async function rpc(url, method, params) {
    let last;
    for (let a = 0; a < 4; a++) {
      try {
        const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ jsonrpc: '2.0', id: 'fuin', method, params }) });
        if ([429, 502, 503, 504].includes(r.status)) throw new Error('HTTP ' + r.status);
        const d = await r.json();
        if (d.error) { const e = new Error(JSON.stringify(d.error).slice(0, 300)); e.rpc = true; throw e; }
        return d.result;
      } catch (e) { if (e.rpc) throw e; last = e; await new Promise((s) => setTimeout(s, 600 * (a + 1))); }
    }
    throw new Unavailable(`${method}: ${last && last.message}`);
  }
  const viewCall = async (url, account, method, args) => {
    const r = await rpc(url, 'query', { request_type: 'call_function', finality: 'final', account_id: account, method_name: method, args_base64: btoa(JSON.stringify(args)) });
    return JSON.parse(dec.decode(Uint8Array.from(r.result)));
  };
  async function block(url, height) {
    try { return (await rpc(url, 'block', height == null ? { finality: 'final' } : { block_id: height })).header; }
    catch (e) { if (e.rpc && /UNKNOWN_BLOCK/.test(e.message)) return null; throw e; }
  }
  async function txReceiptHeight(url, tx, sender, executor, method) {
    const r = await rpc(url, 'EXPERIMENTAL_tx_status', { tx_hash: tx, sender_account_id: sender, wait_until: 'FINAL' });
    const acts = {}; for (const x of r.receipts || []) acts[x.receipt_id] = ((x.receipt || {}).Action || {}).actions || [];
    acts[r.transaction_outcome.outcome.receipt_ids[0]] = r.transaction.actions;
    for (const ro of r.receipts_outcome) {
      if (ro.outcome.executor_id !== executor) continue;
      const names = (acts[ro.id] || []).filter((a) => a && a.FunctionCall).map((a) => a.FunctionCall.method_name);
      if (!names.includes(method)) continue;
      if (!('SuccessValue' in ro.outcome.status)) return -1;
      return (await rpc(url, 'block', { block_id: ro.block_hash })).header.height;
    }
    return -1;
  }

  // ---- schema (subset of verify._validate: everything the browser reads) ----
  function validate(c) {
    const need = (cond, where) => { if (!cond) throw new Refused('certificate_invalid', where); };
    const n32 = (v, w) => need(isHex32(v), w), num = (v, w) => need(Number.isInteger(v) && v >= 0, w), str = (v, w) => need(typeof v === 'string' && v.length > 0 && v.length <= 4096, w);
    need(c && typeof c === 'object' && !Array.isArray(c) && c.version === 1, 'top');
    need(JSON.stringify(Object.keys(c).sort()) === JSON.stringify(['audit', 'benchmark', 'registry', 'run', 'version']), 'top');
    const { registry: reg, benchmark: b, run: r, audit: a } = c;
    for (const k of ['network', 'account', 'code_hash', 'owner']) str(reg && reg[k], 'registry.' + k);
    str(b.id, 'benchmark.id'); n32(b.root, 'benchmark.root'); n32(b.policy_hash, 'benchmark.policy_hash');
    need(Number.isInteger(b.n) && b.n >= 1 && b.n <= 1e6, 'benchmark.n'); need(Array.isArray(b.models), 'benchmark.models');
    need(b.policy && typeof b.policy === 'object', 'benchmark.policy'); str(b.seal_tx, 'benchmark.seal_tx'); num(b.seal_height, 'benchmark.seal_height');
    str(r.model_id, 'run.model_id'); num(r.run_index, 'run.run_index'); n32(r.preflight_nonce, 'run.preflight_nonce');
    need(r.model_report && Array.isArray(r.model_report.model_attestations), 'run.model_report');
    n32(r.run_root, 'run.run_root'); num(r.total_score, 'run.total_score'); str(r.commit_tx, 'run.commit_tx'); num(r.commit_height, 'run.commit_height');
    need(Array.isArray(r.items), 'run.items');
    r.items.forEach((it, j) => {
      const w = `run.items[${j}]`; need(it && Number.isInteger(it.i) && Number.isInteger(it.score), w);
      for (const k of ['benchmark_leaf', 'req_sha256', 'resp_sha256']) n32(it[k], `${w}.${k}`);
      need(it.signature && typeof it.signature === 'object', `${w}.signature`);
      for (const k of ['text', 'signature', 'signing_address', 'signature_kind']) str(it.signature[k], `${w}.signature.${k}`);
    });
    for (const k of ['D', 'k', 'close_height', 'seed_height']) num(a[k], 'audit.' + k);
    for (const k of ['close_tx', 'close_block_hash', 'seed_block_hash']) str(a[k], 'audit.' + k);
    n32(a.seed, 'audit.seed'); need(Array.isArray(a.indices) && a.indices.every(Number.isInteger), 'audit.indices'); need(Array.isArray(a.reveals), 'audit.reveals');
    a.reveals.forEach((x, j) => {
      const w = `audit.reveals[${j}]`; need(x && Number.isInteger(x.i) && x.item && typeof x.item === 'object', w);
      str(x.item.question, w + '.item.question'); str(x.item.answer, w + '.item.answer'); need(['numeric', 'exact'].includes(x.item.answer_type), w + '.item.answer_type');
      n32(x.item.request_nonce, w + '.item.request_nonce'); n32(x.salt, w + '.salt');
      for (const k of ['proof_benchmark', 'proof_run']) { need(Array.isArray(x[k]) && x[k].length <= 64, `${w}.${k}`); x[k].forEach((h, q) => n32(h, `${w}.${k}[${q}]`)); }
      b64(x.request_b64); b64(x.response_b64);
    });
  }

  function makePolicy(n, models, S, scorerName) {
    const { d, k } = auditSize(n);
    return { protocol: S.protocol, models, request: { template: S.template, privacy_profile: S.privacy },
      scorer: { name: scorerName, sha256: S.scorers[scorerName] }, score: { values: [0, 1], aggregate: 'sum', denominator: n },
      audit: { D: d, target: { numerator: 95, denominator: 100 }, k, sampler: S.sampler } };
  }

  /* verify(cert, cfg, onStep) → {outcome, code, detail, steps}. cfg: {supported, attested, registry, rpc, recorded?}.
   * onStep(id, state, detail) with state in running|pass|fail|skip|info, for the UI. */
  async function verify(cert, cfg, onStep = () => {}) {
    const S = cfg.supported, deferred = [];
    let step = '';
    const start = async (id) => { step = id; await onStep(id, 'running', ''); };
    const pass = async (detail) => onStep(step, 'pass', detail);
    const local = async (id, fn) => { await start(id); await pass(await fn()); };
    const online = async (id, fn) => {
      await start(id);
      try { await pass(await fn()); }
      catch (e) { if (e instanceof Unavailable) { deferred.push(['evidence_unavailable', e.message]); await onStep(id, 'skip', 'unavailable: ' + e.message); } else throw e; }
    };
    try {
      await start('schema'); validate(cert); await pass('every field has the right type and form');
      const { benchmark: b, run: r, audit: a } = cert, n = b.n, items = r.items;
      await start('model');
      if (!cfg.attested.includes(r.model_id)) throw new CantCertify(/^(openai|anthropic|google|xai)\//.test(r.model_id) ? 'model_not_tee' : 'policy_unsupported');
      await pass(`${r.model_id} is a TEE model in the verifier's attestation policy`);

      let bl, rl, k;
      await local('rows', async () => {
        req(items.length === n && items.every((it, j) => it.i === j), 'item_set_mismatch');
        req(items.every((it) => it.score === 0 || it.score === 1), 'score_range_invalid');
        req(r.total_score === items.reduce((s, it) => s + it.score, 0), 'total_score_mismatch');
        return `${n} items, scores in {0,1}, total ${r.total_score}/${n}`;
      });
      await local('commitments', async () => {
        bl = items.map((it) => unhex(it.benchmark_leaf));
        const broot = hex(await merkleRoot(bl)); req(broot === b.root, 'merkle_root_mismatch');
        rl = []; for (const it of items) rl.push(await runLeaf(it.i, bl[it.i], unhex(it.req_sha256), unhex(it.resp_sha256), it.score));
        const rroot = hex(await merkleRoot(rl)); req(rroot === r.run_root, 'run_root_mismatch');
        return `benchmark root ${broot.slice(0, 12)}… and run root ${rroot.slice(0, 12)}… rebuilt from all ${n} rows`;
      });
      await local('policy', async () => {
        req(hex(await sha256(enc.encode(jcs(b.policy)))) === b.policy_hash, 'policy_mismatch');
        const sn = b.policy.scorer && b.policy.scorer.name;
        req(sn in S.scorers && jcs(b.policy) === jcs(makePolicy(n, b.policy.models, S, sn)), 'policy_mismatch');
        req(jcs(Object.keys(b.policy.models).sort()) === jcs([...b.models].sort()) && r.model_id in b.policy.models, 'policy_mismatch');
        req(Object.values(b.policy.models).every((s) => Object.keys(s).every((x) => S.allowed_settings.includes(x))), 'policy_mismatch');
        const au = auditSize(n); k = au.k;
        req(a.D === au.d && a.k === au.k && a.target && a.target.numerator === 95 && a.target.denominator === 100, 'audit_sample_mismatch');
        return `${S.protocol}; ${sn} (sha256 ${S.scorers[sn].slice(0, 12)}…); audit k=${k} of ${n}`;
      });
      await local('signatures', async () => {
        const signers = new Set(r.model_report.model_attestations.map((x) => String(x.signing_address).toLowerCase()));
        for (const it of items) {
          const s = it.signature, text = `${r.model_id}:${it.req_sha256}:${it.resp_sha256}`;
          req(s.signature_kind === 'provider_tee' && s.text === text, 'signature_text_mismatch');
          req(recovers(s, text), 'bad_signature');
          req(signers.has(s.signing_address.toLowerCase()), 'signer_not_attested_for_model');
        }
        return `${n}/${n} provider_tee signatures recover to ${items[0].signature.signing_address.slice(0, 10)}…`;
      });
      const rv = a.reveals.map((x) => x.i);
      await local('reveals', async () => {
        req(rv.length === k && rv.every((v, j) => j === 0 || v > rv[j - 1]) && rv.every((v) => v >= 0 && v < n), 'reveal_mismatch');
        for (const x of a.reveals) {
          const it = items[x.i], leaf = await benchmarkLeaf(x.i, unhex(x.salt), x.item);
          req(eq(leaf, bl[x.i]), 'reveal_mismatch');
          req(await verifyProof(leaf, x.i, n, x.proof_benchmark.map(unhex), unhex(b.root)), 'reveal_mismatch');
          req(await verifyProof(rl[x.i], x.i, n, x.proof_run.map(unhex), unhex(r.run_root)), 'reveal_mismatch');
          const rq = b64(x.request_b64), rs = b64(x.response_b64);
          req(hex(await sha256(rq)) === it.req_sha256 && hex(await sha256(rs)) === it.resp_sha256, 'signature_text_mismatch');
          const expected = enc.encode(JSON.stringify({ model: r.model_id, messages: [{ role: 'user', content: x.item.question }], stream: false, user: x.item.request_nonce, ...b.policy.models[r.model_id] }));
          req(eq(rq, expected), 'request_policy_mismatch');
          req(scoreResponse(x.item, rs, b.policy.scorer.name) === it.score, 'score_mismatch');
        }
        return `${k}/${k} revealed: proofs pass, exact request rebuilt, re-score matches`;
      });

      await start('attestation');
      await onStep('attestation', 'info', cfg.recorded ? `recorded by fuin verify: ${cfg.recorded}` : 'needs Intel PCS and NVIDIA NRAS: run fuin verify');

      const reg = cert.registry, url = cfg.rpc; let rec = null;
      await online('registry', async () => {
        req(reg.network === cfg.registry.network && reg.account === cfg.registry.account && reg.code_hash === cfg.registry.code_hash, 'registry_mismatch');
        const acct = await rpc(url, 'query', { request_type: 'view_account', finality: 'final', account_id: reg.account });
        req(acct.code_hash === cfg.registry.code_hash, 'registry_mismatch');
        const got = await viewCall(url, reg.account, 'get_benchmark', { owner: reg.owner, benchmark_id: b.id });
        req(got && got.root === b.root && got.n === n && got.policy_hash === b.policy_hash && jcs(got.models) === jcs(b.models) && got.seal_height === b.seal_height, 'record_mismatch');
        const mine = got.runs.filter((x) => x.model_id === r.model_id && x.run_index === r.run_index);
        req(mine.length === 1 && mine[0].run_root === r.run_root && mine[0].total_score === r.total_score && mine[0].commit_height === r.commit_height, 'record_mismatch');
        req(got.close_height === a.close_height, 'record_mismatch');
        for (const [tx, m, h] of [[b.seal_tx, 'seal', b.seal_height], [r.commit_tx, 'commit_run', r.commit_height], [a.close_tx, 'close_round', a.close_height]])
          req((await txReceiptHeight(url, tx, reg.owner, reg.account, m)) === h, 'record_mismatch');
        req(got.seal_height < r.commit_height && r.commit_height < got.close_height, 'commit_order_invalid');
        const keys = (await rpc(url, 'query', { request_type: 'view_access_key_list', finality: 'final', account_id: reg.account })).keys.length;
        rec = got;
        return `seal ${b.seal_height} < commit ${r.commit_height} < close ${a.close_height} on ${reg.account}; ${keys === 0 ? 'locked (0 access keys)' : keys + ' access key(s): code replaceable'}`;
      });
      await online('sample', async () => {
        if (!rec) throw new Unavailable('registry unavailable');
        const closeHdr = await block(url, a.close_height);
        req(closeHdr && closeHdr.hash === a.close_block_hash, 'audit_sample_mismatch');
        const thr = a.close_height + 2, fin = (await block(url, null)).height;
        let seedHdr = null;
        for (let h = thr; h <= fin && !seedHdr; h++) { const x = await block(url, h); if (x) seedHdr = x; }
        req(seedHdr && seedHdr.prev_height < thr && seedHdr.height === a.seed_height && seedHdr.hash === a.seed_block_hash, 'audit_sample_mismatch');
        const runs = rec.runs.map((x) => ({ model_id: x.model_id, run_index: x.run_index, run_root: x.run_root, total_score: x.total_score }))
          .sort((p, q) => (p.model_id < q.model_id ? -1 : p.model_id > q.model_id ? 1 : p.run_index - q.run_index));
        req(jcs(runs) === jcs(a.round_runs), 'audit_sample_mismatch');
        const ctx = { network: reg.network, registry: reg.account, owner: rec.owner, benchmark_id: rec.benchmark_id, benchmark_root: rec.root,
          policy_hash: rec.policy_hash, close_height: rec.close_height, close_block_hash: closeHdr.hash, runs };
        const seed = await sha256(enc.encode('fuin-audit-v1'), b58decode(seedHdr.hash), await sha256(enc.encode(jcs(ctx))));
        const derived = await sampleIndices(seed, n, k);
        req(hex(seed) === a.seed && jcs(derived) === jcs(a.indices), 'audit_sample_mismatch');
        req(jcs(rv) === jcs(derived), 'reveal_mismatch');
        return `seed block ${seedHdr.height} (first final block ≥ close+2) re-derives the ${k} audited items`;
      });
    } catch (e) {
      if (e instanceof Refused) { await onStep(step, 'fail', e.code + (e.where ? ` (${e.where})` : '')); return { outcome: 'REFUSED', code: e.code, where: e.where }; }
      if (e instanceof CantCertify) { await onStep(step, 'fail', e.code); return { outcome: 'CANT_CERTIFY', code: e.code }; }
      await onStep(step, 'fail', 'certificate_invalid'); return { outcome: 'REFUSED', code: 'certificate_invalid', where: String(e && e.message).slice(0, 120) };
    }
    if (deferred.length) return { outcome: 'CANT_CERTIFY', code: deferred[0][0], detail: deferred[0][1] };
    const au = auditSize(cert.benchmark.n);
    return { outcome: 'VERIFIED', scope: `audit passed ${au.k}/${cert.benchmark.n}; detection power ${(au.p * 100).toFixed(4)}% for ≥${au.d} incorrect scores (not the probability the total is correct)` };
  }

  root.FuinVerify = { verify, jcs, auditSize, scoreText, scoreResponse, sha256, hex, b64 };
})(typeof window !== 'undefined' ? window : globalThis);
