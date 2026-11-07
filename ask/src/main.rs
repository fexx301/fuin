//! Fūin asker, an OutLayer WASI P2 component run as a project whose owner account holds no keys.
//!
//! keygen:    an X25519 keypair made inside the enclave; the secret is sealed under the project's key, so only this
//!            project's code, called by the same account, can open it.
//! ask:       one sealed item, asked once. The record's name is derived from the sealed round (benchmark root, model,
//!            index), never taken from the caller. The record goes `pending` before the model call; the enclave builds
//!            the sealed request (fuin_tee::item_request), calls NEAR AI with the owner's key (an OutLayer secret),
//!            checks and scores the signed answer (fuin_tee::item_result) and writes the record `final`. A final record
//!            is re-emitted, never re-asked. A pending one (no answer ever left the enclave) may be retried; every
//!            attempt is counted.
//! aggregate: reads every final record of one run and returns its roots, total and signer exactly as the TEE scorer
//!            does (fuin_tee::outcome_from), plus the number of retried asks.
//! Outputs stay under 1,024 bytes (OutLayer's receipt limit) and never echo a sealed value.

#[cfg(target_arch = "wasm32")]
#[used]
#[link_section = "outlayer.manifest"]
static OUTLAYER_MANIFEST: [u8; include_bytes!("../manifest.json").len()] = *include_bytes!("../manifest.json");

#[cfg(target_arch = "wasm32")]
mod asker {
    use chacha20poly1305::{aead::Aead, ChaCha20Poly1305, KeyInit, Nonce};
    use outlayer::storage::sealed;
    use serde_json::{json, Value};
    use sha2::{Digest, Sha256};
    use std::time::Duration;
    use x25519_dalek::{PublicKey, StaticSecret};

    const KEY_PATH: &str = "fuin-ask-key";
    const RECORDS: &str = "fuin-ask";
    const AAD: &[u8] = b"fuin-ask-x25519-v1";
    const HOST: &str = "cloud-api.near.ai";

    fn s(input: &Value, k: &str) -> Result<String, String> {
        input[k].as_str().map(str::to_string).ok_or(format!("missing {k}"))
    }

    /// The owner's round, as the TEE scorer receives it (tee/src/main.rs): fetched, hash-checked, opened with the in-TEE key.
    fn open_round(input: &Value) -> Result<(fuin_tee::Round, String), String> {
        let blob = wasi_http_client::Client::new().get(&s(input, "url")?).connect_timeout(Duration::from_secs(20)).send()
            .and_then(|r| r.body()).map_err(|e| format!("fetch: {e}"))?;
        let blob_sha256 = hex::encode(Sha256::digest(&blob));
        if blob_sha256 != s(input, "blob_sha256")? {
            return Err("blob hash differs from the request".into());
        }
        let blob = match input["encoding"].as_str() {
            None | Some("raw") => blob,
            Some("base64") => {
                use base64::Engine;
                let text: String = String::from_utf8_lossy(&blob).chars().filter(|c| !c.is_whitespace()).collect();
                base64::engine::general_purpose::STANDARD.decode(text).map_err(|_| "blob is not base64")?
            }
            Some(_) => return Err("encoding must be raw or base64".into()),
        };
        let secret = outlayer::encryption_keys::decrypt(KEY_PATH, None, &hex::decode(s(input, "sealed")?).map_err(|e| e.to_string())?, AAD)
            .map_err(|e| format!("unseal: {e}"))?;
        let secret: [u8; 32] = secret.try_into().map_err(|_| "secret length")?;
        let eph: [u8; 32] = hex::decode(s(input, "eph_pub")?).map_err(|e| e.to_string())?.try_into().map_err(|_| "eph_pub length")?;
        let shared = StaticSecret::from(secret).diffie_hellman(&PublicKey::from(eph));
        let mut key = [0u8; 32];
        hkdf::Hkdf::<Sha256>::new(None, shared.as_bytes()).expand(b"fuin-ask-round-v1", &mut key).map_err(|e| e.to_string())?;
        let nonce = hex::decode(s(input, "nonce")?).map_err(|e| e.to_string())?;
        if nonce.len() != 12 {
            return Err("nonce length".into());
        }
        let plain = ChaCha20Poly1305::new(&key.into()).decrypt(Nonce::from_slice(&nonce), blob.as_ref()).map_err(|_| "decrypt failed")?;
        let round: Value = serde_json::from_slice(&plain).map_err(|e| format!("plaintext: {e}"))?;
        Ok((fuin_tee::round_from_json(&round)?, blob_sha256))
    }

