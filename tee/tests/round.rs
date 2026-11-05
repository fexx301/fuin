//! A synthetic 3-item round (scripts/make_tee_fixture.py): the scorer reproduces Python's outcome and refuses tampering.
use serde_json::Value;

fn fixture() -> (Value, Value) {
    let raw = std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/../tests/fixtures/tee-synthetic-round.json")).unwrap();
    let v: Value = serde_json::from_str(&raw).unwrap();
    (v["round"].clone(), v["expected"].clone())
}

fn score(round: &Value) -> Result<Value, String> {
    let o = fuin_tee::score_round(&fuin_tee::round_from_json(round)?)?;
    Ok(o.to_json(""))
}

#[test]
fn reproduces_the_python_outcome() {
    let (round, exp) = fixture();
    let got = score(&round).unwrap();
    for k in ["model", "n", "total", "benchmark_root", "policy_hash", "run_root", "signer"] {
        assert_eq!(got[k], exp[k], "{k}");
    }
}

fn refused(mutate: impl Fn(&mut Value), want: &str) {
    let (mut round, _) = fixture();
    mutate(&mut round);
    let err = score(&round).expect_err("tampering must be refused");
    assert!(err.contains(want), "{err} should mention {want}");
}

#[test]
fn answer_slipped_into_the_prompt_is_refused() {
    refused(|r| {
        let req = String::from_utf8(base64_decode(r["rows"][0]["request_b64"].as_str().unwrap())).unwrap().replace("Answer with", "(it is 42) Answer with");
        r["rows"][0]["request_b64"] = base64_encode(req.as_bytes()).into();
    }, "request_policy_mismatch");
}

#[test]
fn edited_response_breaks_the_signature_text() {
    refused(|r| r["rows"][1]["response_b64"] = base64_encode(br#"{"choices":[{"message":{"content":"blue"}}]}"#).into(), "signature_text_mismatch");
}

#[test]
fn signature_from_another_key_is_refused() {
    refused(|r| r["rows"][2]["signature"]["signing_address"] = "0x0000000000000000000000000000000000000001".into(), "bad_signature");
}

#[test]
fn unsupported_scorer_is_refused() {
    refused(|r| { let p = r["policy_jcs"].as_str().unwrap().replace("fuin-scorer-v2", "fuin-scorer-v9"); r["policy_jcs"] = p.into(); }, "unsupported scorer");
}

#[test]
fn missing_row_is_refused() {
    refused(|r| { r["rows"].as_array_mut().unwrap().pop(); }, "one to one");
}

#[test]
fn float_setting_is_refused() {
    refused(|r| { let p = r["policy_jcs"].as_str().unwrap().replace("\"temperature\":0", "\"temperature\":0.5"); r["policy_jcs"] = p.into(); }, "integer");
}

fn base64_decode(s: &str) -> Vec<u8> { use base64::Engine; base64::engine::general_purpose::STANDARD.decode(s).unwrap() }
fn base64_encode(b: &[u8]) -> String { use base64::Engine; base64::engine::general_purpose::STANDARD.encode(b) }
