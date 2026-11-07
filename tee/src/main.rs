//! Fūin TEE scorer, an OutLayer WASI P2 component (and a native tool for the parity tests).
//!
//! keygen: an X25519 keypair made inside the enclave; the secret is sealed under an OutLayer encryption key bound to this
//!         build's sha256 (`bind: "wasm"`), so only this exact scorer, called by the same account, can open it.
//! score:  fetch the owner's encrypted round, check its hash, unseal the secret, decrypt, rebuild and score every answer
//!         (fuin_tee::score_round) and return only the roots, the total and the signer.
//! ground: decrypt the same way, fetch every cited near/docs file at the round's commit and report which answer keys
//!         don't appear in their cited line (fuin_tee::ground_round), with the sealed benchmark root they belong to.
//! Native: `fuin-tee plain ROUND.json` scores a plaintext round without a TEE, and `fuin-tee ground ITEMS.json DIR` grounds
//!         one against files already in DIR, for the parity tests.

#[cfg(target_arch = "wasm32")]
#[used]
#[link_section = "outlayer.manifest"]
static OUTLAYER_MANIFEST: [u8; include_bytes!("../manifest.json").len()] = *include_bytes!("../manifest.json");

#[cfg(target_arch = "wasm32")]
mod tee {
    use chacha20poly1305::{aead::Aead, ChaCha20Poly1305, KeyInit, Nonce};
    use serde_json::{json, Value};
    use sha2::{Digest, Sha256};
    use std::time::Duration;
    use x25519_dalek::{PublicKey, StaticSecret};

    const KEY_PATH: &str = "fuin-tee";
    const AAD: &[u8] = b"fuin-tee-x25519-v1";

    pub fn run(input: &Value) -> Result<Value, String> {
        let s = |k: &str| input[k].as_str().map(str::to_string).ok_or(format!("missing {k}"));
        match input["mode"].as_str() {
            Some("keygen") => {
                let mut b = [0u8; 32];
                getrandom::fill(&mut b).map_err(|e| e.to_string())?;
                let public = PublicKey::from(&StaticSecret::from(b));
                let sealed = outlayer::encryption_keys::encrypt(KEY_PATH, None, &b, AAD).map_err(|e| e.to_string())?;
                Ok(json!({"v": "fuin-tee-key-v1", "pub": hex::encode(public.as_bytes()), "sealed": hex::encode(sealed)}))
            }
            Some(mode @ ("score" | "ground")) => {
                let blob = wasi_http_client::Client::new().get(&s("url")?).connect_timeout(Duration::from_secs(20)).send()
                    .and_then(|r| r.body()).map_err(|e| format!("fetch: {e}"))?;
                let blob_sha256 = hex::encode(Sha256::digest(&blob));
                if blob_sha256 != s("blob_sha256")? {
                    return Err("blob hash differs from the request".into());
                }
                // a gist serves text, so the owner may host the ciphertext base64-encoded; the hash above covers the served bytes
                let blob = match input["encoding"].as_str() {
                    None | Some("raw") => blob,
                    Some("base64") => {
                        use base64::Engine;
                        let text: String = String::from_utf8_lossy(&blob).chars().filter(|c| !c.is_whitespace()).collect();
                        base64::engine::general_purpose::STANDARD.decode(text).map_err(|_| "blob is not base64")?
                    }
                    Some(_) => return Err("encoding must be raw or base64".into()),
                };
                let secret = outlayer::encryption_keys::decrypt(KEY_PATH, None, &hex::decode(s("sealed")?).map_err(|e| e.to_string())?, AAD)
                    .map_err(|e| format!("unseal: {e}"))?;
                let secret: [u8; 32] = secret.try_into().map_err(|_| "secret length")?;
                let eph: [u8; 32] = hex::decode(s("eph_pub")?).map_err(|e| e.to_string())?.try_into().map_err(|_| "eph_pub length")?;
                let shared = StaticSecret::from(secret).diffie_hellman(&PublicKey::from(eph));
                let mut key = [0u8; 32];
                hkdf::Hkdf::<Sha256>::new(None, shared.as_bytes()).expand(b"fuin-tee-round-v1", &mut key).map_err(|e| e.to_string())?;
                let nonce = hex::decode(s("nonce")?).map_err(|e| e.to_string())?;
                if nonce.len() != 12 {
                    return Err("nonce length".into());
                }
                let plain = ChaCha20Poly1305::new(&key.into()).decrypt(Nonce::from_slice(&nonce), blob.as_ref()).map_err(|_| "decrypt failed")?;
                let round: Value = serde_json::from_slice(&plain).map_err(|e| format!("plaintext: {e}"))?;
                if mode == "score" {
                    return Ok(fuin_tee::score_round(&fuin_tee::round_from_json(&round)?)?.to_json(&blob_sha256));
                }
                let items = fuin_tee::items_from_json(&round)?;
                let (commit, paths) = fuin_tee::ground_sources(&items)?;
                let mut files = std::collections::HashMap::new();
                for (k, p) in paths.into_iter().enumerate() {  // errors name the file's position, never its sealed path
                    let url = format!("https://raw.githubusercontent.com/{}/{commit}/{p}", fuin_tee::GROUND_REPO);
                    let r = wasi_http_client::Client::new().get(&url).connect_timeout(Duration::from_secs(20)).send()
                        .map_err(|_| format!("fetch source file {k} failed"))?;
                    if r.status() != 200 {
                        return Err(format!("source file {k}: HTTP {}", r.status()));
                    }
                    let body = r.body().map_err(|_| format!("source file {k}: body"))?;
                    files.insert(p, String::from_utf8(body).map_err(|_| format!("source file {k} is not UTF-8"))?);
                }
                let mut out = fuin_tee::ground_round(&items, &files)?;
                out["blob_sha256"] = blob_sha256.into();
                Ok(out)
            }
            _ => Err("mode must be keygen, score or ground".into()),
        }
    }
}

