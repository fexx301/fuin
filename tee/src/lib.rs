//! Fūin TEE scorer core: rebuild one run of a sealed round from its sealed bytes and score every answer, exactly as
//! the Python reference does (src/fuin/core.py, inference.py, scorer.py, scorer_v1.py). Anything it can't reproduce
//! byte for byte is refused, never guessed. Built natively for the parity tests and to wasm32-wasip2 for OutLayer.
mod pytables;

use base64::Engine;
use k256::ecdsa::{RecoveryId, Signature, VerifyingKey};
use num_bigint::BigInt;
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use sha3::Keccak256;

pub struct Item {
    pub salt: [u8; 32],
    pub item_jcs: String, // the item's RFC 8785 bytes exactly as sealed; hashing them, not re-encoding, keeps the leaf exact
}

pub struct Row {
    pub request: Vec<u8>,
    pub response: Vec<u8>,
    pub sig: Value,
}

pub struct Round {
    pub model: String,
    pub policy_jcs: String,
    pub seal_block_hash: Option<String>, // base58, for request templates v2 and v3 (nonces bound to the seal block)
    pub model_pub: Option<[u8; 64]>,     // template v3: the model's secp256k1 key each question was encrypted to
    pub items: Vec<Item>,
    pub rows: Vec<Row>,
}

#[derive(Debug, PartialEq)]
pub struct Outcome {
    pub model: String,
    pub n: u64,
    pub total: u64,
    pub benchmark_root: String,
    pub policy_hash: String,
    pub run_root: String,
    pub signer: String,
    pub seal_block_hash: Option<String>,
    /// template v3: answers that came back non-empty but don't decrypt with their item's key (each scored 0). The key an
    /// answer is encrypted back to travels in an unsigned header, so this count is what makes such answers visible.
    pub unreadable: Option<u64>,
}

impl Outcome {
    /// The attested output: keys sort the same way OutLayer's worker hashes them; well under its 900-byte cap.
    pub fn to_json(&self, blob_sha256: &str) -> Value {
        let mut v = serde_json::json!({"v": "fuin-tee-score-v1", "model": self.model, "n": self.n, "total": self.total,
            "benchmark_root": self.benchmark_root, "policy_hash": self.policy_hash, "run_root": self.run_root,
            "signer": self.signer, "blob_sha256": blob_sha256});
        if let Some(h) = &self.seal_block_hash {
            v["seal_block_hash"] = h.clone().into(); // the verifier compares it with the chain's block at the seal height
        }
        if let Some(u) = self.unreadable {
            v["unreadable"] = u.into();
        }
        v
    }
}

fn sha256(parts: &[&[u8]]) -> [u8; 32] {
    let mut h = Sha256::new();
    for p in parts {
        h.update(p);
    }
    h.finalize().into()
}

/// core.merkle_root: parents are sha256(0x01 ‖ left ‖ right); an odd level repeats its last node.
pub fn merkle_root(mut level: Vec<[u8; 32]>) -> Result<[u8; 32], String> {
    if level.is_empty() {
        return Err("n must be >= 1".into());
    }
    while level.len() > 1 {
        if level.len() % 2 == 1 {
            level.push(*level.last().unwrap());
        }
        level = level.chunks(2).map(|p| sha256(&[&[1u8], &p[0], &p[1]])).collect();
    }
    Ok(level[0])
}

/// The sealed items of a plaintext (`fuin-tee-round-v1` or `fuin-tee-items-v1`): each salt and its exact sealed bytes.
pub fn items_from_json(v: &Value) -> Result<Vec<Item>, String> {
    let s = |x: &Value, k: &str| x[k].as_str().map(str::to_string).ok_or(format!("missing {k}"));
    v["items"].as_array().ok_or("items")?.iter().map(|x| {
        let salt: [u8; 32] = hex::decode(s(x, "salt")?).map_err(|_| "salt not hex")?.try_into().map_err(|_| "salt must be 32 bytes")?;
        Ok(Item { salt, item_jcs: s(x, "item_jcs")? })
    }).collect()
}

/// core.benchmark_leaf: sha256(0x00 ‖ index ‖ salt ‖ the item's sealed bytes).
pub fn benchmark_leaf(i: usize, it: &Item) -> [u8; 32] {
    sha256(&[&[0u8], &(i as u64).to_be_bytes(), &it.salt, it.item_jcs.as_bytes()])
}