    fn benchmark_root(r: &fuin_tee::Round) -> Result<[u8; 32], String> {
        fuin_tee::merkle_root(r.items.iter().enumerate().map(|(i, it)| fuin_tee::benchmark_leaf(i, it)).collect())
    }

    /// The record of item i of this model's run in this round: named by the sealed round alone.
    fn record_name(root: &[u8; 32], model: &str, i: usize) -> String {
        let mut h = Sha256::new();
        h.update(b"fuin-ask-v1");
        h.update(root);
        h.update((model.len() as u64).to_be_bytes());
        h.update(model.as_bytes());
        h.update((i as u64).to_be_bytes());
        hex::encode(h.finalize())
    }

    fn item_output(model: &str, i: usize, root: &[u8; 32], rec: &Value) -> Value {
        json!({"v": "fuin-ask-item-v1", "model": model, "i": i, "benchmark_root": hex::encode(root), "attempts": rec["a"],
               "req_sha256": rec["req"], "resp_sha256": rec["resp"], "score": rec["score"], "unreadable": rec["unreadable"],
               "signature": rec["sig"], "signing_address": rec["addr"]})
    }

    pub fn run(input: &Value) -> Result<Value, String> {
        match input["mode"].as_str() {
            Some("keygen") => {
                let mut b = [0u8; 32];
                getrandom::fill(&mut b).map_err(|e| e.to_string())?;
                let public = PublicKey::from(&StaticSecret::from(b));
                let sealed_secret = outlayer::encryption_keys::encrypt(KEY_PATH, None, &b, AAD).map_err(|e| e.to_string())?;
                Ok(json!({"v": "fuin-ask-key-v1", "pub": hex::encode(public.as_bytes()), "sealed": hex::encode(sealed_secret)}))
            }
            Some("ask") => ask(input),
            Some("aggregate") => aggregate(input),
            _ => Err("mode must be keygen, ask or aggregate".into()),
        }
    }