fn main() {
    use std::io::{Read, Write};
    #[cfg(target_arch = "wasm32")]
    {
        let mut raw = String::new();
        std::io::stdin().read_to_string(&mut raw).ok();
        let input: serde_json::Value = serde_json::from_str(&raw).unwrap_or(serde_json::Value::Null);
        let out = tee::run(&input).unwrap_or_else(|e| serde_json::json!({"error": e.chars().take(400).collect::<String>()}));
        let mut s = out.to_string();
        s.truncate(900);
        std::io::stdout().write_all(s.as_bytes()).ok();
        std::io::stdout().flush().ok();
    }
    #[cfg(not(target_arch = "wasm32"))]
    {
        let args: Vec<String> = std::env::args().collect();
        if args.len() == 4 && args[1] == "ground" {
            let v: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(&args[2]).expect("read items")).expect("items json");
            let res = fuin_tee::items_from_json(&v).and_then(|items| {
                let (_, paths) = fuin_tee::ground_sources(&items)?;
                let files = paths.into_iter().map(|p| {
                    let text = std::fs::read_to_string(std::path::Path::new(&args[3]).join(&p)).map_err(|e| format!("{p}: {e}"))?;
                    Ok((p, text))
                }).collect::<Result<_, String>>()?;
                fuin_tee::ground_round(&items, &files)
            });
            let out = res.unwrap_or_else(|e| serde_json::json!({"error": e}));
            std::io::stdout().write_all(out.to_string().as_bytes()).ok();
            return;
        }
        if args.len() != 3 || args[1] != "plain" {
            eprintln!("usage: fuin-tee plain ROUND.json | fuin-tee ground ITEMS.json DIR");
            std::process::exit(2);
        }
        let mut raw = String::new();
        std::fs::File::open(&args[2]).and_then(|mut f| f.read_to_string(&mut raw)).expect("read round");
        let v: serde_json::Value = serde_json::from_str(&raw).expect("round json");
        let res = fuin_tee::round_from_json(&v).and_then(|r| fuin_tee::score_round(&r));
        let out = match res {
            Ok(o) => o.to_json(""),
            Err(e) => serde_json::json!({"error": e}),
        };
        std::io::stdout().write_all(out.to_string().as_bytes()).ok();
    }
}