/// The plaintext a benchmark owner encrypts to the TEE (see src/fuin/tee.py `plaintext`).
pub fn round_from_json(v: &Value) -> Result<Round, String> {
    if v["v"] != "fuin-tee-round-v1" {
        return Err("unsupported plaintext version".into());
    }
    let b64 = base64::engine::general_purpose::STANDARD;
    let s = |x: &Value, k: &str| x[k].as_str().map(str::to_string).ok_or(format!("missing {k}"));
    let items = items_from_json(v)?;
    let no_rows = vec![];  // an asker's plaintext carries no rows: the enclave makes them
    let rows = v["rows"].as_array().unwrap_or(&no_rows).iter().map(|x| {
        Ok(Row { request: b64.decode(s(x, "request_b64")?).map_err(|_| "request_b64")?,
                 response: b64.decode(s(x, "response_b64")?).map_err(|_| "response_b64")?, sig: x["signature"].clone() })
    }).collect::<Result<Vec<_>, String>>()?;
    let seal_block_hash = v["seal_block_hash"].as_str().map(str::to_string);
    let model_pub = match v["model_pub"].as_str() {
        None => None,
        Some(h) => Some(hex::decode(h).map_err(|_| "model_pub not hex")?.try_into().map_err(|_| "model_pub must be 64 bytes")?),
    };
    Ok(Round { model: s(v, "model")?, policy_jcs: s(v, "policy_jcs")?, seal_block_hash, model_pub, items, rows })
}

/// inference.build_request: json.dumps(ensure_ascii=False, separators=(",", ":")) of model, messages, stream, user, then
/// the sealed settings. The TEE only sees the canonical (sorted) policy, so it rebuilds with sorted settings and the
/// caller's signed bytes must equal that; a round built with another order is refused, not reinterpreted.
fn build_request(model: &str, question: &str, nonce: &str, settings: &Map<String, Value>) -> Result<String, String> {
    let j = |x: &str| serde_json::to_string(x).unwrap();
    let mut out = format!("{{\"model\":{},\"messages\":[{{\"role\":\"user\",\"content\":{}}}],\"stream\":false,\"user\":{}",
                          j(model), j(question), j(nonce));
    for (k, v) in settings {
        if !(v.is_i64() || v.is_u64() || v.is_boolean()) {
            return Err(format!("setting {k} must be an integer or boolean"));
        }
        out.push_str(&format!(",{}:{}", j(k), v));
    }
    out.push('}');
    Ok(out)
}

/// eth_account's recover_message: EIP-191 personal-sign over the text, keccak-256, secp256k1 recovery; high-s accepted.
fn recover_eip191(text: &str, sig_hex: &str) -> Result<String, String> {
    let sig = hex::decode(sig_hex.trim_start_matches("0x")).map_err(|_| "signature not hex")?;
    if sig.len() != 65 {
        return Err("signature length".into());
    }
    let v = sig[64];
    let recid = match v {
        27 | 28 => v - 27,
        0 | 1 => v,
        _ => return Err("signature v".into()),
    };
    let mut msg = format!("\x19Ethereum Signed Message:\n{}", text.len()).into_bytes();
    msg.extend_from_slice(text.as_bytes());
    let digest = Keccak256::digest(&msg);
    let mut signature = Signature::from_slice(&sig[..64]).map_err(|_| "signature encoding")?;
    let mut recid = RecoveryId::from_byte(recid).ok_or("recovery id")?;
    if let Some(low) = signature.normalize_s() {
        signature = low;
        recid = RecoveryId::new(!recid.is_y_odd(), recid.is_x_reduced());
    }
    let key = VerifyingKey::recover_from_prehash(&digest, &signature, recid).map_err(|_| "signature does not recover")?;
    let point = key.to_encoded_point(false);
    Ok(format!("0x{}", hex::encode(&Keccak256::digest(&point.as_bytes()[1..])[12..])))
}

// ---- request template v3 (src/fuin/e2ee.py): NEAR AI Cloud's E2EE on the model's secp256k1 key, with every random value
// derived from the item's salt, so the question re-encrypts byte for byte and the answer decrypts ----
mod e2ee {
    use aes_gcm::{aead::Aead, Aes256Gcm, KeyInit, Nonce};
    use k256::{elliptic_curve::sec1::ToEncodedPoint, PublicKey, SecretKey};
    use num_bigint::BigUint;

    const ORDER: &str = "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141";
    const MIN_BLOB: usize = 65 + 12 + 16;

