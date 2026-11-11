/* Fūin page: dot-art hero, rotating seal, interactive verifier, results, revealed-sample explorer. */
(function () {
  'use strict';
  const HERO = window.FUIN_HERO;
  let F = null, V = null;  // set once data.js and verify.js have loaded (see boot)
  const $ = (s, el = document) => el.querySelector(s);
  // fires once a block's top is in the upper two-thirds of the screen; a share-visible threshold never fires
  // when the block is taller than the screen (the stacked console on a phone is ~2,000 px)
  const ONSCREEN = { threshold: 0, rootMargin: '0px 0px -33% 0px' };
  const h = (tag, attrs = {}, ...kids) => {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) k === 'class' ? (el.className = v) : k.startsWith('on') ? el.addEventListener(k.slice(2), v) : el.setAttribute(k, v);
    for (const k of kids.flat()) el.append(k instanceof Node ? k : document.createTextNode(String(k)));
    return el;
  };
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const sleep = (ms) => new Promise((r) => setTimeout(r, reduced ? 0 : ms));
  const short = (m) => m.split('/').pop();
  // long lists open short: the first n children show, and one button reveals the rest
  function clamp(box, n, what) {
    if (box.nextElementSibling && box.nextElementSibling.classList.contains('more')) box.nextElementSibling.remove();
    const kids = [...box.children];
    if (kids.length <= n) return;
    kids.slice(n).forEach((k) => (k.hidden = true));
    const b = h('button', { class: 'chip more' }, `Show all ${kids.length} ${what}`);
    b.addEventListener('click', () => { kids.forEach((k) => (k.hidden = false)); b.remove(); kids[n].tabIndex = -1; kids[n].focus({ preventScroll: true }); });
    box.after(b);
  }
  // under the chart, only the chart's round shows its runs until "Show all rounds" is pressed
  let roundShown = 0, allRounds = false;
  function syncRounds() {
    const box = $('#rounds'); box.classList.toggle('one', !allRounds);
    [...box.children].forEach((c, i) => (c.hidden = !allRounds && i !== roundShown));
  }

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
      dpr = Math.min(devicePixelRatio || 1, 2); W = cv.clientWidth;
      const scale = W < 760 ? 1.9 : 1.3, bw = W * scale, cw = bw / cols, ch = cw * (36.437 / 19.313), bh = rows.length * ch;
      const sealPx = Math.max(78, Math.min(150, W * 0.085));
      // the hands sit in the space CSS reserves above the copy (--hands-h); hands and copy are centred as one group,
      // and a short screen grows the hero instead of overlapping them
      const art = Math.max(bh, sealPx), gap = Math.max(24, Math.min(44, innerHeight * 0.045));
      cv.parentElement.style.setProperty('--hands-h', Math.round(art + gap) + 'px');
      H = cv.clientHeight;  // read after --hands-h: the hero may have grown
      cv.width = W * dpr; cv.height = H * dpr; cx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const top = $('.hero-copy').offsetTop - gap - (art + bh) / 2;
      band = { cw, ch, off: W / 2 - HERO.hands.gap.x * bw, h: bh, top };  // the seal sits on the page's centre line, where the copy is centred
      // pull the hands in: fingertip gap ≈ 1.6 seal widths, whatever the screen size
      const mid = cols / 2; let lt = 0, rt = cols;
      rows.forEach((r) => [...r].forEach((c, i) => { if (c !== ' ') { if (i < mid && i > lt) lt = i; if (i >= mid && i < rt) rt = i; } }));
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
      const lit = document.documentElement.dataset.theme === 'light';  // the same dots, inked for a light page
      cx.fillStyle = lit ? '#f6f3ec' : '#161616'; cx.fillRect(0, 0, W, H);
      for (const d of dust) { d.y -= d.v; d.x += Math.sin(t * 0.3 + d.a * 9) * 0.08; if (d.y < -4) { d.y = H + 4; d.x = Math.random() * W; }
        cx.fillStyle = `rgba(${lit ? '120,116,106' : '112,112,110'},${0.25 + 0.25 * Math.sin(t * 1.3 + d.a * 20)})`; cx.fillRect(d.x, d.y, d.s, d.s); }
      const R = 120, R2 = R * R;
      for (const d of dots) {
        const dx = d.x - mouse.x, dy = d.y - mouse.y, q = dx * dx + dy * dy;
        if (q < R2) { const f = (1 - q / R2) * 2.4, l = Math.sqrt(q) || 1; d.vx += (dx / l) * f; d.vy += (dy / l) * f; }
        d.vx += (d.bx - d.x) * 0.055; d.vy += (d.by - d.y) * 0.055; d.vx *= 0.82; d.vy *= 0.82; d.x += d.vx; d.y += d.vy;
        const r = d.big ? band.cw * 0.42 : band.cw * 0.2;
        cx.fillStyle = d.big ? `rgba(${lit ? '27,27,26' : '242,242,240'},${0.82 + 0.18 * Math.sin(t * 1.7 + d.tw)})` : lit ? '#a39f94' : '#70706e';
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
    addEventListener('fuin-theme', () => { if (reduced || !visible) frame(performance.now()); });  // a still canvas repaints in the new theme
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
  // Known disclosure per round: direct reveals plus items disclosed indirectly (docs/RESULTS.md "Disclosure").
  const DISCLOSURE = { 'near-dev-60-r1': { revealed: 23, indirect: 1 }, 'near-dev-60-r2': { revealed: 23, indirect: 0 }, 'near-dev-300-r3': { revealed: 28, indirect: 0 } };
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
    ['trace', 'Serving container traced to NEAR\'s repo', 'Intel via PCCS · GitHub'],
    ['registry', 'NEAR registry record', 'NEAR RPC'], ['sample', 'Round close and audit sample', 'NEAR RPC'],
    ['tee', 'Every answer re-scored in a TEE', 'OutLayer quote via PCCS · NEAR RPC'],
    ['ground', 'Answer keys checked against their source', 'OutLayer quote via PCCS · NEAR RPC'],
    ['asked', 'Every answer asked once, in a TEE', 'OutLayer quote via PCCS · NEAR RPC'],
  ];
  const clone = (x) => JSON.parse(JSON.stringify(x));
  const utf8b64 = (s) => btoa(String.fromCharCode(...new TextEncoder().encode(s)));
  let current = null, running = 0, gpuRecorded = false;  // gpuRecorded: this run has the CLI's recorded NRAS result
  const CHEATS = [
    ['Edit an answer', 'Rewrites a revealed answer after the model signed it.', (c) => {
      const x = c.audit.reveals[0], j = JSON.parse(new TextDecoder().decode(V.b64(x.response_b64)));
      const was = j.choices[0].message.content; j.choices[0].message.content = was === c.audit.reveals[0].item.answer ? 'unknown' : x.item.answer;
      x.response_b64 = utf8b64(JSON.stringify(j)); return `audit.reveals[0] answer: ${JSON.stringify(String(was).slice(0, 30))} → ${JSON.stringify(j.choices[0].message.content)}`; }, 'reveals'],
    ['Inflate the score', 'Adds one point to the published total.', (c) => { const was = c.run.total_score; c.run.total_score++; return `run.total_score: ${was} → ${c.run.total_score}`; }],
    ['Change a sealed question', 'Edits a question after the seal.', (c) => { c.audit.reveals[0].item.question = c.audit.reveals[0].item.question.replace(/\?/, '? (edited)'); return `audit.reveals[0].item.question: "…? (edited)"`; }, 'reveals'],
    ['Sign with another key', 'Re-signs an answer, validly, with a key that is not the model\'s attested key.', (c) => {
      const it = c.run.items[0], s = window.Noble.signText(it.signature.text), was = it.signature.signing_address;
      it.signature.signature = s.signature; it.signature.signing_address = s.address; return `run.items[0] signer: ${was.slice(0, 10)}… → ${s.address.slice(0, 10)}… (fresh key)`; }],
    ['Cherry-pick the audit', 'Replaces the sample with items the owner prefers.', (c) => { const was = c.audit.indices.slice(0, 4); c.audit.indices = [...Array(c.audit.k).keys()]; return `audit.indices: [${was}, …] → [${c.audit.indices.slice(0, 4)}, …]`; }, 'reveals'],
    ['Forge the TDX quote', 'Flips one byte of the Intel TDX quote that attests the model\'s signing key.', (c) => {
      const r0 = c.run.model_report.model_attestations[0], q = r0.intel_quote, k = q.length - 200;
      r0.intel_quote = q.slice(0, k) + (q[k] === '0' ? '1' : '0') + q.slice(k + 1); return `run.model_report…intel_quote: one byte flipped at offset ${k / 2}`; }],
    ['Relabel as GPT', 'Claims a non-TEE gateway model produced the answers.', (c) => { const was = c.run.model_id; c.run.model_id = 'openai/gpt-5.5'; return `run.model_id: ${was} → openai/gpt-5.5`; }],
    ['Edit the TEE total', 'Raises the total the TEE reported, so it is no longer the output OutLayer attested.', (c) => {
      const o = c.run.evidence.tee_score.output, was = o.total; o.total++; return `run.evidence.tee_score.output.total: ${was} → ${o.total}`; }, 'tee'],
    ['Forge the TEE task', 'Changes the OutLayer task id; the Intel-signed quote binds the original task hash.', (c) => {
      const rec = c.run.evidence.tee_score.record, was = rec.task_id; rec.task_id++; return `run.evidence.tee_score.record.task_id: ${was} → ${rec.task_id}`; }, 'tee'],
  ];
  const zeroReveal = (c) => !!(c && c.benchmark && c.benchmark.policy && c.benchmark.policy.audit && [F.supported.tee_audit, F.supported.tee_asked].includes(c.benchmark.policy.audit.mode));
  const askedRound = (c) => zeroReveal(c) && c.benchmark.policy.audit.mode === F.supported.tee_asked;
  const modeName = (c) => askedRound(c) ? 'asked once' : zeroReveal(c) ? 'TEE-scored' : 'sampled';  // the three kinds of round, as the page explains them
  const encrypted = (c) => !!(c && c.benchmark && c.benchmark.policy && c.benchmark.policy.request && c.benchmark.policy.request.template === F.supported.template_v3);
  const canCheat = (c, need) => !need || (need === 'reveals' ? !!(c.audit && c.audit.reveals && c.audit.reveals.length) : !!(c.run && c.run.evidence && c.run.evidence.tee_score));
  function renderChecks() {
    const ul = $('#checks'); ul.innerHTML = '';
    for (const [id, name, where] of STEPS) ul.append(h('li', { id: 'ck-' + id }, h('span', { class: 'ic', 'aria-hidden': 'true' }), h('div', { class: 'nm' }, name, h('small', {}, where), h('span', { class: 'st' }, '')), h('div', { class: 'dt' }, '')));
  }
  async function onStep(id, state, detail, label) {
    const li = $('#ck-' + id); if (!li) return;
    li.className = state === 'running' ? 'active running' : state;
    $('.ic', li).textContent = state === 'pass' ? '✓' : state === 'fail' ? '✕' : state === 'info' || state === 'skip' ? '!' : state === 'na' ? '–' : '';
    $('.st', li).textContent = id === 'attestation' && state === 'pass' ? `TDX checked now · GPU ${gpuRecorded ? 'recorded' : 'not checked'}`
      : label || ({ pass: 'checked now', fail: 'failed', info: 'recorded evidence', skip: 'not checked', na: "doesn't apply", running: '' }[state] ?? '');
    if (detail) $('.dt', li).textContent = detail;
    await sleep(state === 'running' ? 260 : 90);
  }
  function stamp(res) {
    const s = $('#stamp'); s.className = 'stamp';
    void s.offsetWidth;
    const live = res.outcome === 'VERIFIED' && res.attestation === 'live';
    const cls = live ? 'ok' : res.outcome === 'REFUSED' ? 'bad' : 'cant';
    const title = res.outcome === 'CANT_CERTIFY' ? "CAN'T CERTIFY" : res.outcome === 'PARTIAL' ? 'PARTLY CHECKED' : res.outcome;
    const now = ['TDX', res.trace === 'live' ? 'trace' : '', res.tee === 'live' ? 'TEE score' : ''].filter(Boolean);
    const sub = res.outcome === 'VERIFIED' ? (live ? `${now.length > 1 ? now.slice(0, -1).join(', ') + ' and ' + now[now.length - 1] : now[0]} checked now · GPU ${res.trace === 'live' ? '' : 'and trace '}recorded` : 'attestation recorded, not checked here') : res.code;
    s.innerHTML = ''; s.append(title, h('small', {}, sub));
    s.classList.add('show', cls);
    $('#announce').textContent = `${title}: ${sub}`;
  }
  function recordedLine(entry, tampered) {
    if (!entry || !entry.recorded || tampered) return null;
    const ch = Object.fromEntries((entry.recorded.checks || []).map(([n, , d]) => [n, d]));
    return ch.attestation && ch['deployment trace'] ? `${ch.attestation.replace(/ under attestation-v\d+/, '')}; deployment traced${ch['build provenance'] ? ((entry.recorded.warnings || []).some((w) => /build provenance/.test(w)) ? '; build provenance verified for some serving images (SLSA)' : '; serving image build provenance verified (SLSA)') : ''}${ch['tee score'] ? '; every answer scored in a TEE' : ''}` : null;
  }
  function head(entry, cert) {  // title and evidence links, shown before the first check runs so the panel has no empty band
    const r = cert.run || {}, b = cert.benchmark || {};
    $('#certTitle').textContent = `${short(r.model_id || '?')} · ${b.id || 'uploaded certificate'}`;
    const meta = $('#certMeta'); meta.innerHTML = '';
    meta.append(`committed ${r.total_score}/${b.n} · run ${r.run_index} · `, ...evidenceLinks(entry, cert));
  }
  async function run(entry, mutate) {
    const id = ++running;
    gpuRecorded = !!recordedLine(entry, !!mutate);
    current = entry;
    const cert = clone(entry.cert);
    let note = '';
    if (mutate) note = mutate(cert);
    const diff = $('#diff'); diff.classList.toggle('show', !!note); diff.textContent = note ? 'Tampered: ' + note : '';
    head(entry, cert);
    renderChecks(); $('#stamp').className = 'stamp';
    const res = await V.verify(cert, { supported: F.supported, attested: F.attested_models, registry: F.registry, rpc: F.rpc, rpcFallback: F.rpc_fallback, pccs: F.pccs, attestationPolicy: F.attestation_policy, tee: F.tee, recorded: recordedLine(entry, !!mutate) },
      (i, st, d) => (id === running ? onStep(i, st, d) : null));
    // optional evidence a certificate doesn't carry: grey ("na") when the round's kind doesn't call for it, amber when a zero-reveal round lacks it
    const ev = (cert.run && cert.run.evidence) || {}, zr = zeroReveal(cert);
    if (id === running && !ev.tee_score) await (ev.tee_asked
      ? onStep('tee', 'na', 'an asked-once round: the TEE scored each answer as it asked it (see "Every answer asked once, in a TEE" below)')
      : onStep('tee', zr ? 'skip' : 'na', 'this certificate carries no TEE score', zr ? '' : 'not included'));
    if (id === running && !ev.tee_ground) await onStep('ground', zr ? 'skip' : 'na', 'this certificate carries no answer-key check', zr ? '' : 'not included');
    if (id === running && !ev.tee_asked) await onStep('asked', 'na', 'the owner made the model calls in this round; only an asked-once round has a TEE make them');
    if (id === running) stamp(res);
  }
  function picker() {
    const list = $('#certList');
    const all = [];
    for (const rd of F.rounds) for (const e of rd.certs) {
      const btn = h('button', { class: 'cert-btn', 'aria-pressed': 'false' }, h('span', { class: 'm' }, short(e.cert.run.model_id)), h('span', { class: 's' }, `${e.cert.run.total_score}/${e.cert.benchmark.n}`),
        h('span', { class: 'r' }, `round ${rd.id.slice(-1)} · ${modeName(e.cert)}` + (encrypted(e.cert) ? ' · encrypted' : '') + ` · ${rd.cap.toLocaleString('en')} tokens`));
      btn.dataset.file = e.file; btn.addEventListener('click', () => select(btn, e)); list.append(btn); all.push([btn, e]);
    }
    const hb = h('button', { class: 'cert-btn' }, h('span', { class: 'm' }, 'Answer slipped into the prompt'), h('span', { class: 's' }, '1/1'),
      h('span', { class: 'r' }, 'real round, signed and committed'));
    hb.addEventListener('click', () => select(hb, { cert: F.hint.cert, recorded: null, file: F.hint.file })); $('#hintList').append(hb);
    const cheat = $('#cheat');
    CHEATS.forEach(([label, tip, fn, need]) => { const c = h('button', { class: 'chip', title: tip, 'aria-pressed': 'false' }, label); if (need) { c.dataset.need = need; c.dataset.tip = tip; } c.addEventListener('click', () => { press(cheat, c); run(current, fn); }); cheat.append(c); });
    // a cheat that edits reveals or TEE evidence needs a certificate that has them
    const fit = (e) => cheat.querySelectorAll('[data-need]').forEach((b) => { b.disabled = !canCheat(e.cert, b.dataset.need); b.title = b.disabled ? 'not applicable: this certificate has none' : b.dataset.tip; });
    const reset = h('button', { class: 'chip reset' }, 'Reset'); reset.addEventListener('click', () => { press(cheat, null); run(current); }); cheat.append(reset);
    const again = h('button', { class: 'chip reset' }, 'Run again'); again.addEventListener('click', () => run(current)); cheat.append(again);
    function select(btn, e) { document.querySelectorAll('.cert-btn').forEach((x) => { x.classList.remove('on'); x.setAttribute('aria-pressed', 'false'); }); btn.classList.add('on'); btn.setAttribute('aria-pressed', 'true'); press(cheat, null); fit(e); run(e); }
    const file = $('#file'), drop = $('#drop');
    drop.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); file.click(); } });
    const load = async (f) => { try { const c = JSON.parse(await f.text()); document.querySelectorAll('.cert-btn').forEach((x) => x.classList.remove('on')); fit({ cert: c }); run({ cert: c, recorded: null }); } catch { $('#diff').classList.add('show'); $('#diff').textContent = 'That file is not JSON.'; } };
    file.addEventListener('change', () => file.files[0] && load(file.files[0]));
    drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('over'));
    drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('over'); e.dataTransfer.files[0] && load(e.dataTransfer.files[0]); });
    // start verifying the headline certificate when the console scrolls into view
    current = all[0][1]; all[0][0].classList.add('on'); fit(current); renderChecks();
    head(current, current.cert);
    new IntersectionObserver((es, o) => { if (es[0].isIntersecting) { o.disconnect(); run(current); } }, ONSCREEN).observe($('.stage'));
  }

  /* ---------------- results, explorer, steps, refusals ---------------- */
  function results() {
    const box = $('#rounds');
    for (const rd of F.rounds) {
      const n = rd.certs[0].cert.benchmark.n, dis = DISCLOSURE[rd.id] || { revealed: rd.certs[0].cert.audit.reveals.length, indirect: 0 }, known = dis.revealed + dis.indirect;
      const zr = zeroReveal(rd.certs[0].cert);
      const card = h('div', { class: 'panel round' }, h('h3', {}, rd.id), h('div', { class: 'meta' }, zr
        ? `${rd.cap}-token cap · reasoning on · nothing revealed: all ${n} hidden, ` + (askedRound(rd.certs[0].cert) ? 'every question asked and scored by a TEE, which made the model calls itself: one answer kept each, retries counted' : 'every answer scored inside a TEE') + (encrypted(rd.certs[0].cert) ? '; questions and answers end-to-end encrypted, never seen by NEAR\'s gateway' : '')
        : `${rd.cap}-token cap · reasoning on · ${dis.revealed} revealed` + (dis.indirect ? ` + ${dis.indirect} indirectly disclosed` : '') + ` · ${n - known} of ${n} hidden`));
      for (const e of rd.certs) {
        const c = e.cert, bd = breakdown(c), pct = (100 * c.run.total_score) / c.benchmark.n;
        const bar = h('i'); bar.dataset.w = pct + '%';
        card.append(h('div', { class: 'bar-row' },
          h('div', { class: 'top' }, h('div', {}, h('div', { class: 'name' }, c.run.model_id), h('div', { class: 'served' }, 'served as ' + (served(e) || '—'))), h('div', { class: 'score' }, c.run.total_score, h('small', {}, '/' + c.benchmark.n))),
          h('div', { class: 'bar' }, bar),
          h('div', { class: 'pills' }, ...(zr ? [h('span', { class: 'pill' }, 'nothing revealed')] : [h('span', { class: 'pill' }, `revealed ${c.audit.reveals.length}:`), h('span', { class: 'pill ok' }, `${bd.correct} correct`), h('span', { class: 'pill bad' }, `${bd.wrong} wrong`),
            h('span', { class: 'pill fmt' }, `${bd.format} format`), h('span', { class: 'pill cut' }, `${bd.cut} cut off`)]),
            ...(c.run.evidence && c.run.evidence.tee_score ? [h('span', { class: 'pill ok', title: 'Every answer re-scored inside an OutLayer TDX enclave from the sealed bytes; checked by fuin verify' }, `TEE ${zr ? 'scored' : 're-scored'} all ${c.benchmark.n}`)] : []),
            ...(c.run.evidence && c.run.evidence.tee_asked ? [h('span', { class: 'pill ok', title: 'Every question asked by the asker inside an OutLayer TDX enclave, after the seal, and scored there: one answer kept per question, any retry counted; checked by fuin verify' }, `asked once in a TEE, all ${c.benchmark.n}`)] : [])),
          h('div', { class: 'links' }, ...evidenceLinks(e, c))));
      }
      box.append(card);
    }
    const all = h('button', { class: 'chip more' }, `Show all ${F.rounds.length} rounds`);
    all.addEventListener('click', () => { allRounds = true; syncRounds(); all.remove(); });
    box.after(all); syncRounds();
    new IntersectionObserver((es, o) => { if (es[0].isIntersecting) { o.disconnect(); box.querySelectorAll('.bar i').forEach((b) => (b.style.width = b.dataset.w)); } }, ONSCREEN).observe(box);
  }
  // One round at a time: every model in a round answered the same sealed questions, so only within a round do bars compare.
  function chart() {
    const plot = $('#vizPlot'), tip = $('#vizTip'), fig = $('#viz');
    const wilson = (k, n) => {  // 95% score interval for a proportion
      const z = 1.96, p = k / n, d = 1 + z * z / n, c = (p + z * z / (2 * n)) / d, m = (z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / d;
      return [Math.max(0, c - m), Math.min(1, c + m)];
    };
    const pc = (x) => `${Math.round(100 * x)}%`;
    const trace = (e) => ((e.recorded && e.recorded.trace && e.recorded.trace.services) || [])[0] || null;
    const lora = (e) => { const t = trace(e); return (t && t.adapter) || (/abliterated/i.test(e.cert.run.model_id) ? { path: 'a LoRA adapter' } : null); };
    const label = (m) => { const s = short(m); const v = s.match(/^(.*?)-(abliterated)$/i); return v ? [v[1], 'abliterated'] : [s, '']; };
    let shown = false, cur = 0;
    const chips = $('#vizRounds');
    const start = F.rounds.reduce((b, rd, i) => (rd.certs.length > F.rounds[b].certs.length ? i : b), 0);  // open on the round with the most models to compare
    F.rounds.forEach((rd, i) => {
      const c = h('button', { class: 'chip' + (i === start ? ' on' : ''), 'aria-pressed': String(i === start) }, `Round ${rd.id.slice(-1)} · ${modeName(rd.certs[0].cert)}`);
      c.addEventListener('click', () => { press(chips, c); draw(i); }); chips.append(c);
    });
    function hide() { tip.hidden = true; }
    function show(col, e, k, n, lo, hi) {
      const c = e.cert, t = trace(e), ad = lora(e), log = (c.run.evidence && c.run.evidence.attempt_log) || [];
      tip.replaceChildren(
        h('div', { class: 'tv' }, h('strong', {}, `${k}`), h('span', {}, ` / ${n}`), h('em', {}, pc(k / n))),
        h('div', { class: 'tm' }, c.run.model_id),
        h('dl', {},
          h('dt', {}, '95% interval'), h('dd', {}, `${pc(lo)} – ${pc(hi)}`),
          h('dt', {}, 'Served'), h('dd', {}, t ? `${short(t.model_path || '?')}${t.model_revision ? ' @' + t.model_revision.slice(0, 8) : ''}` : (served(e) || '—')),
          ...(ad ? [h('dt', {}, 'Adapter'), h('dd', {}, ad.weights ? `${short(ad.weights)}${ad.revision ? ' @' + ad.revision.slice(0, 8) : ''}` : 'LoRA, unpinned')] : []),
          h('dt', {}, 'Scored'), h('dd', {}, c.run.evidence && c.run.evidence.tee_asked ? `all ${n} inside a TEE, one answer kept each` : c.run.evidence && c.run.evidence.tee_score ? `all ${n} inside a TEE` : `audited sample of ${c.audit.reveals.length}`),
          h('dt', {}, 'Failed attempts'), h('dd', {}, `${log.length} (owner-reported)`)),
        h('div', { class: 'th' }, 'Click to verify this certificate'));
      tip.hidden = false;
      const f = fig.getBoundingClientRect(), b = col.querySelector('.fill').getBoundingClientRect(), w = tip.offsetWidth, ht = tip.offsetHeight;
      if (plot.offsetWidth < 560) {  // rows: under the hovered row
        const r = col.getBoundingClientRect();
        tip.style.left = Math.max(8, (f.width - w) / 2) + 'px'; tip.style.top = (r.bottom - f.top + 8) + 'px';
      } else {  // columns: beside the bar, never over the header
        const right = b.right - f.left + 16, x = right + w < f.width - 8 ? right : b.left - f.left - w - 16;
        tip.style.left = x + 'px'; tip.style.top = Math.min(Math.max(b.top - f.top - 24, 8), f.height - ht - 8) + 'px';
      }
    }
    function draw(i) {
      cur = i; hide(); roundShown = i; syncRounds();
      const rd = F.rounds[i], n = rd.certs[0].cert.benchmark.n, zr = zeroReveal(rd.certs[0].cert);
      const rows = rd.certs.map((e) => ({ e, k: e.cert.run.total_score })).sort((a, b) => b.k - a.k);
      $('#vizTitle').textContent = `Round ${rd.id.slice(-1)}: share of ${n} sealed questions answered correctly`;
      const c0 = rd.certs[0].cert, how = askedRound(c0) ? 'each question asked by a TEE (one answer kept, retries counted), nothing revealed' : zr ? 'every answer scored inside a TEE, nothing revealed' : 'every answer re-scored inside a TEE, a sample revealed';
      $('#vizSub').textContent = `${rows.length} model${rows.length === 1 ? '' : 's'} on the same questions · ${modeName(c0)} round, ${rd.cap.toLocaleString('en')}-token cap · ${how} · whiskers show the 95% interval`;
      plot.replaceChildren(h('div', { class: 'grid', 'aria-hidden': 'true' }, ...[100, 75, 50, 25, 0].map((g) => h('span', { style: `--g:${g / 100}` }, h('b', {}, g + '%')))));
      plot.style.setProperty('--cols', rows.length);
      rows.forEach(({ e, k }, j) => {
        const [lo, hi] = wilson(k, n), [name, variant] = label(e.cert.run.model_id);
        const col = h('button', { class: 'col' + (lora(e) ? ' lora' : ''), style: `--v:${shown ? k / n : 0};--lo:${lo};--hi:${hi};--d:${j * 60}ms`,
          'aria-label': `${e.cert.run.model_id}: ${k} of ${n} correct, ${pc(k / n)}; 95% interval ${pc(lo)} to ${pc(hi)}. Opens the certificate in the verifier.` },
          h('span', { class: 'track' }, h('span', { class: 'whisker' }), h('span', { class: 'fill' }), h('span', { class: 'val' }, pc(k / n))),
          h('span', { class: 'lab' }, h('span', { class: 'n' }, name), h('span', { class: 'v' }, variant || ' ')));
        col.dataset.final = k / n;
        const on = () => show(col, e, k, n, lo, hi);
        col.addEventListener('pointerenter', on); col.addEventListener('focus', on);
        col.addEventListener('pointerleave', hide); col.addEventListener('blur', hide);
        col.addEventListener('click', () => {
          const b = [...document.querySelectorAll('.cert-btn')].find((x) => x.dataset.file === e.file);
          if (b) { $('#verify').scrollIntoView({ behavior: reduced ? 'auto' : 'smooth' }); b.click(); }
        });
        plot.append(col);
      });
      const anyLora = rows.some(({ e }) => lora(e));
      $('#vizKey').replaceChildren(h('span', { class: 'sw' }), 'Answered correctly', h('span', { class: 'sw ci' }), '95% interval',
        ...(anyLora ? [h('span', { class: 'sw hatch' }), 'Abliterated: the base model plus a LoRA adapter that removes refusal training'] : []));
      if (shown) requestAnimationFrame(() => plot.querySelectorAll('.col').forEach((c) => c.style.setProperty('--v', c.dataset.final)));
    }
    document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') hide(); });
    draw(start);
    new IntersectionObserver((es, o) => { if (es[0].isIntersecting) { o.disconnect(); shown = true; plot.querySelectorAll('.col').forEach((c) => c.style.setProperty('--v', c.dataset.final)); } }, ONSCREEN).observe(plot);
  }
  function explorer() {
    const RR = F.rounds.filter((rd) => rd.certs[0].cert.audit.reveals.length);  // a zero-reveal round has nothing to explore
    let ri = 0, filt = 'all';
    const tabs = $('#exRound'), fl = $('#exFilter');
    const draw = () => {
      const rd = RR[ri], qa = $('#qa'); qa.innerHTML = '';
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
      clamp(qa, 6, 'questions');
    };
    RR.forEach((rd, i) => { const c = h('button', { class: 'chip' + (i === 0 ? ' on' : ''), 'aria-pressed': String(i === 0) }, `Round ${rd.id.slice(-1)} · ${rd.cap.toLocaleString('en')} tokens`); c.addEventListener('click', () => { ri = i; press(tabs, c); draw(); lead(); }); tabs.append(c); });
    [['all', 'All revealed'], ['correct', 'Correct'], ['wrong', 'Wrong'], ['format', 'Format'], ['cut', 'Cut off']].forEach(([k, label], i) => {
      const c = h('button', { class: 'chip' + (i === 0 ? ' on' : ''), 'aria-pressed': String(i === 0) }, label); c.addEventListener('click', () => { filt = k; press(fl, c); draw(); }); fl.append(c); });
    const lead = () => { const c0 = RR[ri].certs[0].cert, n = c0.benchmark.n, d = DISCLOSURE[RR[ri].id] || { revealed: c0.audit.reveals.length, indirect: 0 };
      $('#exLead').textContent = `A NEAR block that didn't exist when the results were committed chose these ${d.revealed} of ${n}.` + (d.indirect ? ` ${d.indirect} more is disclosed indirectly (it shares a cited docs line with revealed items), so ${n - d.revealed - d.indirect} stay private.` : ` The other ${n - d.revealed} stay private.`) + ' Miss types are a reading aid computed from the revealed bytes, not a score.'; };
    draw(); lead();
  }
  function steps() {
    const S = [['Seal', 'The owner commits a Merkle root of the salted questions and the scoring policy on NEAR.'],
      ['Run', 'Each question goes to a TEE model on NEAR AI Cloud. Its attested key signs the exact request and response. In an asked-once round a TEE makes these calls itself and keeps one answer per question, counting any retry.'],
      ['Commit', 'Each run\'s result root and total go on chain, numbered per model.'],
      ['Close', 'The round closes. No more runs can join it.'],
      ['Check', 'A NEAR block finalized after the close picks a sample to reveal, and a TEE scores every answer. A round can reveal nothing and rely on the TEE alone.'],
      ['Verify', 'Anyone checks every signature and commitment against the chain, re-scores what was revealed, and checks the TEE\'s score of every answer.']];
    S.forEach(([t, d], i) => $('#steps').append(h('div', { class: 'panel step' }, h('b', {}, String(i + 1).padStart(2, '0')), h('h4', {}, t), h('p', {}, d))));
  }
  function refusals() {
    for (const f of F.manifest) { const cant = f.expected.startsWith('CANT'), ok = f.expected.startsWith('VERIFIED');
      $('#refList').append(h('div', { class: 'panel ref' + (cant ? ' cant' : ok ? ' ok' : '') }, h('code', {}, f.expected.replace('CANT_CERTIFY', "CAN'T CERTIFY")), h('p', {}, f.mutation.replace(/ \(review \d+\)/g, '')))); }
    clamp($('#refList'), 8, 'tests');
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
    await Promise.all([load('vendor/noble.js', 'signature checker'), load('vendor/yaml.js', 'deployment trace reader'), load('verify.js', 'verifier'), load('data.js', 'certificates')]);
    F = window.FUIN; V = window.FuinVerify;
    const vl = $('#verifyLoading'); if (vl) vl.remove();
    picker(); chart(); results(); explorer(); refusals();
    $('#buildInfo').append('Page data from commit ', h('a', { href: 'https://github.com/fexx301/fuin/tree/' + F.commit }, F.commit), ` · ${F.generated_utc}`);
    // the TDX verifier (1.4 MB of WASM) is only needed partway through a run; verify.js waits on this promise
    window.DcapReady = load('vendor/dcap.js', 'Intel TDX verifier');
  }
  const themeBtn = $('#themeBtn'), root = document.documentElement;
  const showTheme = () => { const lit = root.dataset.theme === 'light'; themeBtn.textContent = lit ? 'Dark' : 'Light'; themeBtn.setAttribute('aria-label', `Switch to ${lit ? 'dark' : 'light'} theme`); };
  themeBtn.addEventListener('click', () => {
    const lit = root.dataset.theme !== 'light';
    if (lit) root.dataset.theme = 'light'; else delete root.dataset.theme;
    try { localStorage.setItem('fuin-theme', lit ? 'light' : 'dark'); } catch (e) { /* private window: the choice lasts for this visit */ }
    showTheme(); dispatchEvent(new Event('fuin-theme'));
  });
  showTheme();
  const menu = $('#menuBtn'); menu.addEventListener('click', () => { const open = document.body.classList.toggle('menu-open'); menu.setAttribute('aria-expanded', String(open)); });
  document.querySelectorAll('nav .links a').forEach((a) => a.addEventListener('click', () => { document.body.classList.remove('menu-open'); menu.setAttribute('aria-expanded', 'false'); }));
  // nav: mark the link of the section crossing a line 40% down the screen; the hero and sections without a link clear it
  const spy = new IntersectionObserver((es) => es.forEach((e) => {
    if (!e.isIntersecting) return;
    const href = '#' + (e.target.dataset.nav || e.target.id);
    document.querySelectorAll('nav .links a').forEach((a) => a.getAttribute('href') === href ? a.setAttribute('aria-current', 'location') : a.removeAttribute('aria-current'));
  }), { rootMargin: '-40% 0px -60% 0px' });
  document.querySelectorAll('header.hero, main section').forEach((s) => spy.observe(s));
  buildCoin(); hero(); steps();
  document.querySelectorAll('#how .split ul').forEach((u) => clamp(u, 4, 'points'));
  document.querySelectorAll('[data-copy]').forEach((b) => b.addEventListener('click', async () => { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = 'Copied'; setTimeout(() => (b.textContent = 'Copy'), 1400); }));
  boot().catch((e) => { const vs = $('#verifyLoading'); if (vs) vs.textContent = 'Could not load the verifier: ' + e + '. Reload to try again.'; });
})();
