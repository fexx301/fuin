/* Fūin in-browser verifier: a port of src/fuin/verify.py for every check a browser can do.
 * Local: schema, rows, Merkle roots (RFC 8785 + domain-tagged SHA-256), sealed policy, every EIP-191 signature,
 * revealed proofs, exact request bytes, re-score. Network (NEAR RPC, CORS-enabled): registry record, transaction
 * receipts, seed block, audit sample; the Intel TDX quote (Phala's WebAssembly build of dcap-qvl, collateral from a public
 * PCCS mirror) against the approved application and OS measurements; a TEE score's OutLayer record (its TDX quote, task
 * hash, the worker's approval at the execution's block, the request and result on chain), which is a zero-reveal round's
 * only score check. Not in a browser: NVIDIA's GPU verdict (NRAS blocks
 * browsers) and the deployment trace. VERIFIED therefore needs fuin verify's recorded result for those two on this exact,
 * unmodified certificate; otherwise the result is PARTIAL (run `fuin verify`). Needs globals: Noble, Dcap, crypto.subtle, fetch.
 */
(function (root) {
  'use strict';
  const enc = new TextEncoder();
  const dec = new TextDecoder('utf-8', { fatal: true });

  class Refused extends Error { constructor(code, where) { super(code); this.code = code; this.where = where; } }
  class CantCertify extends Error { constructor(code) { super(code); this.code = code; } }
  class Unavailable extends Error {}
  const COLLATERAL = new Map();  // Intel-signed TDX collateral per quote, cached for the session (verify() still checks it every time)
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
  // Python 3.13 (Unicode 15.1) behaviour the sealed scorers rely on, generated from Python, not hand-written:
  // str.isspace() characters, the zero of every decimal-digit run (Nd), and the code points where str.casefold()
  // differs from per-character toLowerCase(). Re-generate if the reference Python changes.
  const PY_WS = "\t\n\u000b\f\r\u001c\u001d\u001e\u001f \u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000";
  const PY_DIGIT_ZEROS = [48, 1632, 1776, 1984, 2406, 2534, 2662, 2790, 2918, 3046, 3174, 3302, 3430, 3558, 3664, 3792, 3872, 4160, 4240, 6112, 6160, 6470, 6608, 6784, 6800, 6992, 7088, 7232, 7248, 42528, 43216, 43264, 43472, 43504, 43600, 44016, 65296, 66720, 68912, 69734, 69872, 69942, 70096, 70384, 70736, 70864, 71248, 71360, 71472, 71904, 72016, 72784, 73040, 73120, 73552, 92768, 92864, 93008, 120782, 120792, 120802, 120812, 120822, 123200, 123632, 124144, 125264, 130032];
  const PY_FOLD = {"\u00b5":"\u03bc","\u00df":"ss","\u0149":"\u02bcn","\u017f":"s","\u01f0":"j\u030c","\u0345":"\u03b9","\u0390":"\u03b9\u0308\u0301","\u03b0":"\u03c5\u0308\u0301","\u03c2":"\u03c3","\u03d0":"\u03b2","\u03d1":"\u03b8","\u03d5":"\u03c6","\u03d6":"\u03c0","\u03f0":"\u03ba","\u03f1":"\u03c1","\u03f5":"\u03b5","\u0587":"\u0565\u0582","\u13a0":"\u13a0","\u13a1":"\u13a1","\u13a2":"\u13a2","\u13a3":"\u13a3","\u13a4":"\u13a4","\u13a5":"\u13a5","\u13a6":"\u13a6","\u13a7":"\u13a7","\u13a8":"\u13a8","\u13a9":"\u13a9","\u13aa":"\u13aa","\u13ab":"\u13ab","\u13ac":"\u13ac","\u13ad":"\u13ad","\u13ae":"\u13ae","\u13af":"\u13af","\u13b0":"\u13b0","\u13b1":"\u13b1","\u13b2":"\u13b2","\u13b3":"\u13b3","\u13b4":"\u13b4","\u13b5":"\u13b5","\u13b6":"\u13b6","\u13b7":"\u13b7","\u13b8":"\u13b8","\u13b9":"\u13b9","\u13ba":"\u13ba","\u13bb":"\u13bb","\u13bc":"\u13bc","\u13bd":"\u13bd","\u13be":"\u13be","\u13bf":"\u13bf","\u13c0":"\u13c0","\u13c1":"\u13c1","\u13c2":"\u13c2","\u13c3":"\u13c3","\u13c4":"\u13c4","\u13c5":"\u13c5","\u13c6":"\u13c6","\u13c7":"\u13c7","\u13c8":"\u13c8","\u13c9":"\u13c9","\u13ca":"\u13ca","\u13cb":"\u13cb","\u13cc":"\u13cc","\u13cd":"\u13cd","\u13ce":"\u13ce","\u13cf":"\u13cf","\u13d0":"\u13d0","\u13d1":"\u13d1","\u13d2":"\u13d2","\u13d3":"\u13d3","\u13d4":"\u13d4","\u13d5":"\u13d5","\u13d6":"\u13d6","\u13d7":"\u13d7","\u13d8":"\u13d8","\u13d9":"\u13d9","\u13da":"\u13da","\u13db":"\u13db","\u13dc":"\u13dc","\u13dd":"\u13dd","\u13de":"\u13de","\u13df":"\u13df","\u13e0":"\u13e0","\u13e1":"\u13e1","\u13e2":"\u13e2","\u13e3":"\u13e3","\u13e4":"\u13e4","\u13e5":"\u13e5","\u13e6":"\u13e6","\u13e7":"\u13e7","\u13e8":"\u13e8","\u13e9":"\u13e9","\u13ea":"\u13ea","\u13eb":"\u13eb","\u13ec":"\u13ec","\u13ed":"\u13ed","\u13ee":"\u13ee","\u13ef":"\u13ef","\u13f0":"\u13f0","\u13f1":"\u13f1","\u13f2":"\u13f2","\u13f3":"\u13f3","\u13f4":"\u13f4","\u13f5":"\u13f5","\u13f8":"\u13f0","\u13f9":"\u13f1","\u13fa":"\u13f2","\u13fb":"\u13f3","\u13fc":"\u13f4","\u13fd":"\u13f5","\u1c80":"\u0432","\u1c81":"\u0434","\u1c82":"\u043e","\u1c83":"\u0441","\u1c84":"\u0442","\u1c85":"\u0442","\u1c86":"\u044a","\u1c87":"\u0463","\u1c88":"\ua64b","\u1c89":"\u1c89","\u1e96":"h\u0331","\u1e97":"t\u0308","\u1e98":"w\u030a","\u1e99":"y\u030a","\u1e9a":"a\u02be","\u1e9b":"\u1e61","\u1e9e":"ss","\u1f50":"\u03c5\u0313","\u1f52":"\u03c5\u0313\u0300","\u1f54":"\u03c5\u0313\u0301","\u1f56":"\u03c5\u0313\u0342","\u1f80":"\u1f00\u03b9","\u1f81":"\u1f01\u03b9","\u1f82":"\u1f02\u03b9","\u1f83":"\u1f03\u03b9","\u1f84":"\u1f04\u03b9","\u1f85":"\u1f05\u03b9","\u1f86":"\u1f06\u03b9","\u1f87":"\u1f07\u03b9","\u1f88":"\u1f00\u03b9","\u1f89":"\u1f01\u03b9","\u1f8a":"\u1f02\u03b9","\u1f8b":"\u1f03\u03b9","\u1f8c":"\u1f04\u03b9","\u1f8d":"\u1f05\u03b9","\u1f8e":"\u1f06\u03b9","\u1f8f":"\u1f07\u03b9","\u1f90":"\u1f20\u03b9","\u1f91":"\u1f21\u03b9","\u1f92":"\u1f22\u03b9","\u1f93":"\u1f23\u03b9","\u1f94":"\u1f24\u03b9","\u1f95":"\u1f25\u03b9","\u1f96":"\u1f26\u03b9","\u1f97":"\u1f27\u03b9","\u1f98":"\u1f20\u03b9","\u1f99":"\u1f21\u03b9","\u1f9a":"\u1f22\u03b9","\u1f9b":"\u1f23\u03b9","\u1f9c":"\u1f24\u03b9","\u1f9d":"\u1f25\u03b9","\u1f9e":"\u1f26\u03b9","\u1f9f":"\u1f27\u03b9","\u1fa0":"\u1f60\u03b9","\u1fa1":"\u1f61\u03b9","\u1fa2":"\u1f62\u03b9","\u1fa3":"\u1f63\u03b9","\u1fa4":"\u1f64\u03b9","\u1fa5":"\u1f65\u03b9","\u1fa6":"\u1f66\u03b9","\u1fa7":"\u1f67\u03b9","\u1fa8":"\u1f60\u03b9","\u1fa9":"\u1f61\u03b9","\u1faa":"\u1f62\u03b9","\u1fab":"\u1f63\u03b9","\u1fac":"\u1f64\u03b9","\u1fad":"\u1f65\u03b9","\u1fae":"\u1f66\u03b9","\u1faf":"\u1f67\u03b9","\u1fb2":"\u1f70\u03b9","\u1fb3":"\u03b1\u03b9","\u1fb4":"\u03ac\u03b9","\u1fb6":"\u03b1\u0342","\u1fb7":"\u03b1\u0342\u03b9","\u1fbc":"\u03b1\u03b9","\u1fbe":"\u03b9","\u1fc2":"\u1f74\u03b9","\u1fc3":"\u03b7\u03b9","\u1fc4":"\u03ae\u03b9","\u1fc6":"\u03b7\u0342","\u1fc7":"\u03b7\u0342\u03b9","\u1fcc":"\u03b7\u03b9","\u1fd2":"\u03b9\u0308\u0300","\u1fd3":"\u03b9\u0308\u0301","\u1fd6":"\u03b9\u0342","\u1fd7":"\u03b9\u0308\u0342","\u1fe2":"\u03c5\u0308\u0300","\u1fe3":"\u03c5\u0308\u0301","\u1fe4":"\u03c1\u0313","\u1fe6":"\u03c5\u0342","\u1fe7":"\u03c5\u0308\u0342","\u1ff2":"\u1f7c\u03b9","\u1ff3":"\u03c9\u03b9","\u1ff4":"\u03ce\u03b9","\u1ff6":"\u03c9\u0342","\u1ff7":"\u03c9\u0342\u03b9","\u1ffc":"\u03c9\u03b9","\ua7cb":"\ua7cb","\ua7cc":"\ua7cc","\ua7ce":"\ua7ce","\ua7d2":"\ua7d2","\ua7d4":"\ua7d4","\ua7da":"\ua7da","\ua7dc":"\ua7dc","\uab70":"\u13a0","\uab71":"\u13a1","\uab72":"\u13a2","\uab73":"\u13a3","\uab74":"\u13a4","\uab75":"\u13a5","\uab76":"\u13a6","\uab77":"\u13a7","\uab78":"\u13a8","\uab79":"\u13a9","\uab7a":"\u13aa","\uab7b":"\u13ab","\uab7c":"\u13ac","\uab7d":"\u13ad","\uab7e":"\u13ae","\uab7f":"\u13af","\uab80":"\u13b0","\uab81":"\u13b1","\uab82":"\u13b2","\uab83":"\u13b3","\uab84":"\u13b4","\uab85":"\u13b5","\uab86":"\u13b6","\uab87":"\u13b7","\uab88":"\u13b8","\uab89":"\u13b9","\uab8a":"\u13ba","\uab8b":"\u13bb","\uab8c":"\u13bc","\uab8d":"\u13bd","\uab8e":"\u13be","\uab8f":"\u13bf","\uab90":"\u13c0","\uab91":"\u13c1","\uab92":"\u13c2","\uab93":"\u13c3","\uab94":"\u13c4","\uab95":"\u13c5","\uab96":"\u13c6","\uab97":"\u13c7","\uab98":"\u13c8","\uab99":"\u13c9","\uab9a":"\u13ca","\uab9b":"\u13cb","\uab9c":"\u13cc","\uab9d":"\u13cd","\uab9e":"\u13ce","\uab9f":"\u13cf","\uaba0":"\u13d0","\uaba1":"\u13d1","\uaba2":"\u13d2","\uaba3":"\u13d3","\uaba4":"\u13d4","\uaba5":"\u13d5","\uaba6":"\u13d6","\uaba7":"\u13d7","\uaba8":"\u13d8","\uaba9":"\u13d9","\uabaa":"\u13da","\uabab":"\u13db","\uabac":"\u13dc","\uabad":"\u13dd","\uabae":"\u13de","\uabaf":"\u13df","\uabb0":"\u13e0","\uabb1":"\u13e1","\uabb2":"\u13e2","\uabb3":"\u13e3","\uabb4":"\u13e4","\uabb5":"\u13e5","\uabb6":"\u13e6","\uabb7":"\u13e7","\uabb8":"\u13e8","\uabb9":"\u13e9","\uabba":"\u13ea","\uabbb":"\u13eb","\uabbc":"\u13ec","\uabbd":"\u13ed","\uabbe":"\u13ee","\uabbf":"\u13ef","\ufb00":"ff","\ufb01":"fi","\ufb02":"fl","\ufb03":"ffi","\ufb04":"ffl","\ufb05":"st","\ufb06":"st","\ufb13":"\u0574\u0576","\ufb14":"\u0574\u0565","\ufb15":"\u0574\u056b","\ufb16":"\u057e\u0576","\ufb17":"\u0574\u056d","\ud803\udd50":"\ud803\udd50","\ud803\udd51":"\ud803\udd51","\ud803\udd52":"\ud803\udd52","\ud803\udd53":"\ud803\udd53","\ud803\udd54":"\ud803\udd54","\ud803\udd55":"\ud803\udd55","\ud803\udd56":"\ud803\udd56","\ud803\udd57":"\ud803\udd57","\ud803\udd58":"\ud803\udd58","\ud803\udd59":"\ud803\udd59","\ud803\udd5a":"\ud803\udd5a","\ud803\udd5b":"\ud803\udd5b","\ud803\udd5c":"\ud803\udd5c","\ud803\udd5d":"\ud803\udd5d","\ud803\udd5e":"\ud803\udd5e","\ud803\udd5f":"\ud803\udd5f","\ud803\udd60":"\ud803\udd60","\ud803\udd61":"\ud803\udd61","\ud803\udd62":"\ud803\udd62","\ud803\udd63":"\ud803\udd63","\ud803\udd64":"\ud803\udd64","\ud803\udd65":"\ud803\udd65","\ud81b\udea0":"\ud81b\udea0","\ud81b\udea1":"\ud81b\udea1","\ud81b\udea2":"\ud81b\udea2","\ud81b\udea3":"\ud81b\udea3","\ud81b\udea4":"\ud81b\udea4","\ud81b\udea5":"\ud81b\udea5","\ud81b\udea6":"\ud81b\udea6","\ud81b\udea7":"\ud81b\udea7","\ud81b\udea8":"\ud81b\udea8","\ud81b\udea9":"\ud81b\udea9","\ud81b\udeaa":"\ud81b\udeaa","\ud81b\udeab":"\ud81b\udeab","\ud81b\udeac":"\ud81b\udeac","\ud81b\udead":"\ud81b\udead","\ud81b\udeae":"\ud81b\udeae","\ud81b\udeaf":"\ud81b\udeaf","\ud81b\udeb0":"\ud81b\udeb0","\ud81b\udeb1":"\ud81b\udeb1","\ud81b\udeb2":"\ud81b\udeb2","\ud81b\udeb3":"\ud81b\udeb3","\ud81b\udeb4":"\ud81b\udeb4","\ud81b\udeb5":"\ud81b\udeb5","\ud81b\udeb6":"\ud81b\udeb6","\ud81b\udeb7":"\ud81b\udeb7","\ud81b\udeb8":"\ud81b\udeb8"};
  const PY_DIGIT = new Map();
  for (const z of PY_DIGIT_ZEROS) for (let d = 0; d < 10; d++) PY_DIGIT.set(String.fromCodePoint(z + d), String(d));
  const pyStrip = (s) => { const a = Array.from(s); let i = 0, j = a.length;
    while (i < j && PY_WS.includes(a[i])) i++; while (j > i && PY_WS.includes(a[j - 1])) j--; return a.slice(i, j).join(''); };
  const pyFold = (s) => Array.from(s, (ch) => PY_FOLD[ch] ?? ch.toLowerCase()).join('');  // per character: no final-sigma context
  const pyDigits = (s) => Array.from(s, (ch) => PY_DIGIT.get(ch) ?? ch).join('');  // Python's \d and Decimal accept any Nd digit
  function scoreText(item, content, v2) {
    let s = pyStrip(content); if (s.endsWith('.')) s = s.slice(0, -1);
    s = pyStrip(stripSet(pyStrip(s), v2 ? '`"\'*_' : '`"\''));
    if (item.answer_type === 'numeric') {
      s = pyDigits(s).replace(/(?<=\d)[,_](?=\d)/g, '');
      if (!NUMBER.test(s)) return 0;
      try { return absDiffLE(decimal(s), decimal(item.answer), decimal(item.tolerance || '0')) ? 1 : 0; } catch { return 0; }
    }
    if (item.answer_type === 'exact') return [item.answer, ...(item.accept || [])].some((a) => pyFold(a) === pyFold(s)) ? 1 : 0;
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
  // Finalized transactions and blocks fetched by height or hash never change, so one page visit asks for each once
  // (re-verifying under each cheat would otherwise trip public RPC rate limits). Answers at `final` finality (the registry
  // record, the account's keys, the chain head) are reused for a minute: a closed round's record can't change, and a
  // minute-old head only bounds the seed-block search. Keyed by the configured endpoint.
  const RPC_CACHE = new Map(), FINAL_TTL_MS = 60000;
  let RPC_FALLBACK = [];  // other archival endpoints, tried alternately on retries (set per verify from cfg.rpcFallback)
  async function rpc(url, method, params) {
    const immutable = method === 'EXPERIMENTAL_tx_status' || ((method === 'block' || method === 'query') && params.block_id != null);
    const key = immutable || params.finality === 'final' ? url + ' ' + method + ' ' + JSON.stringify(params) : null;
    const hit = key && RPC_CACHE.get(key);
    if (hit && (immutable || Date.now() - hit.at < FINAL_TTL_MS)) return hit.value;
    const urls = [url, ...RPC_FALLBACK.filter((u) => u !== url)];
    let last;
    for (let a = 0; a < 8; a++) {
      let wait = 600 * (a + 1);
      try {
        const r = await fetch(urls[a % urls.length], { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ jsonrpc: '2.0', id: 'fuin', method, params }) });
        // rate limited: back off exponentially (or as told), since public endpoints throttle bursts of verifications
        if (r.status === 429) wait = Math.max(Math.min(1000 * 2 ** a, 8000), 1000 * (Number(r.headers.get('retry-after')) || 0));
        if ([429, 502, 503, 504].includes(r.status)) throw new Error('HTTP ' + r.status);
        const d = await r.json();
        if (d.error) { const e = new Error(JSON.stringify(d.error).slice(0, 300)); e.rpc = true; throw e; }
        if (key) RPC_CACHE.set(key, { value: d.result, at: Date.now() });
        return d.result;
      } catch (e) { if (e.rpc) throw e; last = e; await new Promise((s) => setTimeout(s, wait)); }
    }
    throw new Unavailable(`${method}: ${last && last.message}`);
  }
  const viewCall = async (url, account, method, args, blockId) => {
    const at = blockId == null ? { finality: 'final' } : { block_id: blockId };
    const r = await rpc(url, 'query', { request_type: 'call_function', ...at, account_id: account, method_name: method, args_base64: btoa(JSON.stringify(args)) });
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

  // ---- Intel TDX quote: collateral from the PCCS mirror, then Intel's chain. dcap-qvl reports a network failure and an
  // unparseable quote with the same message, so ask the mirror directly: reachable means the quote is at fault (`code`),
  // unreachable means the evidence is unavailable. ----
  async function tdxVerify(quote, cacheKey, cfg, code) {
    let coll = COLLATERAL.get(cacheKey);
    if (!coll) try { coll = await root.Dcap.collateral(quote, cfg.pccs); COLLATERAL.set(cacheKey, coll); }
    catch (e) {
      let up = false;
      try { up = (await fetch(cfg.pccs.replace(/\/$/, '') + '/tdx/certification/v4/qe/identity')).ok; } catch { up = false; }
      if (!up) throw new Unavailable('TDX collateral service unreachable');
      throw new Refused(code);
    }
    try { return root.Dcap.verify(quote, coll); } catch (e) { throw new Refused(code); }
  }

  // ---- TEE score: ports of fuin/tee.py check_local (no network) and check_remote ----
  class TeeUnapproved extends Error {}  // genuine-looking evidence the verifier's pins don't cover: CAN'T CERTIFY, after later checks
  const isTee = (policy, S) => !!(policy && policy.audit && policy.audit.mode === S.tee_audit);
  const leInt = (v, signed) => { const b = new Uint8Array(8), d = new DataView(b.buffer); signed ? d.setBigInt64(0, BigInt(v), true) : d.setBigUint64(0, BigInt(v), true); return b; };
  async function taskHashV1(rec) {  // OutLayer's V1 preimage: fixed field order, UTF-8 strings, little-endian integers, absent optional fields omitted
    const s = (x) => enc.encode(x), parts = [s(rec.task_type), leInt(rec.task_id, true)];
    for (const k of ['repo_url', 'commit_hash', 'build_target', 'wasm_hash', 'input_hash']) if (rec[k] != null) parts.push(s(rec[k]));
    parts.push(s(rec.output_hash));
    if (rec.block_height != null) parts.push(leInt(rec.block_height, false));
    for (const k of ['caller_account_id', 'project_id', 'secrets_ref']) if (rec[k] != null) parts.push(s(rec[k]));
    parts.push(leInt(rec.timestamp, true));
    if (rec.attached_usd != null) parts.push(s(rec.attached_usd));
    return hex(await sha256(...parts));
  }
  async function teeLocal(ev, cert, cfg) {
    const need = (c, code = 'tee_score_invalid') => req(c, code), obj = (x) => !!x && typeof x === 'object' && !Array.isArray(x);
    need(obj(ev) && ev.v === 'fuin-tee-evidence-v1' && ['transaction_hash', 'input_data', 'scorer_url'].every((k) => typeof ev[k] === 'string'));
    const rec = ev.record, out = ev.output, b = cert.benchmark, r = cert.run;
    need(obj(rec) && obj(out));
    need(typeof rec.tdx_quote === 'string' && Number.isInteger(rec.task_id) && Number.isInteger(rec.timestamp)
      && ['task_type', 'output_hash', 'input_hash', 'wasm_hash'].every((k) => typeof rec[k] === 'string'));
    const pin = rec.wasm_hash;
    if (isTee(b.policy, cfg.supported) && pin !== b.policy.audit.scorer_wasm_sha256) throw new Refused('tee_score_mismatch');  // the sealed build
    need(rec.input_hash === hex(await sha256(enc.encode(ev.input_data))));
    need(rec.output_hash === hex(await sha256(enc.encode(jcs(out)))));  // = Python's sort_keys compact JSON for these strings and integers
    need(rec.transaction_hash === ev.transaction_hash && rec.task_type === 'execute' && rec.build_target === 'wasm32-wasip2');
    need(rec.caller_account_id === cert.registry.owner);
    let inp; try { inp = JSON.parse(ev.input_data); } catch { throw new Refused('tee_score_invalid'); }
    need(obj(inp) && inp.mode === 'score' && inp.blob_sha256 === out.blob_sha256);
    const signers = new Set(r.items.map((it) => it.signature.signing_address.toLowerCase()));
    need(out.v === 'fuin-tee-score-v1', 'tee_score_mismatch');
    need(out.model === r.model_id && out.n === b.n && out.total === r.total_score && out.benchmark_root === b.root && out.policy_hash === b.policy_hash
      && out.run_root === r.run_root && signers.size === 1 && signers.has(out.signer), 'tee_score_mismatch');
    const v2 = [cfg.supported.template_v2, cfg.supported.template_v3].includes(b.policy.request.template);  // nonces rebuilt from this block hash
    need((out.seal_block_hash ?? null) === (v2 ? b.seal_block_hash : null), 'tee_score_mismatch');
    // last, so tampered evidence is refused even when it also names an unpinned build
    if (!cfg.tee.pins.includes(pin) || ('executed_wasm_sha256' in rec ? rec.executed_wasm_sha256 : pin) !== pin) throw new TeeUnapproved('tee_unapproved');
    return { task: rec.task_id, pin };
  }
  async function teeRemote(ev, cert, cfg) {
    const rec = ev.record, T = cfg.tee, url = cfg.rpc, owner = cert.registry.owner;
    let quote; try { quote = b64(rec.tdx_quote); } catch { throw new Refused('tee_attestation_invalid'); }
    const res = await tdxVerify(quote, rec.tdx_quote, cfg, 'tee_attestation_invalid');
    const td = res.report.TD10 || res.report.TD15; req(!!td, 'tee_attestation_invalid');
    req(res.status !== 'Revoked' && (parseInt(td.td_attributes.slice(0, 2), 16) & 1) === 0, 'tee_attestation_invalid');
    if (rec.timestamp < T.v1_cutoff) throw new TeeUnapproved('tee_unapproved');
    const rd = td.report_data.toLowerCase();
    req(rd.slice(0, 64) === await taskHashV1(rec) && /^0*$/.test(rd.slice(64)), 'tee_attestation_invalid');
    const m = { mrtd: td.mr_td, rtmr0: td.rt_mr0, rtmr1: td.rt_mr1, rtmr2: td.rt_mr2, rtmr3: td.rt_mr3 };
    if (await viewCall(url, T.outlayer.register, 'is_measurements_approved', { measurements: m }, rec.block_height) !== true) throw new TeeUnapproved('tee_unapproved');
    const st = await rpc(url, 'EXPERIMENTAL_tx_status', { tx_hash: ev.transaction_hash, sender_account_id: owner, wait_until: 'FINAL' });
    const tx = st.transaction, call = (tx.actions && tx.actions[0] && tx.actions[0].FunctionCall) || {};
    req(tx.signer_id === owner && tx.receiver_id === T.outlayer.contract && call.method_name === 'request_execution', 'tee_score_invalid');
    let args; try { args = JSON.parse(dec.decode(b64(call.args))); } catch { throw new Refused('tee_score_invalid'); }
    req(args.input_data === ev.input_data && ((args.source || {}).WasmUrl || {}).hash === rec.wasm_hash, 'tee_score_invalid');
    const outs = [];
    for (const x of st.receipts_outcome) {
      const v = x.outcome.status.SuccessValue; if (!v) continue;
      try { let o = JSON.parse(dec.decode(b64(v))); if (typeof o === 'string') o = JSON.parse(o); outs.push(jcs(o)); } catch { /* not a JSON result */ }
    }
    req(outs.includes(jcs(ev.output)), 'tee_score_invalid');
    return `quote ${res.status}, task hash bound, worker approved at block ${rec.block_height}, request and result on chain`;
  }

  // ---- schema (subset of verify._validate: everything the browser reads) ----
  function validate(c, S) {
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
    str(b.seal_block_hash, 'benchmark.seal_block_hash');
    need(r.evidence === undefined || (r.evidence && typeof r.evidence === 'object' && !Array.isArray(r.evidence)), 'run.evidence');
    const tr = isTee(b.policy, S);  // a zero-reveal round has no sample, so no seed fields
    for (const k of ['k', 'close_height', ...(tr ? [] : ['D', 'seed_height'])]) num(a[k], 'audit.' + k);
    for (const k of ['close_tx', 'close_block_hash', ...(tr ? [] : ['seed_block_hash'])]) str(a[k], 'audit.' + k);
    if (!tr) n32(a.seed, 'audit.seed');
    need(Array.isArray(a.round_runs), 'audit.round_runs');
    need(Array.isArray(a.indices) && a.indices.every(Number.isInteger), 'audit.indices'); need(Array.isArray(a.reveals), 'audit.reveals');
    a.reveals.forEach((x, j) => {
      const w = `audit.reveals[${j}]`; need(x && Number.isInteger(x.i) && x.item && typeof x.item === 'object', w);
      str(x.item.question, w + '.item.question'); str(x.item.answer, w + '.item.answer'); need(['numeric', 'exact'].includes(x.item.answer_type), w + '.item.answer_type');
      n32(x.item.request_nonce, w + '.item.request_nonce'); n32(x.salt, w + '.salt');
      for (const k of ['proof_benchmark', 'proof_run']) { need(Array.isArray(x[k]) && x[k].length <= 64, `${w}.${k}`); x[k].forEach((h, q) => n32(h, `${w}.${k}[${q}]`)); }
      b64(x.request_b64); b64(x.response_b64);
    });
  }

  function makePolicy(n, models, S, scorerName, teeWasm, e2ee) {  // teeWasm: a zero-reveal round's sealed scorer build
    const { d, k } = auditSize(n);
    return { protocol: S.protocol, models, request: { template: e2ee ? S.template_v3 : teeWasm ? S.template_v2 : S.template, privacy_profile: S.privacy },
      scorer: { name: scorerName, sha256: S.scorers[scorerName] }, score: { values: [0, 1], aggregate: 'sum', denominator: n },
      audit: teeWasm ? { mode: S.tee_audit, k: 0, scorer_wasm_sha256: teeWasm } : { D: d, target: { numerator: 95, denominator: 100 }, k, sampler: S.sampler } };
  }

  /* verify(cert, cfg, onStep) → {outcome, code, detail, steps}. cfg: {supported, attested, registry, rpc, pccs, attestationPolicy, tee, recorded?}.
   * onStep(id, state, detail) with state in running|pass|fail|skip|info, for the UI. */
  async function verify(cert, cfg, onStep = () => {}) {
    RPC_FALLBACK = cfg.rpcFallback || [];
    const S = cfg.supported, deferred = [];
    let attMode = 'none';  // live: TDX checked here · recorded: shown from fuin verify · none: not checked
    let teeMode = 'none', zeroReveal = false;  // teeMode live: the TEE score's OutLayer record checked here
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
      await start('schema'); validate(cert, S); await pass('every field has the right type and form');
      const { benchmark: b, run: r, audit: a } = cert, n = b.n, items = r.items, tr = zeroReveal = isTee(b.policy, S);
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
        const sn = b.policy.scorer && b.policy.scorer.name, tw = tr ? b.policy.audit.scorer_wasm_sha256 : undefined;
        const e3 = !!b.policy.request && b.policy.request.template === S.template_v3;
        req(sn in S.scorers && (!tr || isHex32(tw)) && jcs(b.policy) === jcs(makePolicy(n, b.policy.models, S, sn, tw, e3)), 'policy_mismatch');
        // a sampled v3 round's reveals must be re-encrypted (secp256k1 ECDH), which this page doesn't do yet: say so
        if (e3 && !tr) throw new CantCertify('policy_unsupported');
        req(jcs(Object.keys(b.policy.models).sort()) === jcs([...b.models].sort()) && r.model_id in b.policy.models, 'policy_mismatch');
        req(Object.values(b.policy.models).every((s) => Object.keys(s).every((x) => S.allowed_settings.includes(x))), 'policy_mismatch');
        if (tr) {  // zero-reveal: no sample at all; every item is re-scored in the TEE instead
          k = 0;
          req(a.mode === S.tee_audit && a.k === 0 && a.indices.length === 0 && a.reveals.length === 0, 'audit_sample_mismatch');
          return `${S.protocol}; ${sn} (sha256 ${S.scorers[sn].slice(0, 12)}…); TEE-scored by scorer ${tw.slice(0, 12)}…, nothing revealed; ${S.template_v2}`;
        }
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
      const used = new Set(items.map((it) => it.signature.signing_address.toLowerCase()));
      await local('reveals', async () => {
        req(rv.length === k && rv.every((v, j) => j === 0 || v > rv[j - 1]) && rv.every((v) => v >= 0 && v < n), 'reveal_mismatch');
        for (const x of a.reveals) {
          const it = items[x.i], leaf = await benchmarkLeaf(x.i, unhex(x.salt), x.item);
          req(eq(leaf, bl[x.i]), 'reveal_mismatch');
          req(await verifyProof(leaf, x.i, n, x.proof_benchmark.map(unhex), unhex(b.root)), 'reveal_mismatch');
          req(await verifyProof(rl[x.i], x.i, n, x.proof_run.map(unhex), unhex(r.run_root)), 'reveal_mismatch');
          const rq = b64(x.request_b64), rs = b64(x.response_b64);
          req(hex(await sha256(rq)) === it.req_sha256 && hex(await sha256(rs)) === it.resp_sha256, 'signature_text_mismatch');
          const nonce = b.policy.request.template === S.template_v2  // v2: bound to the seal block, so no request predates the seal (v3 never reaches here)
            ? hex(await sha256(enc.encode('fuin-nonce-v2'), unhex(x.item.request_nonce), b58decode(b.seal_block_hash))) : x.item.request_nonce;
          const expected = enc.encode(JSON.stringify({ model: r.model_id, messages: [{ role: 'user', content: x.item.question }], stream: false, user: nonce, ...b.policy.models[r.model_id] }));
          req(eq(rq, expected), 'request_policy_mismatch');
          req(scoreResponse(x.item, rs, b.policy.scorer.name) === it.score, 'score_mismatch');
        }
        return tr ? 'none: a TEE-scored round reveals nothing; every item is re-scored inside the TEE (below)'
          : `${k}/${k} revealed: proofs pass, exact request rebuilt, re-score matches`;
      });

      // TEE score, local half first: a later outage can't hide evidence that contradicts the certificate
      const teeEv = (r.evidence || {}).tee_score;
      let teeInfo = null;
      if (tr && teeEv == null) deferred.push(['tee_score_missing', 'the sealed policy promises a TEE score and the certificate carries none']);
      if (teeEv != null) {
        await start('tee');
        try { teeInfo = await teeLocal(teeEv, cert, cfg); await onStep('tee', 'running', 'record matches the certificate; checking its quote and the chain…'); }
        catch (e) { if (!(e instanceof TeeUnapproved)) throw e; deferred.push(['tee_unapproved', 'the TEE scorer build is not the one this verifier pins']); await onStep('tee', 'fail', 'tee_unapproved'); }
      }

      const gpu = cfg.recorded ? 'GPU (NVIDIA NRAS) and deployment trace: recorded by fuin verify, not checked here'
        : 'GPU (NVIDIA NRAS blocks browsers) and deployment trace: not checked here; run fuin verify';
      const reps = r.model_report.model_attestations.filter((x) => used.has(String(x.signing_address).toLowerCase()));
      if (root.DcapReady && !root.Dcap) { await onStep('attestation', 'running', 'loading the Intel TDX verifier…'); try { await root.DcapReady; } catch { /* falls back below */ } }
      if (root.Dcap && reps.length && reps.every((x) => x.intel_quote)) {
        await online('attestation', async () => {
          const out = [];
          for (const rep of reps) {
            const res = await tdxVerify(unhex(rep.intel_quote), rep.intel_quote, cfg, 'attestation_invalid');
            req(res.status !== 'Revoked', 'tcb_revoked');
            const td = res.report.TD10 || res.report.TD15; req(!!td, 'attestation_invalid');
            const signer = String(rep.signing_address).toLowerCase().replace(/^0x/, '');
            req(td.report_data === signer.padEnd(64, '0') + r.preflight_nonce && rep.request_nonce === r.preflight_nonce, 'attestation_invalid');
            req((parseInt(td.td_attributes.slice(0, 2), 16) & 1) === 0, 'attestation_invalid');
            const compose = rep.info.tcb_info.app_compose, ch = hex(await sha256(enc.encode(compose)));
            req(td.mr_config_id === '01' + ch + '00'.repeat(15), 'attestation_invalid');
            let rt = new Uint8Array(48);
            for (const ev of rep.event_log) {
              if (ev.imr !== 3) continue;
              const le = new Uint8Array(4); new DataView(le.buffer).setUint32(0, ev.event_type, true);
              const d = new Uint8Array(await crypto.subtle.digest('SHA-384', concat([le, enc.encode(':' + ev.event + ':'), unhex(ev.event_payload)])));
              rt = new Uint8Array(await crypto.subtle.digest('SHA-384', concat([rt, d])));
            }
            req(hex(rt) === td.rt_mr3, 'attestation_invalid');
            // the application (compose hash) and the OS it runs on (MRTD, RTMR0-2, os_image_hash) must both be approved
            const entry = (cfg.attestationPolicy.models[r.model_id] || {})[ch];
            const osOk = !!entry && rep.info.os_image_hash === entry.os_image_hash
              && entry.os_measurements.some((m) => ['mr_td', 'rt_mr0', 'rt_mr1', 'rt_mr2'].every((k) => m[k] === td[k]));
            if (!osOk) {  // defer, like the CLI: later checks can still refuse
              deferred.push(['measurement_unapproved', '']);
              out.push(`quote ${res.status} but ${entry ? 'its OS measurements (MRTD, RTMR0-2) are' : `configuration ${ch.slice(0, 10)}… is`} not approved in ${cfg.attestationPolicy.version} (CAN'T CERTIFY measurement_unapproved)`); continue;
            }
            out.push(`quote ${res.status}${res.advisory_ids && res.advisory_ids.length ? ' (advisories ' + res.advisory_ids.join(',') + ')' : ''}, signer+nonce bound, debug off, MRCONFIGID and RTMR3 match, compose ${ch.slice(0, 10)}… and OS ${td.mr_td.slice(0, 10)}… approved by ${cfg.attestationPolicy.version}`);
          }
          attMode = 'live';
          return `TDX checked in your browser: ${out.join('; ')}. ${gpu}`;
        });
      } else {
        await start('attestation');
        attMode = cfg.recorded ? 'recorded' : 'none';
        await onStep('attestation', cfg.recorded ? 'info' : 'skip', cfg.recorded ? `recorded by fuin verify, not checked here: ${cfg.recorded}` : 'not checked here: the Intel TDX verifier did not load or the certificate has no quote. Run fuin verify.');
      }

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
        const sealHdr = await block(url, b.seal_height);  // the hash a v2 template binds every request nonce to
        req(sealHdr && sealHdr.hash === b.seal_block_hash, 'record_mismatch');
        const keys = (await rpc(url, 'query', { request_type: 'view_access_key_list', finality: 'final', account_id: reg.account })).keys.length;
        rec = got;
        return `seal ${b.seal_height} < commit ${r.commit_height} < close ${a.close_height} on ${reg.account}; ${keys === 0 ? 'locked (0 access keys)' : keys + ' access key(s): code replaceable'}`;
      });
      await online('sample', async () => {
        if (!rec) throw new Unavailable('registry unavailable');
        const closeHdr = await block(url, a.close_height);
        req(closeHdr && closeHdr.hash === a.close_block_hash, 'audit_sample_mismatch');
        const runs = rec.runs.map((x) => ({ model_id: x.model_id, run_index: x.run_index, run_root: x.run_root, total_score: x.total_score }))
          .sort((p, q) => (p.model_id < q.model_id ? -1 : p.model_id > q.model_id ? 1 : p.run_index - q.run_index));
        req(jcs(runs) === jcs(a.round_runs), 'audit_sample_mismatch');
        if (tr) return `closed at ${a.close_height} with ${runs.length} runs; no sample: a TEE-scored round reveals nothing`;
        const thr = a.close_height + 2, fin = (await block(url, null)).height;
        let seedHdr = null;
        for (let h = thr; h <= fin && !seedHdr; h++) { const x = await block(url, h); if (x) seedHdr = x; }
        req(seedHdr && seedHdr.prev_height < thr && seedHdr.height === a.seed_height && seedHdr.hash === a.seed_block_hash, 'audit_sample_mismatch');
        const ctx = { network: reg.network, registry: reg.account, owner: rec.owner, benchmark_id: rec.benchmark_id, benchmark_root: rec.root,
          policy_hash: rec.policy_hash, close_height: rec.close_height, close_block_hash: closeHdr.hash, runs };
        const seed = await sha256(enc.encode('fuin-audit-v1'), b58decode(seedHdr.hash), await sha256(enc.encode(jcs(ctx))));
        const derived = await sampleIndices(seed, n, k);
        req(hex(seed) === a.seed && jcs(derived) === jcs(a.indices), 'audit_sample_mismatch');
        req(jcs(rv) === jcs(derived), 'reveal_mismatch');
        return `seed block ${seedHdr.height} (first final block ≥ close+2) re-derives the ${k} audited items`;
      });
      if (teeInfo && !root.Dcap) await onStep('tee', 'skip', 'record matches the certificate, but its quote is not checked here: the Intel TDX verifier did not load. Run fuin verify.');
      else if (teeInfo) {
        await start('tee');
        try {
          const detail = await teeRemote(teeEv, cert, cfg); teeMode = 'live';
          await pass(`all ${n} items rebuilt and re-scored inside an OutLayer TDX enclave by scorer ${teeInfo.pin.slice(0, 12)}… (task ${teeInfo.task}): total ${r.total_score}/${n} and both roots match; ${detail}`);
        } catch (e) {
          if (e instanceof TeeUnapproved) { deferred.push(['tee_unapproved', "OutLayer worker measurements not approved at the execution's block, or legacy format"]); await onStep('tee', 'fail', 'tee_unapproved'); }
          else if (e instanceof Unavailable) { deferred.push(['evidence_unavailable', e.message]); await onStep('tee', 'skip', 'unavailable: ' + e.message); }
          else throw e;
        }
      }
    } catch (e) {
      if (e instanceof Refused) { await onStep(step, 'fail', e.code + (e.where ? ` (${e.where})` : '')); return { outcome: 'REFUSED', code: e.code, where: e.where }; }
      if (e instanceof CantCertify) { await onStep(step, 'fail', e.code); return { outcome: 'CANT_CERTIFY', code: e.code }; }
      await onStep(step, 'fail', 'certificate_invalid'); return { outcome: 'REFUSED', code: 'certificate_invalid', where: String(e && e.message).slice(0, 120) };
    }
    if (deferred.length) return { outcome: 'CANT_CERTIFY', code: deferred[0][0], detail: deferred[0][1] };
    const n = cert.benchmark.n, au = auditSize(n);
    if (attMode === 'none') return { outcome: 'PARTIAL', code: 'attestation not checked', attestation: attMode };
    // a zero-reveal round's only score check is its TEE score: without it here, nothing about the scores was checked
    if (zeroReveal && teeMode !== 'live') return { outcome: 'PARTIAL', code: 'TEE score not checked in this browser', attestation: attMode, tee: teeMode };
    if (!cfg.recorded) return { outcome: 'PARTIAL', code: 'GPU and deployment trace not checked in a browser', attestation: attMode, gpu: 'not checked' };
    const tee = `every item rebuilt and re-scored inside an OutLayer TDX enclave (checked here)`;
    const scope = zeroReveal ? `${tee}: the total is exact under the TEE trust assumptions; nothing revealed, all ${n} items stay private`
      : `audit passed ${au.k}/${n}; detection power ${(au.p * 100).toFixed(4)}% for ≥${au.d} incorrect scores (not the probability the total is correct)${teeMode === 'live' ? '; ' + tee : ''}`;
    return { outcome: 'VERIFIED', attestation: attMode, gpu: 'recorded', tee: teeMode, scope };
  }

  root.FuinVerify = { verify, jcs, auditSize, scoreText, scoreResponse, sha256, hex, b64 };
})(typeof window !== 'undefined' ? window : globalThis);