    fn seed(salt: &[u8; 32], model: &str) -> [u8; 32] { super::sha256(&[b"fuin-e2ee-v1", salt, model.as_bytes()]) }

    fn secret(tag: &[u8], salt: &[u8; 32], model: &str) -> SecretKey {
        let n = BigUint::parse_bytes(ORDER.as_bytes(), 16).unwrap();
        let x = BigUint::from_bytes_be(&super::sha256(&[tag, &seed(salt, model)])) % (&n - 1u32) + 1u32;  // in [1, N-1]
        let mut b = [0u8; 32];
        let xb = x.to_bytes_be();
        b[32 - xb.len()..].copy_from_slice(&xb);
        SecretKey::from_slice(&b).unwrap()
    }

    fn key(secret: &SecretKey, public: &PublicKey) -> [u8; 32] {  // ECDH x-coordinate, HKDF-SHA256 (no salt, "ecdsa_encryption")
        let shared = k256::ecdh::diffie_hellman(secret.to_nonzero_scalar(), public.as_affine());
        let mut k = [0u8; 32];
        hkdf::Hkdf::<sha2::Sha256>::new(None, shared.raw_secret_bytes()).expand(b"ecdsa_encryption", &mut k).unwrap();
        k
    }

    pub fn pub_from(raw64: &[u8; 64]) -> Option<PublicKey> {
        let mut sec1 = [4u8; 65];
        sec1[1..].copy_from_slice(raw64);
        PublicKey::from_sec1_bytes(&sec1).ok()
    }

    /// e2ee.encrypt_question: hex(ephemeral public key ‖ nonce ‖ AES-256-GCM ciphertext and tag)
    pub fn encrypt_question(question: &str, salt: &[u8; 32], model: &str, model_pub: &PublicKey) -> String {
        let eph = secret(b"fuin-e2ee-eph-v1", salt, model);
        let nonce = &super::sha256(&[b"fuin-e2ee-nonce-v1", &seed(salt, model)])[..12];
        let ct = Aes256Gcm::new(&key(&eph, model_pub).into()).encrypt(Nonce::from_slice(nonce), question.as_bytes()).unwrap();
        let mut out = eph.public_key().to_encoded_point(false).as_bytes().to_vec();
        out.extend_from_slice(nonce);
        out.extend_from_slice(&ct);
        hex::encode(out)
    }

    /// e2ee.decrypt: a field the model encrypted to this item's client key; None if it isn't such a ciphertext
    pub fn decrypt(blob_hex: &str, salt: &[u8; 32], model: &str) -> Option<String> {
        if blob_hex.len() % 2 != 0 || !blob_hex.bytes().all(|c| c.is_ascii_hexdigit()) {
            return None;
        }
        let b = hex::decode(blob_hex).ok()?;
        if b.len() < MIN_BLOB || b[0] != 4 {
            return None;
        }
        let model_eph = PublicKey::from_sec1_bytes(&b[..65]).ok()?;
        let k = key(&secret(b"fuin-e2ee-client-v1", salt, model), &model_eph);
        let plain = Aes256Gcm::new(&k.into()).decrypt(Nonce::from_slice(&b[65..77]), &b[77..]).ok()?;
        String::from_utf8(plain).ok()
    }

    /// e2ee.client_pub: the item's client key, raw 64 bytes as hex (the X-Client-Pub-Key header)
    pub fn client_pub_hex(salt: &[u8; 32], model: &str) -> String {
        hex::encode(&secret(b"fuin-e2ee-client-v1", salt, model).public_key().to_encoded_point(false).as_bytes()[1..])
    }

    pub fn address(public: &PublicKey) -> String {
        use sha3::Digest;
        let point = public.to_encoded_point(false);
        format!("0x{}", hex::encode(&sha3::Keccak256::digest(&point.as_bytes()[1..])[12..]))
    }
}

// ---- scorer: Python's str.strip(), \d with Decimal, and str.casefold(), from generated tables ----

fn is_py_space(c: char) -> bool {
    pytables::PY_WS.binary_search(&(c as u32)).is_ok()
}

fn py_strip(s: &str) -> &str {
    s.trim_matches(is_py_space)
}

fn py_digit(c: char) -> Option<u8> {
    if c.is_ascii_digit() {
        return Some(c as u8 - b'0');
    }
    let cp = c as u32;
    let i = pytables::PY_DIGIT_ZEROS.partition_point(|&z| z <= cp);
    (i > 0 && cp - pytables::PY_DIGIT_ZEROS[i - 1] < 10).then(|| (cp - pytables::PY_DIGIT_ZEROS[i - 1]) as u8)
}

