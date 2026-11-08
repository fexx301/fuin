/* Fūin in-browser verifier: a port of src/fuin/verify.py for every check a browser can do.
 * Local: schema, rows, Merkle roots (RFC 8785 + domain-tagged SHA-256), sealed policy, every EIP-191 signature,
 * revealed proofs, exact request bytes, re-score. Network (NEAR RPC, CORS-enabled): registry record, transaction
 * receipts, seed block, audit sample; the Intel TDX quote (Phala's WebAssembly build of dcap-qvl, collateral from a public
 * PCCS mirror) against the approved application and OS measurements; the deployment trace (NEAR's attested deployment log
 * replayed to public compose files on GitHub, YAML read with js-yaml); a TEE score's OutLayer record (its TDX quote, task
 * hash, the worker's approval at the execution's block, the request and result on chain), which is a zero-reveal round's
 * only score check. Not in a browser: NVIDIA's GPU verdict (NRAS blocks browsers). VERIFIED therefore needs fuin verify's
 * recorded result for it on this exact, unmodified certificate; otherwise the result is PARTIAL (run `fuin verify`).
 * Needs globals: Noble, Yaml, Dcap, crypto.subtle, fetch.
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
  function decimal(s, sealed) { // exact: value = m * 10^e. A sealed answer or tolerance is read as Python's Decimal() reads
    // it: surrounding whitespace, Unicode digits, '_' between digits, and '.5' or '5.' forms (as the TEE scorer does)
    if (sealed) s = pyDigits(pyStrip(s)).replace(/(?<=\d)_(?=\d)/g, '');
    const m = s.match(sealed ? /^([-+]?)(\d*)(?:\.(\d*))?(?:[eE]([-+]?\d{1,9}))?$/ : /^([-+]?)(\d+)(?:\.(\d+))?(?:[eE]([-+]?\d+))?$/);
    if (!m || !(m[2] || m[3])) throw new Error('bad decimal');
    const frac = m[3] || ''; return { m: BigInt((m[1] === '-' ? '-' : '') + (m[2] || '') + frac || '0'), e: (m[4] ? parseInt(m[4], 10) : 0) - frac.length };
  }
  function sealedNumberOk(s, tolerance) {  // fuin/core.py sealed_number_ok: a finite decimal, magnitude within 10^±100, tolerance >= 0
    if (typeof s !== 'string') return false;
    let d; try { d = decimal(s, true); } catch { return false; }
    if (d.m === 0n) return true;
    const adjusted = (d.m < 0n ? -d.m : d.m).toString().length - 1 + d.e;
    return adjusted >= -100 && adjusted <= 100 && (!tolerance || d.m >= 0n);
  }
  function absDiffLE(a, b, tol) {  // Python: the exact difference rounded to 28 significant digits, half-even, then compared
    const sc = (x, e) => x.m * 10n ** BigInt(x.e - e), e = Math.min(a.e, b.e);
    let m = sc(a, e) - sc(b, e), de = e; if (m < 0n) m = -m;
    const digits = m.toString().length;
    if (m !== 0n && digits > 28) {
      const k = digits - 28, p = 10n ** BigInt(k), r = m % p, half = 5n * 10n ** BigInt(k - 1);
      m = m / p; if (r > half || (r === half && m % 2n === 1n)) m += 1n; de += k;
    }
    const e2 = Math.min(de, tol.e); return sc({ m, e: de }, e2) <= sc(tol, e2);
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
      try { return absDiffLE(decimal(s), decimal(item.answer, true), decimal(item.tolerance || '0', true)) ? 1 : 0; } catch { return 0; }
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
        // a throttled or retired endpoint (as fuin.near._transient): try the other one; any other error is the answer
        if (d.error) { const s = JSON.stringify(d.error), e = new Error(s.slice(0, 300)); e.rpc = !(d.error.code === -429 || /DEPRECATED|TOO_MANY_REQUESTS/i.test(s)); throw e; }
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
  async function txReceipt(url, tx, sender, executor, method) {  // {height, args} of the call's successful receipt, or null
    const r = await rpc(url, 'EXPERIMENTAL_tx_status', { tx_hash: tx, sender_account_id: sender, wait_until: 'FINAL' });
    const acts = {}; for (const x of r.receipts || []) acts[x.receipt_id] = ((x.receipt || {}).Action || {}).actions || [];
    acts[r.transaction_outcome.outcome.receipt_ids[0]] = r.transaction.actions;
    for (const ro of r.receipts_outcome) {
      if (ro.outcome.executor_id !== executor) continue;
      const call = (acts[ro.id] || []).filter((a) => a && a.FunctionCall).map((a) => a.FunctionCall).find((c) => c.method_name === method);
      if (!call) continue;
      if (!('SuccessValue' in ro.outcome.status)) return null;
      let args = null; try { args = JSON.parse(dec.decode(b64(call.args))); } catch { /* unreadable arguments match nothing */ }
      return { height: (await rpc(url, 'block', { block_id: ro.block_hash })).header.height, args };
    }
    return null;
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

  // ---- deployment trace: port of fuin/provenance.py trace(). NEAR's compose-manager attests its own action log with a
  // second TDX quote on the same machine; the log names each deployed compose file by repo commit and sha256. ----
  // as fuin.provenance.served_as: under its own name, as a LoRA adapter on the service's base weights (vLLM --lora-modules
  // JSON or SGLang --lora-paths name=path), or not at all
  function servedAs(cmd, model) {
    if (new RegExp('--served-model-name\\s+' + escRe(model) + '(\\s|$)').test(cmd)) return { adapter: null };
    let path = null;
    const after = cmd.split('--lora-modules').slice(1).join('--lora-modules');
    for (const obj of after.match(/\{[^{}]*\}/g) || []) {
      if (new RegExp('"name"\\s*:\\s*"' + escRe(model) + '"').test(obj)) { const pm = obj.match(/"path"\s*:\s*"([^"]+)"/); path = pm ? pm[1] : '?'; break; }
    }
    if (path === null) { const m = cmd.match(new RegExp('--lora-paths\\s+(?:\\S+=\\S+\\s+)*?' + escRe(model) + '=(\\S+)')); path = m ? m[1] : null; }
    if (path === null) return null;
    const hub = path.match(/models--([\w.-]+)--([\w.-]+)\/snapshots\/([0-9a-f]+)/);
    return { adapter: { path, weights: hub ? `${hub[1]}/${hub[2]}` : null, revision: hub ? hub[3] : null } };
  }
  class Untraced extends Error {}  // no log, or no deployed service serves the model: CAN'T CERTIFY deployment_untraced
  const escRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  async function traceDeployment(rep, nonce, tdModel, cfg) {
    const cma = rep.compose_manager_attestation;
    if (!cma) throw new Untraced('no compose_manager_attestation in the report');
    let ah;  // present, so anything malformed in it is invalid evidence, not a missing trace
    try {
      ah = hex(await sha256(enc.encode(jcs(cma.actions))));
      req(ah === cma.actions_hash && String(cma.nonce).toLowerCase() === nonce && String(cma.report_data).toLowerCase() === ah + nonce, 'attestation_invalid');
    } catch (e) { if (e instanceof Refused) throw e; throw new Refused('attestation_invalid'); }
    const res = await tdxVerify(unhex(cma.quote), cma.quote, cfg, 'attestation_invalid');
    const td = res.report.TD10 || res.report.TD15;
    req(!!td && td.report_data.toLowerCase() === ah + nonce, 'attestation_invalid');
    req(['mr_td', 'rt_mr0', 'rt_mr1', 'rt_mr2', 'mr_config_id', 'rt_mr3'].every((k) => td[k] === tdModel[k]), 'attestation_invalid');  // same CVM
    let repo;
    try { repo = JSON.parse(rep.info.tcb_info.app_compose).docker_compose_file.match(/GITHUB_REPO=https:\/\/github\.com\/([\w.-]+\/[\w.-]+?)(?:\.git)?\s/)[1]; }
    catch { throw new Untraced('measured app_compose pins no GITHUB_REPO'); }
    const files = new Map();
    const compose = async (a) => {
      const key = a.commit + ' ' + a.file;
      if (!files.has(key)) {
        let r; try { r = await fetch(`https://raw.githubusercontent.com/${repo}/${a.commit}/${a.file}`); } catch { throw new Unavailable('GitHub unreachable'); }
        if (r.status === 404 || r.status === 410) throw new Untraced(`${a.file}@${String(a.commit).slice(0, 10)} isn't in ${repo} (HTTP ${r.status})`);  // no trace, not an outage (review 9)
        if (!r.ok) throw new Unavailable(`GitHub HTTP ${r.status} for ${a.file}`);
        const bytes = new Uint8Array(await r.arrayBuffer());
        if (a.file_sha256) req(hex(await sha256(bytes)) === a.file_sha256, 'attestation_invalid');
        let doc; try { doc = root.Yaml.load(dec.decode(bytes)); } catch { throw new Untraced(`${a.file} does not parse as YAML`); }
        files.set(key, doc || {});
      }
      return files.get(key);
    };
    const latest = new Map();  // service -> the last up/down action that touched it
    for (const a of [...cma.actions].reverse()) {
      if (a.action !== 'compose_up' && a.action !== 'compose_down') continue;
      for (const n of (a.services && a.services.length ? a.services : Object.keys((await compose(a)).services || {}))) if (!latest.has(n)) latest.set(n, a);
    }
    const serving = [];
    for (const [name, a] of latest) {
      if (a.action !== 'compose_up') continue;
      const svc = ((await compose(a)).services || {})[name]; if (!svc) continue;
      const cmd = Array.isArray(svc.command) ? svc.command.join(' ') : String(svc.command ?? '');
      const how = servedAs(cmd, rep.model_name); if (!how) continue;
      const img = String(svc.image ?? ''), m = img.match(/([a-z0-9][\w./-]*@sha256:[0-9a-f]{64})/), path = cmd.match(/--model-path\s+(\S+)/);
      const cut = cmd.indexOf('--lora-modules'), base = cut < 0 ? cmd : cmd.slice(0, cut), lora = cut < 0 ? '' : cmd.slice(cut);
      const hub = (path ? path[1] : base).match(/models--([\w.-]+)--([\w.-]+)\/snapshots\/([0-9a-f]+)/), pos = cmd.match(/^\s*(?:vllm\s+serve\s+)?([\w.-]+\/[\w.-]+)(\s|$)/);
      const rev = JSON.stringify(svc.labels || {}).match(/model_revision:([0-9a-f]{7,40})/) || cmd.match(/--revision\s+([0-9a-f]{7,40})/);
      serving.push({ service: name, tag: a.tag, file: a.file, image: m ? m[1] : img, weights: hub ? `${hub[1]}/${hub[2]}` : (path ? path[1] : (pos ? pos[1] : '?')),
        revision: hub ? hub[3] : (rev ? rev[1] : null), shaChecked: !!a.file_sha256,
        loras: [...lora.matchAll(/"name"\s*:\s*"([^"]+)"/g)].map((x) => x[1]).filter((n) => n !== rep.model_name), adapter: how.adapter });
    }
    if (!serving.length) throw new Untraced(`no deployed service serves ${rep.model_name}, by --served-model-name or as a LoRA adapter`);
    // a trace has to pin what ran: a mutable tag, unknown weights or an unchecked compose file shows nothing (review 3; fuin/provenance.py)
    for (const x of serving) if (!(/^[a-z0-9][\w./-]*@sha256:[0-9a-f]{64}$/.test(x.image) && x.weights !== '?' && x.revision && x.shaChecked))
      throw new Untraced(`service ${x.service} isn't pinned: its image digest, weights, weights revision and compose sha256 are all required`);
    serving.sort((p, q) => (p.service < q.service ? -1 : p.service > q.service ? 1 : 0));
    return { repo, status: res.status, services: serving };
  }

  // ---- TEE score: ports of fuin/tee.py check_local (no network) and check_remote ----
  class TeeUnapproved extends Error {}  // genuine-looking evidence the verifier's pins don't cover: CAN'T CERTIFY, after later checks
  const isTee = (policy, S) => !!(policy && policy.audit && [S.tee_audit, S.tee_asked].includes(policy.audit.mode));  // zero-reveal
  const isAsked = (policy, S) => !!(policy && policy.audit && policy.audit.mode === S.tee_asked);
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
  const tObj = (x) => !!x && typeof x === 'object' && !Array.isArray(x);
  async function teeRecord(ev, cert, version, mode) {  // what a TEE score and a TEE grounding share (fuin/tee.py _check_record)
    const need = (c, code = 'tee_score_invalid') => req(c, code), obj = tObj;
    need(obj(ev) && ev.v === version && ['transaction_hash', 'input_data', 'scorer_url'].every((k) => typeof ev[k] === 'string'));
    const rec = ev.record, out = ev.output;
    need(obj(rec) && obj(out));
    need(typeof rec.tdx_quote === 'string' && Number.isInteger(rec.task_id) && Number.isInteger(rec.timestamp)
      && ['task_type', 'output_hash', 'input_hash', 'wasm_hash'].every((k) => typeof rec[k] === 'string'));
    need(rec.input_hash === hex(await sha256(enc.encode(ev.input_data))));
    need(rec.output_hash === hex(await sha256(enc.encode(jcs(out)))));  // = Python's sort_keys compact JSON for these strings and integers
    need(rec.transaction_hash === ev.transaction_hash && rec.task_type === 'execute' && rec.build_target === 'wasm32-wasip2');
    need(rec.caller_account_id === cert.registry.owner);
    let inp; try { inp = JSON.parse(ev.input_data); } catch { throw new Refused('tee_score_invalid'); }
    need(obj(inp) && inp.mode === mode && inp.blob_sha256 === out.blob_sha256);
    return { rec, out };
  }
  const tPinned = (rec, pins) => {  // last, so tampered evidence is refused even when it also names an unpinned build
    const pin = rec.wasm_hash;
    if (!pins.includes(pin) || ('executed_wasm_sha256' in rec ? rec.executed_wasm_sha256 : pin) !== pin) throw new TeeUnapproved('tee_unapproved');
    return pin;
  };
  async function teeLocal(ev, cert, cfg) {
    const need = (c, code = 'tee_score_invalid') => req(c, code), b = cert.benchmark, r = cert.run;
    const { rec, out } = await teeRecord(ev, cert, 'fuin-tee-evidence-v1', 'score');
    if (b.policy.audit.mode === cfg.supported.tee_audit && rec.wasm_hash !== b.policy.audit.scorer_wasm_sha256) throw new Refused('tee_score_mismatch');  // the sealed build
    need(out.v === 'fuin-tee-score-v1', 'tee_score_mismatch');
    runFields(out, cert, cfg, 'tee_score_mismatch');
    return { task: rec.task_id, pin: tPinned(rec, cfg.tee.pins), unreadable: out.unreadable };
  }
  function runFields(out, cert, cfg, code) {  // fuin/tee.py _run_fields: a TEE result for one run equals the certificate's run
    const b = cert.benchmark, r = cert.run, need = (c) => req(c, code);
    const signers = new Set(r.items.map((it) => it.signature.signing_address.toLowerCase()));
    need(out.model === r.model_id && out.n === b.n && out.total === r.total_score && out.benchmark_root === b.root && out.policy_hash === b.policy_hash
      && out.run_root === r.run_root && signers.size === 1 && signers.has(out.signer));
    const v2 = [cfg.supported.template_v2, cfg.supported.template_v3].includes(b.policy.request.template);  // nonces rebuilt from this block hash
    need((out.seal_block_hash ?? null) === (v2 ? b.seal_block_hash : null));
    if ('unreadable' in out)  // only end-to-end-encrypted rounds have answers that can fail to decrypt
      need(b.policy.request.template === cfg.supported.template_v3 && Number.isInteger(out.unreadable) && out.unreadable >= 0 && out.unreadable <= b.n);
  }
  async function askedLocal(ev, cert, cfg) {  // fuin/tee.py check_asked_local
    const { rec, out } = await teeRecord(ev, cert, 'fuin-tee-asked-evidence-v1', 'aggregate'), a = cert.benchmark.policy.audit;
    if (rec.wasm_hash !== a.asker_wasm_sha256 || rec.project_id !== a.asker_project) throw new Refused('tee_asked_mismatch');
    req(out.v === 'fuin-tee-asked-v1' && Number.isInteger(out.retried) && out.retried >= 0, 'tee_asked_mismatch');
    runFields(out, cert, cfg, 'tee_asked_mismatch');
    const pinned = (cfg.tee.askers || []).some((x) => x.wasm_sha256 === rec.wasm_hash && x.project === rec.project_id);
    if (!pinned || ('executed_wasm_sha256' in rec ? rec.executed_wasm_sha256 : rec.wasm_hash) !== rec.wasm_hash) throw new TeeUnapproved('tee_unapproved');
    return { task: rec.task_id, pin: rec.wasm_hash, project: rec.project_id, unreadable: out.unreadable, retried: out.retried };
  }
  async function askedCheckLocal(ev, cert, cfg) {  // fuin/tee.py check_asked_check_local: requests rebuilt with the seal block hash
    const { rec, out } = await teeRecord(ev, cert, 'fuin-tee-asked-check-evidence-v1', 'asked-check');
    req(out.v === 'fuin-tee-asked-check-v1' && !('unreadable' in out), 'tee_asked_mismatch');
    runFields(out, cert, cfg, 'tee_asked_mismatch');
    return { task: rec.task_id, pin: tPinned(rec, cfg.tee.asked_checkers || []) };
  }
  async function askedLock(cert, cfg) {  // fuin/tee.py check_asked_lock: the project was locked at the seal block
    const a = cert.benchmark.policy.audit, h = cert.benchmark.seal_height, proj = a.asker_project, acct = proj.split('/')[0];
    const q = (kind, extra) => rpc(cfg.rpc, 'query', { request_type: kind, block_id: h, account_id: acct, ...extra });
    const keys = (await q('view_access_key_list')).keys, code = (await q('view_account')).code_hash;
    req(Array.isArray(keys) && keys.length === 0 && code === '11111111111111111111111111111111', 'tee_asked_unlocked');
    const project = await viewCall(cfg.rpc, cfg.tee.outlayer.contract, 'get_project', { project_id: proj }, h);
    const versions = await viewCall(cfg.rpc, cfg.tee.outlayer.contract, 'list_versions', { project_id: proj, from_index: 0, limit: 10 }, h);
    req(project && project.owner === acct && project.active_version === a.asker_wasm_sha256 && Array.isArray(versions)
      && versions.length === 1 && versions[0].wasm_hash === a.asker_wasm_sha256, 'tee_asked_unlocked');
    return `${proj} was locked at the seal (block ${h}): its owner had no keys and no code, and its only version was the sealed asker`;
  }
  async function groundLocal(ev, cert, cfg) {  // fuin/tee.py check_ground_local
    const need = (c) => req(c, 'tee_ground_mismatch'), b = cert.benchmark, n = b.n;
    const { rec, out } = await teeRecord(ev, cert, 'fuin-tee-ground-evidence-v1', 'ground');
    need(out.v === 'fuin-tee-ground-v1' && out.repo === cfg.tee.ground_repo && out.n === n && out.benchmark_root === b.root);
    const f = out.flags;
    need(typeof f === 'string' && /^[0-9a-f]*$/.test(f) && f.length === Math.ceil(n / 8) * 2 && Number.isInteger(out.flagged));
    const bits = BigInt('0x' + (f || '0')), flagged = [];
    for (let i = 0; i < f.length * 4; i++) if ((bits >> BigInt(f.length * 4 - 1 - i)) & 1n) flagged.push(i);
    need(flagged.length === out.flagged && flagged.every((i) => i < n));
    const pin = tPinned(rec, cfg.tee.grounders);
    if (!cfg.tee.ground_commits.includes(out.commit)) throw new TeeUnapproved('tee_unapproved');  // a fork's commit is served under near/docs too
    return { task: rec.task_id, pin, commit: out.commit, flagged };
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
    const src = args.source || {}, pj = src.Project || {};  // by URL, or a project's exact version (the asker): the build the record attests
    const byUrl = (src.WasmUrl || {}).hash === rec.wasm_hash && rec.project_id == null, byProject = pj.project_id === rec.project_id && pj.version_key === rec.wasm_hash;
    req(args.input_data === ev.input_data && (byUrl || byProject), 'tee_score_invalid');
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
    // nested evidence too, so malformed input is refused here rather than crashing a later check (review 2; fuin/verify.py _validate)
    const hexBytes = (v) => typeof v === 'string' && v.length % 2 === 0 && /^[0-9a-fA-F]*$/.test(v);
    const isObj = (v) => !!v && typeof v === 'object' && !Array.isArray(v);
    const jsonObj = (v) => { if (isObj(v)) return true; if (typeof v !== 'string') return false; try { return isObj(JSON.parse(v)); } catch { return false; } };
    r.model_report.model_attestations.forEach((rep, j) => {
      const w = `run.model_report.model_attestations[${j}]`; need(isObj(rep), w);
      for (const k of ['signing_address', 'model_name', 'intel_quote', 'request_nonce']) need(typeof rep[k] === 'string', `${w}.${k}`);
      need(/^0x[0-9a-fA-F]{40}$/.test(rep.signing_address), `${w}.signing_address`); need(hexBytes(rep.intel_quote), `${w}.intel_quote`);
      need(Array.isArray(rep.event_log), w);  // the GPU payload is optional here: the page's certificates omit it (browsers can't reach NRAS)
      need(isObj(rep.info) && isObj(rep.info.tcb_info) && typeof rep.info.tcb_info.app_compose === 'string', `${w}.info.tcb_info.app_compose`);
      need(rep.event_log.length <= 1000, `${w}.event_log`);
      rep.event_log.forEach((e, q) => need(isObj(e) && Number.isInteger(e.imr) && Number.isInteger(e.event_type) && typeof e.event === 'string'
        && hexBytes(e.event_payload) && (e.digest == null || hexBytes(e.digest)), `${w}.event_log[${q}]`));
      if (rep.nvidia_payload !== undefined) need(jsonObj(rep.nvidia_payload), `${w}.nvidia_payload`);
      need(jsonObj(rep.info.tcb_info.app_compose), `${w}.info.tcb_info.app_compose`);
    });
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
      if (x.item.answer_type === 'numeric') {  // finite and within 10^±100, as fuin/core.py sealed_number_ok
        need(sealedNumberOk(x.item.answer, false), w + '.item.answer');
        need(!('tolerance' in x.item) || sealedNumberOk(x.item.tolerance, true), w + '.item.tolerance');
      }
      n32(x.item.request_nonce, w + '.item.request_nonce'); n32(x.salt, w + '.salt');
      for (const k of ['proof_benchmark', 'proof_run']) { need(Array.isArray(x[k]) && x[k].length <= 64, `${w}.${k}`); x[k].forEach((h, q) => n32(h, `${w}.${k}[${q}]`)); }
      b64(x.request_b64); b64(x.response_b64);
    });
  }

  function makePolicy(n, models, S, scorerName, teeWasm, e2ee, asker) {  // teeWasm: a zero-reveal round's sealed scorer; asker: [build, project]
    const { d, k } = auditSize(n);
    return { protocol: S.protocol, models, request: { template: e2ee ? S.template_v3 : teeWasm || asker ? S.template_v2 : S.template, privacy_profile: S.privacy },
      scorer: { name: scorerName, sha256: S.scorers[scorerName] }, score: { values: [0, 1], aggregate: 'sum', denominator: n },
      audit: asker ? { mode: S.tee_asked, k: 0, asker_wasm_sha256: asker[0], asker_project: asker[1] }
        : teeWasm ? { mode: S.tee_audit, k: 0, scorer_wasm_sha256: teeWasm } : { D: d, target: { numerator: 95, denominator: 100 }, k, sampler: S.sampler } };
  }

  /* verify(cert, cfg, onStep) → {outcome, code, detail, steps}. cfg: {supported, attested, registry, rpc, pccs, attestationPolicy, tee, recorded?}.
   * onStep(id, state, detail) with state in running|pass|fail|skip|info, for the UI. */
  async function verify(cert, cfg, onStep = () => {}) {
    RPC_FALLBACK = cfg.rpcFallback || [];
    const S = cfg.supported, deferred = [];
    let attMode = 'none';  // live: TDX checked here · recorded: shown from fuin verify · none: not checked
    let teeMode = 'none', groundMode = 'none', zeroReveal = false;  // teeMode live: the TEE score's OutLayer record checked here
    let traceMode = 'none';  // live: the deployment trace replayed here
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
        const ak = isAsked(b.policy, S), sn = b.policy.scorer && b.policy.scorer.name, tw = tr && !ak ? b.policy.audit.scorer_wasm_sha256 : undefined;
        const asker = ak ? [b.policy.audit.asker_wasm_sha256, b.policy.audit.asker_project] : undefined;
        const e3 = !!b.policy.request && b.policy.request.template === S.template_v3;
        req(sn in S.scorers && (!tr || ak || isHex32(tw)) && (!ak || (isHex32(asker[0]) && typeof asker[1] === 'string'))
          && jcs(b.policy) === jcs(makePolicy(n, b.policy.models, S, sn, tw, e3, asker)), 'policy_mismatch');
        // a sampled v3 round's reveals must be re-encrypted (secp256k1 ECDH), which this page doesn't do yet: say so
        if (e3 && !tr) throw new CantCertify('policy_unsupported');
        req(jcs(Object.keys(b.policy.models).sort()) === jcs([...b.models].sort()) && r.model_id in b.policy.models, 'policy_mismatch');
        req(Object.values(b.policy.models).every((s) => Object.keys(s).every((x) => S.allowed_settings.includes(x))), 'policy_mismatch');
        // the TEE rebuilds each request from the canonical policy: integer or boolean settings, in sorted order (review 10; fuin/policy.py)
        if (tr) req(Object.values(b.policy.models).every((s) => jcs(Object.keys(s)) === jcs(Object.keys(s).sort())
          && Object.values(s).every((v) => Number.isInteger(v) || typeof v === 'boolean')), 'policy_mismatch');
        if (tr) {  // zero-reveal: no sample at all; every item is re-scored in the TEE instead
          k = 0;
          req(a.mode === b.policy.audit.mode && a.k === 0 && a.indices.length === 0 && a.reveals.length === 0, 'audit_sample_mismatch');
          const how = ak ? `asked once per item inside the TEE by asker ${asker[0].slice(0, 12)}… in ${asker[1]}` : `TEE-scored by scorer ${tw.slice(0, 12)}…`;
          return `${S.protocol}; ${sn} (sha256 ${S.scorers[sn].slice(0, 12)}…); ${how}, nothing revealed; ${b.policy.request.template}${e3 ? ' (end-to-end encrypted)' : ''}`;
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
      const asked = isAsked(b.policy, S), askedEv = (r.evidence || {}).tee_asked;
      if (tr && !asked && teeEv == null) deferred.push(['tee_score_missing', 'the sealed policy promises a TEE score and the certificate carries none']);
      if (asked && askedEv == null) deferred.push(['tee_asked_missing', 'the sealed policy promises enclave-asked answers and the certificate carries no aggregate']);
      const checkEv = (r.evidence || {}).tee_asked_check;
      if (asked && checkEv == null) deferred.push(['tee_asked_check_missing', "nothing shows the asked answers' requests were made after the seal"]);
      let askedInfo = null, checkInfo = null;
      if (asked && askedEv != null) {
        await start('asked');
        try { askedInfo = await askedLocal(askedEv, cert, cfg); await onStep('asked', 'running', 'aggregate matches the run; checking its quote, the chain and the project lock…'); }
        catch (e) { if (!(e instanceof TeeUnapproved)) throw e; deferred.push(['tee_unapproved', 'the asker build or its project is not one this verifier pins']); await onStep('asked', 'fail', 'tee_unapproved'); }
        if (checkEv != null) {
          try { checkInfo = await askedCheckLocal(checkEv, cert, cfg); }
          catch (e) { if (!(e instanceof TeeUnapproved)) throw e; deferred.push(['tee_unapproved', "the asked-check's scorer build is not one this verifier pins"]); await onStep('asked', 'fail', 'tee_unapproved'); }
        }
      }
      if (teeEv != null) {
        await start('tee');
        try { teeInfo = await teeLocal(teeEv, cert, cfg); await onStep('tee', 'running', 'record matches the certificate; checking its quote and the chain…'); }
        catch (e) { if (!(e instanceof TeeUnapproved)) throw e; deferred.push(['tee_unapproved', 'the TEE scorer build is not the one this verifier pins']); await onStep('tee', 'fail', 'tee_unapproved'); }
      }
      const groundEv = (r.evidence || {}).tee_ground;
      let groundInfo = null;
      if (groundEv != null) {
        await start('ground');
        try { groundInfo = await groundLocal(groundEv, cert, cfg); await onStep('ground', 'running', 'record matches the sealed root; checking its quote and the chain…'); }
        catch (e) { if (!(e instanceof TeeUnapproved)) throw e; deferred.push(['tee_unapproved', 'the grounding build, or the near/docs commit it cites, is not one this verifier pins']); await onStep('ground', 'fail', 'tee_unapproved'); }
      }

      const gpu = cfg.recorded ? 'GPU (NVIDIA NRAS): recorded by fuin verify, not checked here'
        : 'GPU (NVIDIA NRAS blocks browsers): not checked here; run fuin verify';
      const approvedTd = new Map();  // signer -> its model quote's measurements, for the same-machine check of the trace
      const reps = r.model_report.model_attestations.filter((x) => used.has(String(x.signing_address).toLowerCase()));
      if (root.DcapReady && !root.Dcap) { await onStep('attestation', 'running', 'loading the Intel TDX verifier…'); try { await root.DcapReady; } catch { /* falls back below */ } }
      let acceptedRep = null;  // the one report accepted for this run: the trace below uses it (review 4)
      if (root.Dcap && reps.length && reps.every((x) => x.intel_quote)) {
        await online('attestation', async () => {
          const out = [], accepted = [];
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
              if (ev.digest) req(hex(d) === String(ev.digest).toLowerCase(), 'attestation_invalid');  // a logged (non-empty) digest must match, as the CLI checks it
              rt = new Uint8Array(await crypto.subtle.digest('SHA-384', concat([rt, d])));
            }
            req(hex(rt) === td.rt_mr3, 'attestation_invalid');
            // the application (compose hash) and the OS it runs on (MRTD, RTMR0-2, os_image_hash) must both be approved
            // approved under the model the report names; exactly one report may be accepted, for the run's model (below)
            const entry = (cfg.attestationPolicy.models[rep.model_name] || {})[ch];
            const osOk = !!entry && rep.info.os_image_hash === entry.os_image_hash
              && entry.os_measurements.some((m) => ['mr_td', 'rt_mr0', 'rt_mr1', 'rt_mr2'].every((k) => m[k] === td[k]));
            if (!osOk) {
              out.push(`${rep.model_name}: quote ${res.status} but ${entry ? 'its OS measurements (MRTD, RTMR0-2) are' : `configuration ${ch.slice(0, 10)}… is`} not approved in ${cfg.attestationPolicy.version}`); continue;
            }
            accepted.push({ rep, td });
            out.push(`quote ${res.status}${res.advisory_ids && res.advisory_ids.length ? ' (advisories ' + res.advisory_ids.join(',') + ')' : ''}, signer+nonce bound, debug off, MRCONFIGID and RTMR3 match, compose ${ch.slice(0, 10)}… and OS ${td.mr_td.slice(0, 10)}… approved by ${cfg.attestationPolicy.version}`);
          }
          // like the CLI: one accepted report, for the run's model, from the run's one signer; else defer (later checks can still refuse)
          if (accepted.length !== 1 || used.size !== 1 || accepted[0].rep.model_name !== r.model_id) {
            deferred.push(['measurement_unapproved', '']); out.push(`not exactly one approved report for ${r.model_id} (CAN'T CERTIFY measurement_unapproved)`);
          } else {
            acceptedRep = accepted[0].rep; approvedTd.set(String(acceptedRep.signing_address).toLowerCase(), accepted[0].td);
          }
          attMode = 'live';
          return `TDX checked in your browser: ${out.join('; ')}. ${gpu}`;
        });
      } else {
        await start('attestation');
        attMode = cfg.recorded ? 'recorded' : 'none';
        await onStep('attestation', cfg.recorded ? 'info' : 'skip', cfg.recorded ? `recorded by fuin verify, not checked here: ${cfg.recorded}` : 'not checked here: the Intel TDX verifier did not load or the certificate has no quote. Run fuin verify.');
      }
      // the serving container, traced live from NEAR's attested deployment log when the model quote was checked here
      const rep0 = acceptedRep, tdModel = rep0 && approvedTd.get(String(rep0.signing_address).toLowerCase());
      if (attMode === 'live' && tdModel) {
        await start('trace');
        try {
          const tr = await traceDeployment(rep0, r.preflight_nonce, tdModel, cfg); traceMode = 'live';
          await pass(`compose-manager log (quote ${tr.status}) → ${tr.repo}: ` + tr.services.slice(0, 2).map((x) => `${x.service} @${x.tag} ${x.file} image …${x.image.slice(-12)} weights ${x.weights.split('/').pop()}`
            + (x.adapter ? ` + LoRA adapter ${x.adapter.weights || x.adapter.path}${x.adapter.revision ? ' rev ' + x.adapter.revision.slice(0, 10) : ''}` : '')
            + (x.loras.length ? ` (same instance also serves LoRA adapters under other names: ${x.loras.join(', ')})` : '')).join('; ')
            + (tr.services.length > 2 ? ` (+${tr.services.length - 2} more replicas)` : ''));
        } catch (e) {
          if (e instanceof Untraced) { deferred.push(['deployment_untraced', e.message]); await onStep('trace', 'fail', 'deployment_untraced'); }
          else if (e instanceof Unavailable) { deferred.push(['evidence_unavailable', e.message]); await onStep('trace', 'skip', 'unavailable: ' + e.message); }
          else throw e;
        }
      } else await onStep('trace', cfg.recorded ? 'info' : 'skip', cfg.recorded ? 'recorded by fuin verify, not checked here' : 'not checked here: needs the model quote checked first. Run fuin verify.');

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
        // the signed transactions' own arguments, not only the contract's state (its code isn't built reproducibly)
        const signed = { seal: { benchmark_id: b.id, root: b.root, n, policy_hash: b.policy_hash, models: b.models },
          commit_run: { benchmark_id: b.id, model_id: r.model_id, run_root: r.run_root, total_score: r.total_score }, close_round: { benchmark_id: b.id } };
        for (const [tx, m, h] of [[b.seal_tx, 'seal', b.seal_height], [r.commit_tx, 'commit_run', r.commit_height], [a.close_tx, 'close_round', a.close_height]]) {
          const rc = await txReceipt(url, tx, reg.owner, reg.account, m);
          req(rc && rc.height === h && jcs(rc.args) === jcs(signed[m]), 'record_mismatch');
        }
        req(got.seal_height < r.commit_height && r.commit_height < got.close_height, 'commit_order_invalid');
        const sealHdr = await block(url, b.seal_height);  // the hash a v2 template binds every request nonce to
        req(sealHdr && sealHdr.hash === b.seal_block_hash, 'record_mismatch');
        const keys = (await rpc(url, 'query', { request_type: 'view_access_key_list', finality: 'final', account_id: reg.account })).keys.length;
        rec = got;
        return `seal ${b.seal_height} < commit ${r.commit_height} < close ${a.close_height} on ${reg.account}; signed seal and commit arguments match; ${keys === 0 ? 'locked (0 access keys)' : keys + ' access key(s): code replaceable'}`;
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
          const u = teeInfo.unreadable, lost = u == null ? '' : `; ${u} unreadable answer${u === 1 ? '' : 's'} (counted inside the TEE)`;
          await pass(`all ${n} items rebuilt and re-scored inside an OutLayer TDX enclave by scorer ${teeInfo.pin.slice(0, 12)}… (task ${teeInfo.task}): total ${r.total_score}/${n} and both roots match${lost}; ${detail}`);
        } catch (e) {
          if (e instanceof TeeUnapproved) { deferred.push(['tee_unapproved', "OutLayer worker measurements not approved at the execution's block, or legacy format"]); await onStep('tee', 'fail', 'tee_unapproved'); }
          else if (e instanceof Unavailable) { deferred.push(['evidence_unavailable', e.message]); await onStep('tee', 'skip', 'unavailable: ' + e.message); }
          else throw e;
        }
      }
      if (askedInfo && !root.Dcap) await onStep('asked', 'skip', 'aggregate matches the run, but its quote is not checked here: the Intel TDX verifier did not load. Run fuin verify.');
      else if (askedInfo && checkInfo) {
        await start('asked');
        try {
          const detail = await teeRemote(askedEv, cert, cfg); await teeRemote(checkEv, cert, cfg);
          const lock = await askedLock(cert, cfg), rt = askedInfo.retried, u = askedInfo.unreadable;
          teeMode = 'live';  // the aggregate is this round's TEE score
          await pass(`all ${n} answers asked once inside an OutLayer TDX enclave by asker ${askedInfo.pin.slice(0, 12)}… in ${askedInfo.project} (aggregate task ${askedInfo.task}): `
            + `total ${r.total_score}/${n} and both roots match; ${rt} retried ask${rt === 1 ? '' : 's'} (no answer had left the enclave); `
            + `every request rebuilt with the seal block's hash by scorer ${checkInfo.pin.slice(0, 12)}… (task ${checkInfo.task}) equals the signed one, so every ask came after the seal`
            + (u == null ? '' : `; ${u} unreadable answer${u === 1 ? '' : 's'}`) + `; ${lock}; ${detail}`);
        } catch (e) {
          if (e instanceof TeeUnapproved) { deferred.push(['tee_unapproved', "OutLayer worker measurements not approved at the aggregate's block, or legacy format"]); await onStep('asked', 'fail', 'tee_unapproved'); }
          else if (e instanceof Unavailable) { deferred.push(['evidence_unavailable', e.message]); await onStep('asked', 'skip', 'unavailable: ' + e.message); }
          else throw e;
        }
      }
      if (groundInfo && !root.Dcap) await onStep('ground', 'skip', 'record matches the sealed root, but its quote is not checked here: the Intel TDX verifier did not load. Run fuin verify.');
      else if (groundInfo) {
        await start('ground');
        try {
          const detail = await teeRemote(groundEv, cert, cfg), f = groundInfo.flagged; groundMode = 'live';
          await pass(`${n - f.length}/${n} answer keys appear in their cited line of near/docs at ${groundInfo.commit.slice(0, 8)}, checked inside an OutLayer TDX enclave by build ${groundInfo.pin.slice(0, 12)}… (task ${groundInfo.task})`
            + (f.length ? `; ${f.length} flagged, not checked (a derived answer or a broader alternative): item${f.length === 1 ? '' : 's'} ${f.join(', ')}` : '') + `; ${detail}`);
        } catch (e) {
          if (e instanceof TeeUnapproved) { deferred.push(['tee_unapproved', "OutLayer worker measurements not approved at the grounding's block, or legacy format"]); await onStep('ground', 'fail', 'tee_unapproved'); }
          else if (e instanceof Unavailable) { deferred.push(['evidence_unavailable', e.message]); await onStep('ground', 'skip', 'unavailable: ' + e.message); }
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
    if (!cfg.recorded) return { outcome: 'PARTIAL', code: traceMode === 'live' ? 'GPU not checked in a browser' : 'GPU and deployment trace not checked in a browser', attestation: attMode, gpu: 'not checked', trace: traceMode };
    const tee = `every item rebuilt and re-scored inside an OutLayer TDX enclave (checked here)`;
    const askedRound = isAsked(cert.benchmark.policy, cfg.supported);
    const rt = askedRound && cert.run.evidence.tee_asked ? cert.run.evidence.tee_asked.output.retried : 0;
    const scope = askedRound ? `every item asked inside an OutLayer TDX enclave after the seal and scored there, its answer recorded once (checked here): the total is exact under the TEE trust assumptions; `
      + (rt ? `${rt} ask${rt === 1 ? '' : 's'} retried after a timeout, so a single draw per item could differ from this total by at most ${rt}` : 'no ask retried, so each item is a single draw') + `; nothing revealed, all ${n} items stay private`
      : zeroReveal ? `${tee}: the total is exact under the TEE trust assumptions; nothing revealed, all ${n} items stay private`
      : `audit passed ${au.k}/${n}; detection power ${(au.p * 100).toFixed(4)}% for ≥${au.d} incorrect scores (not the probability the total is correct)${teeMode === 'live' ? '; ' + tee : ''}`;
    return { outcome: 'VERIFIED', attestation: attMode, gpu: 'recorded', tee: teeMode, ground: groundMode, trace: traceMode, scope };
  }

  root.FuinVerify = { verify, servedAs, sealedNumberOk, jcs, auditSize, scoreText, scoreResponse, sha256, hex, b64 };
})(typeof window !== 'undefined' ? window : globalThis);
