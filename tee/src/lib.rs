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
}

impl Outcome {
    /// The attested output: keys sort the same way OutLayer's worker hashes them; well under its 900-byte cap.
    pub fn to_json(&self, blob_sha256: &str) -> Value {
        serde_json::json!({"v": "fuin-tee-score-v1", "model": self.model, "n": self.n, "total": self.total,
            "benchmark_root": self.benchmark_root, "policy_hash": self.policy_hash, "run_root": self.run_root,
            "signer": self.signer, "blob_sha256": blob_sha256})
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

/// The plaintext a benchmark owner encrypts to the TEE (see src/fuin/tee.py `plaintext`).
pub fn round_from_json(v: &Value) -> Result<Round, String> {
    if v["v"] != "fuin-tee-round-v1" {
        return Err("unsupported plaintext version".into());
    }
    let b64 = base64::engine::general_purpose::STANDARD;
    let s = |x: &Value, k: &str| x[k].as_str().map(str::to_string).ok_or(format!("missing {k}"));
    let items = v["items"].as_array().ok_or("items")?.iter().map(|x| {
        let salt: [u8; 32] = hex::decode(s(x, "salt")?).map_err(|_| "salt not hex")?.try_into().map_err(|_| "salt must be 32 bytes")?;
        Ok(Item { salt, item_jcs: s(x, "item_jcs")? })
    }).collect::<Result<Vec<_>, String>>()?;
    let rows = v["rows"].as_array().ok_or("rows")?.iter().map(|x| {
        Ok(Row { request: b64.decode(s(x, "request_b64")?).map_err(|_| "request_b64")?,
                 response: b64.decode(s(x, "response_b64")?).map_err(|_| "response_b64")?, sig: x["signature"].clone() })
    }).collect::<Result<Vec<_>, String>>()?;
    Ok(Round { model: s(v, "model")?, policy_jcs: s(v, "policy_jcs")?, items, rows })
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

fn abs_diff_le(a: &(BigInt, i64), b: &(BigInt, i64), tol: &(BigInt, i64)) -> Option<bool> {
    let e = a.1.min(b.1).min(tol.1);
    let scale = |x: &(BigInt, i64)| -> Option<BigInt> {
        let k = u32::try_from(x.1 - e).ok().filter(|k| *k <= 2_000_000)?;
        Some(&x.0 * BigInt::from(10u8).pow(k))
    };
    let d = scale(a)? - scale(b)?;
    let d = if d < BigInt::from(0) { -d } else { d };
    Some(d <= scale(tol)?)
}

fn answer_decimal(s: &str) -> Result<(BigInt, i64), String> {
    let t: String = py_strip(s).chars().map(|c| py_digit(c).map(|d| (b'0' + d) as char).unwrap_or(c)).collect();
    let chars: Vec<char> = t.chars().collect();
    let t: String = chars.iter().enumerate()
        .filter(|(j, c)| !(**c == '_' && *j > 0 && *j + 1 < chars.len() && chars[j - 1].is_ascii_digit() && chars[j + 1].is_ascii_digit()))
        .map(|(_, c)| *c).collect();
    parse_decimal(&t, false).ok_or_else(|| format!("unsupported decimal {s:?}"))
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
    let Ok(v) = serde_json::from_slice::<Value>(response) else { return Ok(0) };
    match v.get("choices").and_then(|c| c.get(0)).and_then(|c| c.get("message")).and_then(|m| m.get("content")).and_then(Value::as_str) {
        Some(content) => score_text(item, content, v2),
        None => Ok(0),
    }
}

/// Rebuild and score one run: every leaf from the sealed bytes, every request against the sealed template, every
/// signature recovered to one signer, every answer scored. The verifier compares the result with the registry.
pub fn score_round(r: &Round) -> Result<Outcome, String> {
    let policy: Value = serde_json::from_str(&r.policy_jcs).map_err(|e| format!("policy: {e}"))?;
    let n = r.items.len();
    if n == 0 || r.rows.len() != n {
        return Err("rows must match items one to one".into());
    }
    let s = |p: &str| policy.pointer(p).and_then(Value::as_str);
    if s("/protocol") != Some("fuin-v1") {
        return Err("unsupported protocol".into());
    }
    if s("/request/template") != Some("fuin-request-v1") || s("/request/privacy_profile") != Some("nonce-in-user-field-v1") {
        return Err("unsupported request template".into());
    }
    let scorer = (s("/scorer/name").unwrap_or(""), s("/scorer/sha256").unwrap_or(""));
    if !pytables::SCORERS.iter().any(|(a, b)| (*a, *b) == scorer) {
        return Err("unsupported scorer".into());
    }
    let v2 = scorer.0 == "fuin-scorer-v2";
    if policy.pointer("/score/values") != Some(&serde_json::json!([0, 1])) || s("/score/aggregate") != Some("sum")
        || policy.pointer("/score/denominator").and_then(Value::as_u64) != Some(n as u64) {
        return Err("unsupported score policy".into());
    }
    let settings = policy["models"].get(&r.model).and_then(Value::as_object).ok_or("model not in the sealed policy")?;
    let (mut bleaves, mut rleaves, mut total, mut signer) = (Vec::with_capacity(n), Vec::with_capacity(n), 0u64, None::<String>);
    for (i, (it, row)) in r.items.iter().zip(&r.rows).enumerate() {
        let at = |e: String| format!("item {i}: {e}");
        let idx = (i as u64).to_be_bytes();
        let bleaf = sha256(&[&[0u8], &idx, &it.salt, it.item_jcs.as_bytes()]);
        let item: Value = serde_json::from_str(&it.item_jcs).map_err(|e| at(e.to_string()))?;
        let q = |k: &str| item[k].as_str().ok_or_else(|| at(format!("item {k}")));
        let expected = build_request(&r.model, q("question")?, q("request_nonce")?, settings).map_err(at)?;
        if expected.as_bytes() != row.request.as_slice() {
            return Err(at("request_policy_mismatch".into()));
        }
        let (req_sha, resp_sha) = (sha256(&[&row.request]), sha256(&[&row.response]));
        let sig = &row.sig;
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
        if signer.get_or_insert_with(|| who.clone()) != &who {
            return Err(at("more than one signer".into()));
        }
        let score = score_response(&item, &row.response, v2).map_err(at)?;
        total += u64::from(score);
        rleaves.push(sha256(&[&[2u8], &idx, &bleaf, &req_sha, &resp_sha, &[score]]));
        bleaves.push(bleaf);
    }
    Ok(Outcome {
        model: r.model.clone(),
        n: n as u64,
        total,
        benchmark_root: hex::encode(merkle_root(bleaves)?),
        policy_hash: hex::encode(sha256(&[r.policy_jcs.as_bytes()])),
        run_root: hex::encode(merkle_root(rleaves)?),
        signer: signer.unwrap_or_default(),
    })
}