fn py_casefold(s: &str) -> String {
    s.chars().map(|c| match pytables::PY_CASEFOLD.binary_search_by_key(&(c as u32), |(cp, _)| *cp) {
        Ok(i) => pytables::PY_CASEFOLD[i].1.to_string(),
        Err(_) => c.to_string(),
    }).collect()
}

fn extract(content: &str, v2: bool) -> String {
    let mut s = py_strip(content);
    if let Some(t) = s.strip_suffix('.') {
        s = t;
    }
    let set: &[char] = if v2 { &['`', '"', '\'', '*', '_'] } else { &['`', '"', '\''] };
    py_strip(py_strip(s).trim_matches(set)).to_string()
}

/// A finite decimal as (digits, exponent); value = digits × 10^exponent. Python's Decimal subtracts at 28 significant
/// digits; this is exact, so the two can only differ when the tolerance itself has 28+ significant digits.
fn parse_decimal(s: &str, strict: bool) -> Option<(BigInt, i64)> {
    let (neg, body) = match s.as_bytes().first() {
        Some(b'-') => (true, &s[1..]),
        Some(b'+') => (false, &s[1..]),
        _ => (false, s),
    };
    let (mant, exp) = match body.find(['e', 'E']) {
        Some(i) => (&body[..i], Some(&body[i + 1..])),
        None => (body, None),
    };
    let (int, frac) = match mant.find('.') {
        Some(i) => (&mant[..i], &mant[i + 1..]),
        None => (mant, ""),
    };
    let digits = |x: &str| !x.is_empty() && x.bytes().all(|b| b.is_ascii_digit());
    // NUMBER.fullmatch: digits, optional .digits; Decimal (answers, tolerance) also allows "6." and ".5"
    let ok = if strict { digits(int) && (mant.find('.').is_none() || digits(frac)) }
             else { (digits(int) || int.is_empty()) && (frac.is_empty() || digits(frac)) && (digits(int) || digits(frac)) };
    if !ok {
        return None;
    }
    let e: i64 = match exp {
        Some(x) => {
            let (en, ed) = match x.as_bytes().first() { Some(b'-') => (true, &x[1..]), Some(b'+') => (false, &x[1..]), _ => (false, x) };
            if !digits(ed) || ed.len() > 9 { return None; }
            let v: i64 = ed.parse().ok()?;
            if en { -v } else { v }
        }
        None => 0,
    };
    let mut m: BigInt = format!("{int}{frac}").trim_start_matches('0').parse().unwrap_or_default();
    if neg {
        m = -m;
    }
    Some((m, e - frac.len() as i64))
}

/// abs(Decimal(x) - Decimal(answer)) <= Decimal(tolerance) as Python computes it: the exact difference is rounded to the
/// default context's 28 significant digits, half-even, before the exact comparison.
fn abs_diff_le(a: &(BigInt, i64), b: &(BigInt, i64), tol: &(BigInt, i64)) -> Option<bool> {
    let scale = |x: &(BigInt, i64), e: i64| -> Option<BigInt> {
        let k = u32::try_from(x.1 - e).ok().filter(|k| *k <= 2_000_000)?;
        Some(&x.0 * BigInt::from(10u8).pow(k))
    };
    let e = a.1.min(b.1);
    let d = scale(a, e)? - scale(b, e)?;
    let (mut m, mut de) = (if d < BigInt::from(0) { -d } else { d }, e);
    let digits = m.to_string().len() as u32;
    if m != BigInt::from(0) && digits > 28 {
        let k = digits - 28;
        let p = BigInt::from(10u8).pow(k);
        let (mut q, r) = (&m / &p, &m % &p);
        let half = BigInt::from(5u8) * BigInt::from(10u8).pow(k - 1);
        if r > half || (r == half && &q % 2u8 == BigInt::from(1)) {
            q += 1;
        }
        m = q;
        de += i64::from(k);  // a carry to 10^28 changes no value, so it needs no renormalising for the comparison
    }
    let e2 = de.min(tol.1);
    Some(scale(&(m, de), e2)? <= scale(tol, e2)?)
}

