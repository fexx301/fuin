/* Fūin page: dot-art hero, rotating seal, interactive verifier, results, revealed-sample explorer. */
(function () {
  'use strict';
  const HERO = window.FUIN_HERO;
  let F = null, V = null;  // set once data.js and verify.js have loaded (see boot)
  const $ = (s, el = document) => el.querySelector(s);
  const h = (tag, attrs = {}, ...kids) => {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) k === 'class' ? (el.className = v) : k.startsWith('on') ? el.addEventListener(k.slice(2), v) : el.setAttribute(k, v);
    for (const k of kids.flat()) el.append(k instanceof Node ? k : document.createTextNode(String(k)));
    return el;
  };
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const sleep = (ms) => new Promise((r) => setTimeout(r, reduced ? 0 : ms));
  const short = (m) => m.split('/').pop();

  /* ---------------- hero: dot-art hands + spinning seal ---------------- */
  const SEAL = '<path d="M35 25h190v78h-22V47H57v146h56v22H35z"/><path d="M225 125v90h-90v-22h68v-68z"/><path d="M79 69h102v22H101v80H79z"/><path d="M123 113h58v58h-58z"/>';
  const flat = (fill) => `<svg viewBox="15 8 240 240" xmlns="http://www.w3.org/2000/svg"><g fill="${fill}">${SEAL}</g></svg>`;
  function buildCoin() {
    const coin = $('#coin');
    const back = h('div', { class: 'back' }); back.innerHTML = flat('#8f2422');
    coin.append(back);
    for (let i = 9; i >= 1; i--) { const e = h('div', { class: 'edge' }); e.innerHTML = flat(i > 5 ? '#571b1b' : '#8f2422'); e.style.transform = `translateZ(${-i * 1.1}px)`; coin.append(e); }
    const front = h('img', { src: 'assets/fuin-symbol-depth.svg', alt: '' }); front.style.transform = 'translateZ(0.5px)';
    coin.append(front);
  }

  function hero() {
    const cv = $('#dots'), cx = cv.getContext('2d'), tilt = $('#coinTilt');
    const rows = HERO.hands.rows, cols = HERO.hands.cols;
    let W = 0, H = 0, dpr = 1, dots = [], dust = [], sparks = [], band = {}, mouse = { x: -9999, y: -9999 }, coinXY = { x: 0, y: 0 };
    function layout() {
      dpr = Math.min(devicePixelRatio || 1, 2); W = cv.clientWidth; H = cv.clientHeight;
      cv.width = W * dpr; cv.height = H * dpr; cx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const scale = W < 760 ? 1.9 : 1.3, bw = W * scale, cw = bw / cols, ch = cw * (36.437 / 19.313);
      band = { cw, ch, off: (W - bw) / 2, h: rows.length * ch, top: H * (W < 760 ? 0.26 : 0.31) - (rows.length * ch) / 2 };
      // pull the hands in: fingertip gap ≈ 1.6 seal widths, whatever the screen size
      const mid = cols / 2; let lt = 0, rt = cols;
      rows.forEach((r) => [...r].forEach((c, i) => { if (c !== ' ') { if (i < mid && i > lt) lt = i; if (i >= mid && i < rt) rt = i; } }));
      const sealPx = Math.max(78, Math.min(150, W * 0.085));
      band.shift = Math.max(0, ((rt - lt) * cw - sealPx * 1.6) / 2);
      dots = [];
      rows.forEach((row, j) => [...row].forEach((c, i) => {
        if (c === ' ') return;
        const x = band.off + (i + 0.5) * cw + (i < mid ? band.shift : -band.shift), y = band.top + (j + 0.5) * ch + (c === '.' ? ch * 0.18 : 0);
        dots.push({ x, y, bx: x, by: y, vx: 0, vy: 0, big: c === '#', tw: Math.random() * 6.28 });
      }));
      dust = Array.from({ length: Math.round((W * H) / 2600) }, () => ({ x: Math.random() * W, y: Math.random() * H, s: Math.random() * 0.9 + 0.3, a: Math.random(), v: Math.random() * 0.15 + 0.03 }));
      coinXY = { x: band.off + HERO.hands.gap.x * cols * cw, y: band.top + HERO.hands.gap.y * band.h };
      const size = sealPx;
      tilt.style.setProperty('--coin', size + 'px'); tilt.style.left = coinXY.x + 'px'; tilt.style.top = coinXY.y + 'px';
    }
    // fingertips, for the occasional seal-ink spark travelling into the seal
    const tips = () => {
      const mid = cols / 2; let L = [0, 0], R = [cols, 0];
      rows.forEach((r, j) => [...r].forEach((c, i) => { if (c === ' ') return; if (i < mid && i > L[0]) L = [i, j]; if (i >= mid && i < R[0]) R = [i, j]; }));
      return [L, R].map(([i, j], side) => ({ x: band.off + (i + 0.5) * band.cw + (side === 0 ? band.shift : -band.shift), y: band.top + (j + 0.5) * band.ch }));
    };
    let fingertips = [];
    let last = 0, t0 = performance.now();
    function frame(now) {
      const t = (now - t0) / 1000;
      cx.fillStyle = '#161616'; cx.fillRect(0, 0, W, H);
      for (const d of dust) { d.y -= d.v; d.x += Math.sin(t * 0.3 + d.a * 9) * 0.08; if (d.y < -4) { d.y = H + 4; d.x = Math.random() * W; }
        cx.fillStyle = `rgba(112,112,110,${0.25 + 0.25 * Math.sin(t * 1.3 + d.a * 20)})`; cx.fillRect(d.x, d.y, d.s, d.s); }
      const R = 120, R2 = R * R;
      for (const d of dots) {
        const dx = d.x - mouse.x, dy = d.y - mouse.y, q = dx * dx + dy * dy;
        if (q < R2) { const f = (1 - q / R2) * 2.4, l = Math.sqrt(q) || 1; d.vx += (dx / l) * f; d.vy += (dy / l) * f; }
        d.vx += (d.bx - d.x) * 0.055; d.vy += (d.by - d.y) * 0.055; d.vx *= 0.82; d.vy *= 0.82; d.x += d.vx; d.y += d.vy;
        const r = d.big ? band.cw * 0.42 : band.cw * 0.2;
        cx.fillStyle = d.big ? `rgba(242,242,240,${0.82 + 0.18 * Math.sin(t * 1.7 + d.tw)})` : '#70706e';
        cx.beginPath(); cx.arc(d.x, d.y, Math.max(r, 0.6), 0, 6.283); cx.fill();
      }
      if (!reduced && now - last > 1700) { last = now; fingertips.forEach((p) => sparks.push({ x: p.x, y: p.y, p: 0, sx: p.x, sy: p.y })); }
      for (const s of sparks) { s.p += 0.012; const e = 1 - Math.pow(1 - Math.min(s.p, 1), 3);
        s.x = s.sx + (coinXY.x - s.sx) * e; s.y = s.sy + (coinXY.y - s.sy) * e - Math.sin(e * Math.PI) * 18;
        cx.fillStyle = `rgba(208,74,59,${1 - Math.max(0, s.p - 0.7) / 0.3})`; cx.beginPath(); cx.arc(s.x, s.y, 2.1, 0, 6.283); cx.fill(); }
      sparks = sparks.filter((s) => s.p < 1);
      if (!painted) { painted = true; heroReady(); }
      if (!reduced && visible) requestAnimationFrame(frame);
    }
    let painted = false;
    let visible = true;  // stop drawing ~5,000 dots per frame once the hero is off-screen
    new IntersectionObserver((es) => { const was = visible; visible = es[0].isIntersecting; if (visible && !was && !reduced) requestAnimationFrame(frame); }).observe(cv);
    addEventListener('resize', () => { layout(); fingertips = tips(); if (reduced) frame(performance.now()); });
    cv.addEventListener('pointermove', (e) => {
      const r = cv.getBoundingClientRect(); mouse = { x: e.clientX - r.left, y: e.clientY - r.top };
      const rx = ((mouse.y - coinXY.y) / H) * -28, ry = ((mouse.x - coinXY.x) / W) * 36;
      tilt.style.transform = `translate(-50%,-50%) rotateX(${rx}deg) rotateY(${ry}deg)`;
    });
    cv.addEventListener('pointerleave', () => { mouse = { x: -9999, y: -9999 }; tilt.style.transform = 'translate(-50%,-50%)'; });
    tilt.style.transformStyle = 'preserve-3d';
    layout(); fingertips = tips(); requestAnimationFrame(frame);
  }

  /* ---------------- diagnose (port of src/fuin/diagnose.py) ---------------- */
  const NUMS = /[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?/g;
  function lenient(item, content) {
    const text = content.replace(/(?<=\d)[,_](?=\d)/g, '');
    if (item.answer_type === 'numeric') { const n = [...new Set(text.match(NUMS) || [])]; return n.length === 1 && V.scoreText(item, n[0], true) === 1; }
    const norm = text.replace(/[`*"'()]/g, ' ').toLowerCase();
    return [item.answer, ...(item.accept || [])].some((w) => new RegExp(`(?<![\\w:.])${w.replace(/\(\)$/, '').toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?![\\w])`).test(norm));
  }
  function classify(x, score) {
    if (score === 1) return 'correct';
    let ch; try { ch = JSON.parse(new TextDecoder().decode(V.b64(x.response_b64))).choices[0]; } catch { return 'wrong'; }
    const content = (ch.message.content || '').trim();
    if (!content && ch.finish_reason === 'length') return 'cut';
    return lenient(x.item, content) ? 'format' : 'wrong';
  }
  const answerOf = (x) => { try { return (JSON.parse(new TextDecoder().decode(V.b64(x.response_b64))).choices[0].message.content || '').trim(); } catch { return ''; } };
  const breakdown = (cert) => { const sc = Object.fromEntries(cert.run.items.map((i) => [i.i, i.score])); const o = { correct: 0, wrong: 0, format: 0, cut: 0 }; for (const x of cert.audit.reveals) o[classify(x, sc[x.i])]++; return o; };
  const served = (e) => [...new Set(((e.recorded && e.recorded.trace && e.recorded.trace.services) || []).map((s) => s.model_path).filter(Boolean))].join(', ');

  /* ---------------- evidence links, pressed state ---------------- */
  // Known disclosure per round: direct reveals plus items disclosed indirectly (README "Disclosure").
  const DISCLOSURE = { 'near-dev-60-r1': { revealed: 23, indirect: 1 }, 'near-dev-60-r2': { revealed: 23, indirect: 0 } };
  const TX = 'https://testnet.nearblocks.io/txns/';
  function evidenceLinks(entry, c) {
    const a = (href, text) => h('a', { href, target: '_blank', rel: 'noopener' }, text);
    const out = [];
    if (entry && entry.file) out.push(a('https://github.com/fexx301/fuin/blob/main/' + entry.file, 'certificate'), ' · ');
    if (c.benchmark && c.benchmark.seal_tx) out.push(a(TX + c.benchmark.seal_tx, 'seal tx'), ' · ');
    if (c.run && c.run.commit_tx) out.push(a(TX + c.run.commit_tx, 'commit tx'), ' · ');
    if (c.audit && c.audit.close_tx) out.push(a(TX + c.audit.close_tx, 'close tx'));
    return out;
  }
  function press(group, btn) { group.querySelectorAll('.chip').forEach((x) => { x.classList.toggle('on', x === btn); if (x.hasAttribute('aria-pressed')) x.setAttribute('aria-pressed', String(x === btn)); }); }

  /* ---------------- verifier console ---------------- */
  const STEPS = [
    ['schema', 'Certificate shape', 'local'], ['model', 'Model is attested', 'local'], ['rows', 'Rows and total', 'local'],
    ['commitments', 'Merkle commitments', 'local'], ['policy', 'Sealed policy', 'local'], ['signatures', 'Every model signature', 'local'],
    ['reveals', 'Revealed sample re-scored', 'local'], ['attestation', 'Intel TDX quote (+ GPU, recorded)', 'Intel via PCCS'],
    ['registry', 'NEAR registry record', 'NEAR RPC'], ['sample', 'Audit sample from a NEAR block', 'NEAR RPC'],
  ];
  const clone = (x) => JSON.parse(JSON.stringify(x));
  const utf8b64 = (s) => btoa(String.fromCharCode(...new TextEncoder().encode(s)));
  let current = null, running = 0;
  const CHEATS = [
    ['Edit an answer', 'Rewrites a revealed answer after the model signed it.', (c) => {
      const x = c.audit.reveals[0], j = JSON.parse(new TextDecoder().decode(V.b64(x.response_b64)));
      const was = j.choices[0].message.content; j.choices[0].message.content = was === c.audit.reveals[0].item.answer ? 'unknown' : x.item.answer;
      x.response_b64 = utf8b64(JSON.stringify(j)); return `audit.reveals[0] answer: ${JSON.stringify(String(was).slice(0, 30))} → ${JSON.stringify(j.choices[0].message.content)}`; }],
    ['Inflate the score', 'Adds one point to the published total.', (c) => { const was = c.run.total_score; c.run.total_score++; return `run.total_score: ${was} → ${c.run.total_score}`; }],
    ['Change a sealed question', 'Edits a question after the seal.', (c) => { c.audit.reveals[0].item.question = c.audit.reveals[0].item.question.replace(/\?/, '? (edited)'); return `audit.reveals[0].item.question: "…? (edited)"`; }],
    ['Sign with another key', 'Re-signs an answer, validly, with a key that is not the model\'s attested key.', (c) => {
      const it = c.run.items[0], s = window.Noble.signText(it.signature.text), was = it.signature.signing_address;
      it.signature.signature = s.signature; it.signature.signing_address = s.address; return `run.items[0] signer: ${was.slice(0, 10)}… → ${s.address.slice(0, 10)}… (fresh key)`; }],
    ['Cherry-pick the audit', 'Replaces the sample with items the owner prefers.', (c) => { const was = c.audit.indices.slice(0, 4); c.audit.indices = [...Array(c.audit.k).keys()]; return `audit.indices: [${was}, …] → [${c.audit.indices.slice(0, 4)}, …]`; }],
    ['Forge the TDX quote', 'Flips one byte of the Intel TDX quote that attests the model\'s signing key.', (c) => {
      const r0 = c.run.model_report.model_attestations[0], q = r0.intel_quote, k = q.length - 200;
      r0.intel_quote = q.slice(0, k) + (q[k] === '0' ? '1' : '0') + q.slice(k + 1); return `run.model_report…intel_quote: one byte flipped at offset ${k / 2}`; }],
    ['Relabel as GPT', 'Claims a non-TEE gateway model produced the answers.', (c) => { const was = c.run.model_id; c.run.model_id = 'openai/gpt-5.5'; return `run.model_id: ${was} → openai/gpt-5.5`; }],
  ];
  function renderChecks() {
    const ul = $('#checks'); ul.innerHTML = '';
    for (const [id, name, where] of STEPS) ul.append(h('li', { id: 'ck-' + id }, h('span', { class: 'ic', 'aria-hidden': 'true' }), h('div', { class: 'nm' }, name, h('small', {}, where), h('span', { class: 'st' }, '')), h('div', { class: 'dt' }, '')));
  }
  async function onStep(id, state, detail) {
    const li = $('#ck-' + id); if (!li) return;
    li.className = state === 'running' ? 'active running' : state;
    $('.ic', li).textContent = state === 'pass' ? '✓' : state === 'fail' ? '✕' : state === 'info' || state === 'skip' ? '!' : '';
    $('.st', li).textContent = id === 'attestation' && state === 'pass' ? 'TDX checked now · GPU recorded'
      : { pass: 'checked now', fail: 'failed', info: 'recorded evidence', skip: 'not checked', running: '' }[state] ?? '';
    if (detail) $('.dt', li).textContent = detail;
    await sleep(state === 'running' ? 260 : 90);
  }
  function stamp(res) {
    const s = $('#stamp'); s.className = 'stamp';
    void s.offsetWidth;
    const live = res.outcome === 'VERIFIED' && res.attestation === 'live';
    const cls = live ? 'ok' : res.outcome === 'REFUSED' ? 'bad' : 'cant';
    const title = res.outcome === 'CANT_CERTIFY' ? "CAN'T CERTIFY" : res.outcome === 'PARTIAL' ? 'PARTLY CHECKED' : res.outcome;
    const sub = res.outcome === 'VERIFIED' ? (live ? 'TDX checked now · GPU recorded' : 'attestation recorded, not checked here') : res.code;
    s.innerHTML = ''; s.append(title, h('small', {}, sub));
    s.classList.add('show', cls);
    $('#announce').textContent = `${title}: ${sub}`;
  }
  function recordedLine(entry, tampered) {
    if (!entry || !entry.recorded || tampered) return null;
    const ch = Object.fromEntries((entry.recorded.checks || []).map(([n, , d]) => [n, d]));
    return ch.attestation ? `${ch.attestation.replace(/ under attestation-v\d+/, '')}; deployment traced` : null;
  }
  async function run(entry, mutate) {
    const id = ++running;
    current = entry;
    const cert = clone(entry.cert);
    let note = '';
    if (mutate) note = mutate(cert);
    const diff = $('#diff'); diff.classList.toggle('show', !!note); diff.textContent = note ? 'Tampered: ' + note : '';
    const r = cert.run || {}, b = cert.benchmark || {};
    $('#certTitle').textContent = `${short(r.model_id || '?')} · ${b.id || 'uploaded certificate'}`;
    const meta = $('#certMeta'); meta.innerHTML = '';
    meta.append(`committed ${r.total_score}/${b.n} · run ${r.run_index} · `, ...evidenceLinks(entry, cert));
    renderChecks(); $('#stamp').className = 'stamp';
    const res = await V.verify(cert, { supported: F.supported, attested: F.attested_models, registry: F.registry, rpc: F.rpc, pccs: F.pccs, attestationPolicy: F.attestation_policy, recorded: recordedLine(entry, !!mutate) },
      (i, st, d) => (id === running ? onStep(i, st, d) : null));
    if (id === running) stamp(res);
  }
  function picker() {
    const list = $('#certList');
    const all = [];
    for (const rd of F.rounds) for (const e of rd.certs) {
      const btn = h('button', { class: 'cert-btn', 'aria-pressed': 'false' }, h('span', { class: 'm' }, short(e.cert.run.model_id)), h('span', { class: 's' }, `${e.cert.run.total_score}/60`),
        h('span', { class: 'r' }, `round ${rd.id.slice(-1)} · ${rd.cap.toLocaleString('en')} tokens`));
      btn.addEventListener('click', () => select(btn, e)); list.append(btn); all.push([btn, e]);
    }
    const hb = h('button', { class: 'cert-btn' }, h('span', { class: 'm' }, 'Answer slipped into the prompt'), h('span', { class: 's' }, '1/1'),
      h('span', { class: 'r' }, 'real round, signed and committed'));
    hb.addEventListener('click', () => select(hb, { cert: F.hint.cert, recorded: null, file: F.hint.file })); $('#hintList').append(hb);
    const cheat = $('#cheat');
    CHEATS.forEach(([label, tip, fn]) => { const c = h('button', { class: 'chip', title: tip, 'aria-pressed': 'false' }, label); c.addEventListener('click', () => { press(cheat, c); run(current, fn); }); cheat.append(c); });
    const reset = h('button', { class: 'chip reset' }, 'Reset'); reset.addEventListener('click', () => { press(cheat, null); run(current); }); cheat.append(reset);
    const again = h('button', { class: 'chip reset' }, 'Run again'); again.addEventListener('click', () => run(current)); cheat.append(again);
    function select(btn, e) { document.querySelectorAll('.cert-btn').forEach((x) => { x.classList.remove('on'); x.setAttribute('aria-pressed', 'false'); }); btn.classList.add('on'); btn.setAttribute('aria-pressed', 'true'); press(cheat, null); run(e); }
    const file = $('#file'), drop = $('#drop');
    drop.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); file.click(); } });
    const load = async (f) => { try { const c = JSON.parse(await f.text()); document.querySelectorAll('.cert-btn').forEach((x) => x.classList.remove('on')); run({ cert: c, recorded: null }); } catch { $('#diff').classList.add('show'); $('#diff').textContent = 'That file is not JSON.'; } };
    file.addEventListener('change', () => file.files[0] && load(file.files[0]));
    drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('over'));
    drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('over'); e.dataTransfer.files[0] && load(e.dataTransfer.files[0]); });
    // start verifying the headline certificate when the console scrolls into view
    current = all[0][1]; all[0][0].classList.add('on'); renderChecks();
    $('#certTitle').textContent = `${short(current.cert.run.model_id)} · ${current.cert.benchmark.id}`;
    new IntersectionObserver((es, o) => { if (es[0].isIntersecting) { o.disconnect(); run(current); } }, { threshold: 0.35 }).observe($('.stage'));
  }

  /* ---------------- results, explorer, steps, refusals ---------------- */
  function results() {
    const box = $('#rounds');
    for (const rd of F.rounds) {
      const dis = DISCLOSURE[rd.id] || { revealed: 23, indirect: 0 }, known = dis.revealed + dis.indirect;
      const card = h('div', { class: 'panel round' }, h('h3', {}, rd.id), h('div', { class: 'meta' }, `${rd.cap}-token cap · reasoning on · ${dis.revealed} revealed` + (dis.indirect ? ` + ${dis.indirect} indirectly disclosed` : '') + ` · ${60 - known} hidden`));
      for (const e of rd.certs) {
        const c = e.cert, bd = breakdown(c), pct = (100 * c.run.total_score) / c.benchmark.n;
        const bar = h('i'); bar.dataset.w = pct + '%';
        card.append(h('div', { class: 'bar-row' },
          h('div', { class: 'top' }, h('div', {}, h('div', { class: 'name' }, c.run.model_id), h('div', { class: 'served' }, 'served as ' + (served(e) || '—'))), h('div', { class: 'score' }, c.run.total_score, h('small', {}, '/' + c.benchmark.n))),
          h('div', { class: 'bar' }, bar),
          h('div', { class: 'pills' }, h('span', { class: 'pill' }, 'revealed 23:'), h('span', { class: 'pill ok' }, `${bd.correct} correct`), h('span', { class: 'pill bad' }, `${bd.wrong} wrong`),
            h('span', { class: 'pill fmt' }, `${bd.format} format`), h('span', { class: 'pill cut' }, `${bd.cut} cut off`)),
          h('div', { class: 'links' }, ...evidenceLinks(e, c))));
      }
      box.append(card);
    }
    new IntersectionObserver((es, o) => { if (es[0].isIntersecting) { o.disconnect(); box.querySelectorAll('.bar i').forEach((b) => (b.style.width = b.dataset.w)); } }, { threshold: 0.3 }).observe(box);
  }
  function explorer() {
    let ri = 0, filt = 'all';
    const tabs = $('#exRound'), fl = $('#exFilter');
    const draw = () => {
      const rd = F.rounds[ri], qa = $('#qa'); qa.innerHTML = '';
      const per = rd.certs.map((e) => ({ m: short(e.cert.run.model_id), sc: Object.fromEntries(e.cert.run.items.map((i) => [i.i, i.score])), rv: Object.fromEntries(e.cert.audit.reveals.map((x) => [x.i, x])) }));
      for (const x of rd.certs[0].cert.audit.reveals) {
        const lines = per.map((p) => {
          const rx = p.rv[x.i], cls = classify(rx, p.sc[x.i]), full = answerOf(rx), tag = h('span', { class: 'tag ' + cls }, cls === 'cut' ? 'cut off' : cls);
          if (cls === 'cut' && !full) return { cls, el: h('span', { class: 'said' }, tag, `${p.m}: (cut off before answering)`) };
          if (full.length <= 48) return { cls, el: h('span', { class: 'said' }, tag, `${p.m}: ${full}`) };
          return { cls, el: h('details', { class: 'said' }, h('summary', {}, tag, `${p.m}: ${full.slice(0, 48)}… `, h('u', {}, 'view full answer')), h('pre', { class: 'full' }, full)) }; });
        if (filt !== 'all' && !lines.some((l) => l.cls === filt)) continue;
        qa.append(h('div', { class: 'qa' }, h('div', { class: 'n' }, '#' + x.i),
          h('div', { class: 'q' }, x.item.question, x.item.source ? h('a', { href: x.item.source.url, target: '_blank', rel: 'noopener' }, 'source') : ''),
          h('div', { class: 'a' }, h('span', { class: 'exp' }, 'expected ' + x.item.answer), ...lines.map((l) => l.el))));
      }
    };
    F.rounds.forEach((rd, i) => { const c = h('button', { class: 'chip' + (i === 0 ? ' on' : ''), 'aria-pressed': String(i === 0) }, `Round ${rd.id.slice(-1)} · ${rd.cap.toLocaleString('en')} tokens`); c.addEventListener('click', () => { ri = i; press(tabs, c); draw(); lead(); }); tabs.append(c); });
    [['all', 'All 23'], ['correct', 'Correct'], ['wrong', 'Wrong'], ['format', 'Format'], ['cut', 'Cut off']].forEach(([k, label], i) => {
      const c = h('button', { class: 'chip' + (i === 0 ? ' on' : ''), 'aria-pressed': String(i === 0) }, label); c.addEventListener('click', () => { filt = k; press(fl, c); draw(); }); fl.append(c); });
    const lead = () => { const d = DISCLOSURE[F.rounds[ri].id] || { revealed: 23, indirect: 0 };
      $('#exLead').textContent = `A NEAR block that didn't exist when the results were committed chose these ${d.revealed} of 60.` + (d.indirect ? ` ${d.indirect} more is disclosed indirectly (it shares a cited docs line with revealed items), so ${60 - d.revealed - d.indirect} stay private.` : ` The other ${60 - d.revealed} stay private.`) + ' Miss types are a reading aid computed from the revealed bytes, not a score.'; };
    draw(); lead();
  }
  function steps() {
    const S = [['Seal', 'The owner commits a Merkle root of the salted questions and the scoring policy on NEAR.'],
      ['Run', 'Each question goes to a TEE model on NEAR AI Cloud. Its attested key signs the exact request and response.'],
      ['Commit', 'Each run\'s result root and total go on chain, numbered per model.'],
      ['Close', 'The round closes. No more runs can join it.'],
      ['Sample', 'A finalized NEAR block after the close picks the audited items. Nobody knew it in advance.'],
      ['Reveal', 'The sampled questions, salts and exact bytes are published with Merkle proofs.'],
      ['Verify', 'Anyone checks every signature and commitment, re-derives the sample, and re-scores the reveals.']];
    S.forEach(([t, d], i) => $('#steps').append(h('div', { class: 'panel step' }, h('b', {}, String(i + 1).padStart(2, '0')), h('h4', {}, t), h('p', {}, d))));
  }
  function refusals() {
    for (const f of F.manifest) { const cant = f.expected.startsWith('CANT');
      $('#refList').append(h('div', { class: 'panel ref' + (cant ? ' cant' : '') }, h('code', {}, f.expected.replace('CANT_CERTIFY', "CAN'T CERTIFY")), h('p', {}, f.mutation))); }
  }

  /* ---------------- loading: hero first, then the heavy files with real progress ---------------- */
  const loader = $('#loader'), bar = $('#topbar'), t0 = performance.now();
  const total = Object.values(HERO.assets).reduce((a, b) => a + b, 0), got = {};
  const progress = (label) => {
    const done = Object.values(got).reduce((a, b) => a + b, 0), pct = Math.min(100, Math.round((100 * done) / total));
    bar.style.width = pct + '%'; bar.classList.toggle('done', pct >= 100); const lb = $('#loaderBar'); if (lb) lb.style.width = pct + '%';
    const msg = `${label} · ${pct}%`;
    const ls = $('#loaderStatus'); if (ls) ls.textContent = msg;  // the loader is removed once the hero is up
    const vs = $('#verifyLoading'); if (vs) vs.textContent = 'Loading the verifier · ' + msg;
  };
  // Stream over http(s) to count real bytes (decompressed, so it matches the sizes from build_page.py);
  // file:// can't be fetched, so fall back to a plain <script> and count the file when it lands.
  function load(src, label) {
    const size = HERO.assets[src];
    const viaTag = () => new Promise((res, rej) => { const el = document.createElement('script'); el.src = src; el.onload = () => { got[src] = size; progress(label); res(); }; el.onerror = rej; document.body.append(el); });
    if (!/^https?:$/.test(location.protocol) || !window.ReadableStream) return viaTag();
    return fetch(src).then(async (r) => {
      if (!r.ok || !r.body) throw new Error('fetch failed');
      const rd = r.body.getReader(), parts = []; let n = 0;
      for (;;) { const { done, value } = await rd.read(); if (done) break; parts.push(value); n += value.length; got[src] = Math.min(n, size); progress(label); }
      const url = URL.createObjectURL(new Blob(parts, { type: 'text/javascript' }));
      await new Promise((res, rej) => { const el = document.createElement('script'); el.src = url; el.onload = () => { URL.revokeObjectURL(url); res(); }; el.onerror = rej; document.body.append(el); });
      got[src] = size; progress(label);
    }).catch(viaTag);
  }
  function heroReady() {  // keep the seal animation up long enough to read, never longer than needed
    setTimeout(() => { loader.classList.add('gone'); setTimeout(() => loader.remove(), 700); }, Math.max(0, 1400 - (performance.now() - t0)));
  }
  async function boot() {
    progress('Loading certificates');
    await Promise.all([load('vendor/noble.js', 'signature checker'), load('verify.js', 'verifier'), load('data.js', 'certificates')]);
    F = window.FUIN; V = window.FuinVerify;
    const vl = $('#verifyLoading'); if (vl) vl.remove();
    picker(); results(); explorer(); refusals();
    $('#buildInfo').textContent = `Page data from commit ${F.commit} · ${F.generated_utc}`;
    // the TDX verifier (1.4 MB of WASM) is only needed partway through a run; verify.js waits on this promise
    window.DcapReady = load('vendor/dcap.js', 'Intel TDX verifier');
  }
  const menu = $('#menuBtn'); menu.addEventListener('click', () => { const open = document.body.classList.toggle('menu-open'); menu.setAttribute('aria-expanded', String(open)); });
  document.querySelectorAll('nav .links a').forEach((a) => a.addEventListener('click', () => { document.body.classList.remove('menu-open'); menu.setAttribute('aria-expanded', 'false'); }));
  buildCoin(); hero(); steps();
  document.querySelectorAll('[data-copy]').forEach((b) => b.addEventListener('click', async () => { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = 'Copied'; setTimeout(() => (b.textContent = 'Copy'), 1400); }));
  boot().catch((e) => { const vs = $('#verifyLoading'); if (vs) vs.textContent = 'Could not load the verifier: ' + e + '. Reload to try again.'; });
})();