    fn ask(input: &Value) -> Result<Value, String> {
        let (r, _) = open_round(input)?;
        let c = fuin_tee::sealed(&r)?;
        let i = input["i"].as_u64().ok_or("missing i")? as usize;
        if i >= r.items.len() {
            return Err("no such item".into());
        }
        let expected_signer = s(input, "signer")?.to_lowercase();
        let root = benchmark_root(&r)?;
        let name = record_name(&root, &r.model, i);
        // the record goes pending before any model call; a final one is re-emitted, never re-asked
        let current = match sealed::get(RECORDS, None, &name).map_err(|e| e.to_string())? {
            Some(rec) => rec,
            None => {
                sealed::set_if_absent(RECORDS, None, &name, br#"{"s":"pending","a":0}"#).map_err(|e| e.to_string())?;
                sealed::get(RECORDS, None, &name).map_err(|e| e.to_string())?.ok_or("record vanished")?
            }
        };
        let rec: Value = serde_json::from_slice(current.plaintext()).map_err(|_| "record unreadable")?;
        if rec["s"] == "final" {
            return Ok(item_output(&r.model, i, &root, &rec));
        }
        let attempts = rec["a"].as_u64().unwrap_or(0) + 1;
        let (claimed, _) = sealed::set_if_equals(RECORDS, None, &name, &current, json!({"s": "pending", "a": attempts}).to_string().as_bytes())
            .map_err(|e| e.to_string())?;
        if !claimed {
            return Err("another ask of this item is in progress".into());
        }
        let current = sealed::get(RECORDS, None, &name).map_err(|e| e.to_string())?.ok_or("record vanished")?;

        let (request, e2ee_headers) = fuin_tee::item_request(&r, &c, i)?;
        let key = outlayer::env::var("NEARAI_API_KEY").ok_or("no NEARAI_API_KEY secret")?;
        let auth = format!("Bearer {key}");
        let mut headers: Vec<(&str, &str)> = vec![("Authorization", &auth), ("Content-Type", "application/json"),
                                                  ("x-no-aliasing", "true"), ("Accept-Encoding", "identity")];
        headers.extend(e2ee_headers.iter().map(|(k, v)| (*k, v.as_str())));
        let (status, response) = post("/v1/chat/completions", &headers, request.as_bytes())?;
        if status != 200 {
            return Err(format!("item {i}: completion HTTP {status}"));
        }
        let chat_id = serde_json::from_slice::<Value>(&response).ok().and_then(|v| v["id"].as_str().map(str::to_string))
            .ok_or(format!("item {i}: no chat id"))?;
        let sig = signature(&chat_id, &r.model, &auth).ok_or(format!("item {i}: signature unavailable"))?;
        let x = fuin_tee::item_result(&r, &c, i, request.as_bytes(), &response, &sig)?;
        if x.signer != expected_signer {  // another instance answered: stays pending, counted, retried after a fresh preflight
            return Err(format!("item {i}: answer signed by another key"));
        }
        let fin = json!({"s": "final", "a": attempts, "req": hex::encode(x.req_sha), "resp": hex::encode(x.resp_sha), "score": x.score,
                         "unreadable": x.unreadable, "sig": sig["signature"], "addr": x.signer});
        let (done, _) = sealed::set_if_equals(RECORDS, None, &name, &current, fin.to_string().as_bytes()).map_err(|e| e.to_string())?;
        if !done {
            return Err("record changed during the ask".into());
        }
        Ok(item_output(&r.model, i, &root, &fin))
    }

    fn aggregate(input: &Value) -> Result<Value, String> {
        let (r, blob_sha256) = open_round(input)?;
        let c = fuin_tee::sealed(&r)?;
        let root = benchmark_root(&r)?;
        let (mut results, mut retried) = (Vec::with_capacity(r.items.len()), 0u64);
        for i in 0..r.items.len() {
            let rec = sealed::get(RECORDS, None, &record_name(&root, &r.model, i)).map_err(|e| e.to_string())?
                .ok_or(format!("item {i} was never asked"))?;
            let rec: Value = serde_json::from_slice(rec.plaintext()).map_err(|_| "record unreadable")?;
            if rec["s"] != "final" {
                return Err(format!("item {i} has no final answer"));
            }
            let h = |k: &str| -> Result<[u8; 32], String> {
                hex::decode(rec[k].as_str().unwrap_or("")).ok().and_then(|b| b.try_into().ok()).ok_or(format!("item {i}: record {k}"))
            };
            retried += rec["a"].as_u64().unwrap_or(1).saturating_sub(1);
            results.push(fuin_tee::ItemResult { req_sha: h("req")?, resp_sha: h("resp")?, score: rec["score"].as_u64().unwrap_or(0) as u8,
                unreadable: rec["unreadable"].as_bool().unwrap_or(false), signer: rec["addr"].as_str().unwrap_or("").to_string() });
        }
        let mut out = fuin_tee::outcome_from(&r, &c, &results)?.to_json(&blob_sha256);
        out["v"] = "fuin-tee-asked-v1".into();
        out["retried"] = retried.into();
        Ok(out)
    }

    fn signature(chat_id: &str, model: &str, auth: &str) -> Option<Value> {
        for t in 0..6u64 {
            let url = format!("https://{HOST}/v1/signature/{chat_id}?model={}&signing_algo=ecdsa", model.replace('/', "%2F"));
            if let Ok(r) = wasi_http_client::Client::new().get(&url).header("Authorization", auth).connect_timeout(Duration::from_secs(20)).send() {
                if r.status() == 200 {
                    if let Some(v) = r.body().ok().and_then(|b| serde_json::from_slice::<Value>(&b).ok()) {
                        if v.get("error_code").is_none() {
                            return Some(v);
                        }
                    }
                }
            }
            std::thread::sleep(Duration::from_secs(1 + t));
        }
        None
    }

    /// One HTTPS POST to NEAR AI through wasi:http (wasi-http-client can't pass the request body's length limits and
    /// options we need); how long it may wait is the manifest's `timeout_secs`, part of this attested build.
    fn post(path: &str, headers: &[(&str, &str)], body: &[u8]) -> Result<(u16, Vec<u8>), String> {
        use wasi::http::types::{Fields, Method, OutgoingBody, OutgoingRequest, RequestOptions, Scheme};
        use wasi::io::streams::StreamError;
        let h = Fields::new();
        for (k, v) in headers {
            h.append(&k.to_string(), &v.as_bytes().to_vec()).map_err(|_| format!("header {k}"))?;
        }
        let req = OutgoingRequest::new(h);
        req.set_method(&Method::Post).map_err(|_| "method")?;
        req.set_scheme(Some(&Scheme::Https)).map_err(|_| "scheme")?;
        req.set_authority(Some(HOST)).map_err(|_| "authority")?;
        req.set_path_with_query(Some(path)).map_err(|_| "path")?;
        let ob = req.body().map_err(|_| "body")?;
        {
            let w = ob.write().map_err(|_| "body write")?;
            for chunk in body.chunks(4096) {  // blocking_write_and_flush takes at most 4096 bytes per call
                w.blocking_write_and_flush(chunk).map_err(|_| "write")?;
            }
        }
        OutgoingBody::finish(ob, None).map_err(|_| "finish")?;
        let opts = RequestOptions::new();
        opts.set_connect_timeout(Some(20_000_000_000)).map_err(|_| "connect timeout")?;
        let fut = wasi::http::outgoing_handler::handle(req, Some(opts)).map_err(|e| format!("completion: {e:?}"))?;
        fut.subscribe().block();
        let resp = fut.get().ok_or("no response")?.map_err(|_| "response taken")?.map_err(|e| format!("completion: {e:?}"))?;
        let status = resp.status();
        let ib = resp.consume().map_err(|_| "consume")?;
        let mut out = Vec::new();
        {
            let st = ib.stream().map_err(|_| "stream")?;
            loop {
                match st.blocking_read(1 << 20) {
                    Ok(c) => out.extend(c),
                    Err(StreamError::Closed) => break,
                    Err(_) => return Err("read".into()),
                }
            }
        }
        drop(ib);
        Ok((status, out))
    }
}

fn main() {
    #[cfg(target_arch = "wasm32")]
    {
        use std::io::{Read, Write};
        let mut raw = String::new();
        std::io::stdin().read_to_string(&mut raw).ok();
        let input: serde_json::Value = serde_json::from_str(&raw).unwrap_or(serde_json::Value::Null);
        let out = asker::run(&input).unwrap_or_else(|e| serde_json::json!({"error": e.chars().take(300).collect::<String>()}));
        let mut s = out.to_string();
        if s.len() >= 1024 {  // OutLayer carries only outputs under 1,024 bytes in the receipt; never cut one
            s = serde_json::json!({"error": "output too large"}).to_string();
        }
        std::io::stdout().write_all(s.as_bytes()).ok();
        std::io::stdout().flush().ok();
    }
    #[cfg(not(target_arch = "wasm32"))]
    {
        eprintln!("fuin-ask runs only as an OutLayer component (wasm32-wasip2); its logic is fuin_tee's, tested natively there");
        std::process::exit(2);
    }
}