fn answer_decimal(s: &str) -> Result<(BigInt, i64), String> {
    let t: String = py_strip(s).chars().map(|c| py_digit(c).map(|d| (b'0' + d) as char).unwrap_or(c)).collect();
    let chars: Vec<char> = t.chars().collect();
    let t: String = chars.iter().enumerate()
        .filter(|(j, c)| !(**c == '_' && *j > 0 && *j + 1 < chars.len() && chars[j - 1].is_ascii_digit() && chars[j + 1].is_ascii_digit()))
        .map(|(_, c)| *c).collect();
    // never echo the value: an error leaves the enclave as public on-chain output, and this is a sealed answer
    parse_decimal(&t, false).ok_or_else(|| "unsupported decimal in a sealed answer or tolerance".to_string())
}

/// scorer.score_text (v2) / scorer_v1.score_text: 1 or 0.
pub fn score_text(item: &Value, content: &str, v2: bool) -> Result<u8, String> {
    let s = extract(content, v2);
    match item["answer_type"].as_str() {
        Some("numeric") => {
            let ascii: Vec<char> = s.chars().map(|c| py_digit(c).map(|d| (b'0' + d) as char).unwrap_or(c)).collect();
            let t: String = ascii.iter().enumerate()
                .filter(|(j, c)| !((**c == ',' || **c == '_') && *j > 0 && *j + 1 < ascii.len()
                                   && ascii[j - 1].is_ascii_digit() && ascii[j + 1].is_ascii_digit()))
                .map(|(_, c)| *c).collect();
            let Some(x) = parse_decimal(&t, true) else { return Ok(0) };
            let ans = answer_decimal(item["answer"].as_str().ok_or("answer")?)?;
            let tol = answer_decimal(item["tolerance"].as_str().unwrap_or("0"))?;
            abs_diff_le(&x, &ans, &tol).map(u8::from).ok_or_else(|| "number out of range".into())
        }
        Some("exact") => {
            let got = py_casefold(&s);
            let mut accept = vec![item["answer"].as_str().ok_or("answer")?.to_string()];
            for a in item["accept"].as_array().into_iter().flatten() {
                accept.push(a.as_str().ok_or("accept")?.to_string());
            }
            Ok(u8::from(accept.iter().any(|a| py_casefold(a) == got)))
        }
        _ => Err("unsupported answer_type".into()),
    }
}

/// scorer.score_response: the first choice's message content; a malformed or empty response scores 0.
pub fn score_response(item: &Value, response: &[u8], v2: bool) -> Result<u8, String> {
    score_response_e2ee(item, response, v2, None).map(|(score, _)| score)
}

/// With `e2ee` (the item's salt and the model), the answer is decrypted first (e2ee.decrypted_response): a non-empty
/// content string that doesn't decrypt scores 0 whatever the item accepts (as "" it would match an accepted ""; scorer v6).
/// Returns (score, unreadable).
fn score_response_e2ee(item: &Value, response: &[u8], v2: bool, e2ee: Option<(&[u8; 32], &str)>) -> Result<(u8, bool), String> {
    let Ok(v) = serde_json::from_slice::<Value>(response) else { return Ok((0, false)) };
    match v.get("choices").and_then(|c| c.get(0)).and_then(|c| c.get("message")).and_then(|m| m.get("content")).and_then(Value::as_str) {
        Some(content) => match e2ee {
            Some((salt, model)) if !content.is_empty() => match e2ee::decrypt(content, salt, model) {
                Some(plain) => Ok((score_text(item, &plain, v2)?, false)),
                None => Ok((0, true)),
            },
            _ => Ok((score_text(item, content, v2)?, false)),
        },
        None => Ok((0, false)),
    }
}

/// What every item of one run needs from the sealed round: the model's settings, the request template, the seal-bound
/// nonce, the model's key (template v3) and the scorer. Validates the policy exactly as the scorer always has.
pub struct Sealed {
    settings: Map<String, Value>,
    seal_hash: Option<Vec<u8>>,
    model_pub: Option<k256::PublicKey>,
    v2_scorer: bool,
    v2_nonce: bool,
    v3: bool,
}

pub fn sealed(r: &Round) -> Result<Sealed, String> {
    let policy: Value = serde_json::from_str(&r.policy_jcs).map_err(|e| format!("policy: {e}"))?;
    let n = r.items.len();
    if n == 0 {
        return Err("n must be >= 1".into());
    }
    let s = |p: &str| policy.pointer(p).and_then(Value::as_str);
    if s("/protocol") != Some("fuin-v1") {
        return Err("unsupported protocol".into());
    }
    // v1: the sealed item nonce rides in `user`; v2: sha256("fuin-nonce-v2" ‖ item nonce ‖ seal block hash), so no request
    // (and no signed answer) can predate the seal
    // v3: v2's nonce, with the question and the answer end-to-end encrypted to the model's key (mod e2ee)
    let (v2_nonce, v3) = match (s("/request/template"), s("/request/privacy_profile")) {
        (Some("fuin-request-v1"), Some("nonce-in-user-field-v1")) => (false, false),
        (Some("fuin-request-v2"), Some("nonce-in-user-field-v1")) => (true, false),
        (Some("fuin-request-v3"), Some("nonce-in-user-field-v1")) => (true, true),
        _ => return Err("unsupported request template".into()),
    };
    let model_pub = match (v3, &r.model_pub) {
        (false, _) => None,
        (true, Some(k)) => Some(e2ee::pub_from(k).ok_or("model_pub is not a secp256k1 key")?),
        (true, None) => return Err("request template v3 needs the model's key".into()),
    };
    let seal_hash = match (v2_nonce, &r.seal_block_hash) {
        (false, _) => None,
        (true, Some(h)) => Some(bs58::decode(h).into_vec().map_err(|_| "seal_block_hash is not base58")?),
        (true, None) => return Err("a seal-bound request template needs the seal block hash".into()),
    };
    if seal_hash.as_ref().is_some_and(|h| h.len() != 32) {
        return Err("seal block hash must be 32 bytes".into());
    }
    let scorer = (s("/scorer/name").unwrap_or(""), s("/scorer/sha256").unwrap_or(""));
    if !pytables::SCORERS.iter().any(|(a, b)| (*a, *b) == scorer) {
        return Err("unsupported scorer".into());
    }
    if policy.pointer("/score/values") != Some(&serde_json::json!([0, 1])) || s("/score/aggregate") != Some("sum")
        || policy.pointer("/score/denominator").and_then(Value::as_u64) != Some(n as u64) {
        return Err("unsupported score policy".into());
    }
    let settings = policy["models"].get(&r.model).and_then(Value::as_object).ok_or("model not in the sealed policy")?.clone();
    Ok(Sealed { settings, seal_hash, model_pub, v2_scorer: scorer.0 == "fuin-scorer-v2", v2_nonce, v3 })
}

/// The exact request bytes the sealed template prescribes for item `i`, and the end-to-end-encryption headers (template v3).
pub fn item_request(r: &Round, c: &Sealed, i: usize) -> Result<(String, Vec<(&'static str, String)>), String> {
    let at = |e: String| format!("item {i}: {e}");
    let it = r.items.get(i).ok_or("no such item")?;
    let item: Value = serde_json::from_str(&it.item_jcs).map_err(|e| at(e.to_string()))?;
    let q = |k: &str| item[k].as_str().ok_or_else(|| at(format!("item {k}")));
    let nonce = match &c.seal_hash {
        None => q("request_nonce")?.to_string(),
        Some(h) => {
            let item_nonce = hex::decode(q("request_nonce")?).map_err(|_| at("request_nonce not hex".into()))?;
            hex::encode(sha256(&[b"fuin-nonce-v2", &item_nonce, h]))
        }
    };
    let (question, headers) = match &c.model_pub {
        None => (q("question")?.to_string(), vec![]),
        Some(k) => (e2ee::encrypt_question(q("question")?, &it.salt, &r.model, k),
                    vec![("X-Signing-Algo", "ecdsa".to_string()), ("X-Client-Pub-Key", e2ee::client_pub_hex(&it.salt, &r.model)),
                         ("X-Model-Pub-Key", hex::encode(&r.model_pub.unwrap()))]),
    };
    Ok((build_request(&r.model, &question, &nonce, &c.settings).map_err(at)?, headers))
}

/// One signed answer, checked and scored: the signature text binds this request and response, it recovers to the
/// signing address, and the answer is scored with the sealed scorer's exact rules.
pub struct ItemResult {
    pub req_sha: [u8; 32],
    pub resp_sha: [u8; 32],
    pub score: u8,
    pub unreadable: bool,
    pub signer: String,
}

pub fn item_result(r: &Round, c: &Sealed, i: usize, request: &[u8], response: &[u8], sig: &Value) -> Result<ItemResult, String> {
    let at = |e: String| format!("item {i}: {e}");
    let it = r.items.get(i).ok_or("no such item")?;
    let item: Value = serde_json::from_str(&it.item_jcs).map_err(|e| at(e.to_string()))?;
    let (req_sha, resp_sha) = (sha256(&[request]), sha256(&[response]));
    if sig["signature_kind"] != "provider_tee" || !(sig["signing_algo"].is_null() || sig["signing_algo"] == "ecdsa") {
        return Err(at("signature_text_mismatch".into()));
    }
    let text = format!("{}:{}:{}", r.model, hex::encode(req_sha), hex::encode(resp_sha));
    if sig["text"].as_str() != Some(text.as_str()) {
        return Err(at("signature_text_mismatch".into()));
    }
    let who = recover_eip191(&text, sig["signature"].as_str().unwrap_or("")).map_err(at)?;
    if Some(who.as_str()) != sig["signing_address"].as_str().map(str::to_lowercase).as_deref() {
        return Err(at("bad_signature".into()));
    }
    let (score, unreadable) = score_response_e2ee(&item, response, c.v2_scorer, c.v3.then_some((&it.salt, r.model.as_str()))).map_err(at)?;
    Ok(ItemResult { req_sha, resp_sha, score, unreadable, signer: who })
}

/// The run's roots and total from every item's result, in index order: one signer, and in template v3 the questions
/// went to that signer's key.
pub fn outcome_from(r: &Round, c: &Sealed, results: &[ItemResult]) -> Result<Outcome, String> {
    let n = r.items.len();
    if results.len() != n {
        return Err("rows must match items one to one".into());
    }
    let (mut bleaves, mut rleaves, mut total, mut signer, mut unreadable) = (Vec::with_capacity(n), Vec::with_capacity(n), 0u64, None::<String>, 0u64);
    for (i, (it, x)) in r.items.iter().zip(results).enumerate() {
        if signer.get_or_insert_with(|| x.signer.clone()) != &x.signer {
            return Err(format!("item {i}: more than one signer"));
        }
        let bleaf = benchmark_leaf(i, it);
        rleaves.push(sha256(&[&[2u8], &(i as u64).to_be_bytes(), &bleaf, &x.req_sha, &x.resp_sha, &[x.score]]));
        bleaves.push(bleaf);
        total += u64::from(x.score);
        unreadable += u64::from(x.unreadable);
    }
    if let (Some(k), Some(who)) = (&c.model_pub, &signer) {
        if &e2ee::address(k) != who {  // the questions went to the key that signed every answer, nobody else's
            return Err("model_pub is not the signer's key".into());
        }
    }
    Ok(Outcome {
        model: r.model.clone(),
        n: n as u64,
        total,
        benchmark_root: hex::encode(merkle_root(bleaves)?),
        policy_hash: hex::encode(sha256(&[r.policy_jcs.as_bytes()])),
        run_root: hex::encode(merkle_root(rleaves)?),
        signer: signer.unwrap_or_default(),
        seal_block_hash: if c.v2_nonce { r.seal_block_hash.clone() } else { None },
        unreadable: c.v3.then_some(unreadable),
    })
}

/// Rebuild and score one run: every leaf from the sealed bytes, every request against the sealed template, every
/// signature recovered to one signer, every answer scored. The verifier compares the result with the registry.
pub fn score_round(r: &Round) -> Result<Outcome, String> {
    let c = sealed(r)?;
    if r.rows.len() != r.items.len() {
        return Err("rows must match items one to one".into());
    }
    let mut results = Vec::with_capacity(r.rows.len());
    for (i, row) in r.rows.iter().enumerate() {
        let (expected, _) = item_request(r, &c, i)?;
        if expected.as_bytes() != row.request.as_slice() {
            return Err(format!("item {i}: request_policy_mismatch"));
        }
        let x = item_result(r, &c, i, &row.request, &row.response, &row.sig)?;
        if let Some(first) = results.first().map(|f: &ItemResult| f.signer.clone()) {
            if first != x.signer {
                return Err(format!("item {i}: more than one signer"));
            }
        }
        results.push(x);
    }
    outcome_from(r, &c, &results)
}

// ---------------- answer-key grounding (mode `ground`, src/fuin/tee.py `ground` is the reference) ----------------

/// The only repository a round may cite. Hard-coded: a fork's commits are also served under this path on GitHub, so the
/// verifier also pins which commits it accepts (policy/tee-v2.json `ground_commits`).
pub const GROUND_REPO: &str = "near/docs";

fn safe_path(p: &str) -> bool {
    !p.is_empty() && !p.starts_with('/') && !p.contains("..")
        && p.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '/' | '-'))
}

/// A numeric key counts only where it doesn't touch another digit: not after a digit or '.', not before a digit or '.'
/// followed by a digit (tee.py: (?<![0-9.])KEY(?![0-9]|\.[0-9])), so "2" isn't found inside "2024" or "1.25".
fn in_number_free(line: &str, key: &str) -> bool {
    let b = line.as_bytes();  // non-ASCII bytes are never digits or '.', so byte checks match Python's code-point checks
    line.match_indices(key).any(|(j, _)| {
        let end = j + key.len();
        let before = j > 0 && (b[j - 1].is_ascii_digit() || b[j - 1] == b'.');
        let after = end < b.len() && (b[end].is_ascii_digit() || (b[end] == b'.' && end + 1 < b.len() && b[end + 1].is_ascii_digit()));
        !before && !after
    })
}

/// The one commit a round cites and its distinct files in first-use order. Refuses what it can't fetch safely.
pub fn ground_sources(items: &[Item]) -> Result<(String, Vec<String>), String> {
    let (mut commit, mut paths) = (None::<String>, Vec::<String>::new());
    for (i, it) in items.iter().enumerate() {
        let item: Value = serde_json::from_str(&it.item_jcs).map_err(|e| format!("item {i}: {e}"))?;
        let (c, p) = (item["source"]["commit"].as_str().unwrap_or(""), item["source"]["path"].as_str().unwrap_or(""));
        if c.len() != 40 || !c.chars().all(|x| matches!(x, '0'..='9' | 'a'..='f')) {
            return Err(format!("item {i}: source commit must be 40 lowercase hex"));
        }
        if !safe_path(p) {
            return Err(format!("item {i}: unsupported source path"));
        }
        if commit.get_or_insert_with(|| c.to_string()) != c {
            return Err("sources must cite one commit".into());
        }
        if !paths.iter().any(|x| x == p) {
            paths.push(p.to_string());
        }
    }
    Ok((commit.ok_or("n must be >= 1")?, paths))
}

/// An item is grounded when its answer and every `accept` alternative appear in its cited line (split on \n, a trailing
/// \r dropped, ',' '`' '*' removed). Otherwise it is flagged, not refused: a derived answer (a unit conversion, a count)
/// may be right, but nobody checked it. `flags` sets bit i (most significant bit first) for each flagged item.
pub fn ground_round(items: &[Item], files: &std::collections::HashMap<String, String>) -> Result<Value, String> {
    let (commit, _) = ground_sources(items)?;
    let mut flags = vec![0u8; items.len().div_ceil(8)];
    let mut flagged = 0u64;
    for (i, it) in items.iter().enumerate() {
        let item: Value = serde_json::from_str(&it.item_jcs).map_err(|e| format!("item {i}: {e}"))?;
        let text = files.get(item["source"]["path"].as_str().unwrap_or("")).ok_or(format!("item {i}: source not fetched"))?;
        let lines: Vec<&str> = text.split('\n').map(|l| l.strip_suffix('\r').unwrap_or(l)).collect();
        let line = match item["source"]["line"].as_u64() {
            Some(k) if k >= 1 && (k as usize) <= lines.len() => lines[k as usize - 1].replace([',', '`', '*'], ""),
            _ => String::new(),
        };
        let answer = item["answer"].as_str().ok_or(format!("item {i}: answer must be a string"))?;
        let accept = match &item["accept"] {
            Value::Null => vec![],
            Value::Array(a) => a.iter().map(|x| x.as_str().ok_or(format!("item {i}: accept must be strings"))).collect::<Result<_, _>>()?,
            _ => return Err(format!("item {i}: accept must be a list")),
        };
        let numeric = item["answer_type"] == "numeric";
        if !std::iter::once(answer).chain(accept).all(|a| if numeric { in_number_free(&line, a) } else { line.contains(a) }) {
            flags[i / 8] |= 0x80 >> (i % 8);
            flagged += 1;
        }
    }
    let leaves = items.iter().enumerate().map(|(i, it)| benchmark_leaf(i, it)).collect();
    Ok(serde_json::json!({"v": "fuin-tee-ground-v1", "repo": GROUND_REPO, "commit": commit, "n": items.len() as u64,
        "benchmark_root": hex::encode(merkle_root(leaves)?), "flagged": flagged, "flags": hex::encode(flags)}))
}
