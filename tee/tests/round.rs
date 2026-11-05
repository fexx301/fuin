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

fn fixture_v2() -> (Value, Value) {
    let raw = std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/../tests/fixtures/tee-synthetic-round-v2.json")).unwrap();
    let v: Value = serde_json::from_str(&raw).unwrap();
    (v["round"].clone(), v["expected"].clone())
}

#[test]
fn template_v2_reproduces_python_and_reports_the_seal_block() {
    let (round, exp) = fixture_v2();
    let got = score(&round).unwrap();
    for k in ["model", "n", "total", "benchmark_root", "policy_hash", "run_root", "signer", "seal_block_hash"] {
        assert_eq!(got[k], exp[k], "{k}");
    }
}

#[test]
fn template_v2_with_another_seal_block_is_refused() {
    let (mut round, _) = fixture_v2();
    round["seal_block_hash"] = "11111111111111111111111111111112".into(); // a different 32-byte hash
    let err = score(&round).expect_err("requests were built for the real seal block");
    assert!(err.contains("request_policy_mismatch"), "{err}");
}

#[test]
fn template_v2_without_the_seal_block_is_refused() {
    let (mut round, _) = fixture_v2();
    round.as_object_mut().unwrap().remove("seal_block_hash");
    assert!(score(&round).unwrap_err().contains("seal block hash"));
}

fn fixture_v3() -> (Value, Value) {
    let raw = std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/../tests/fixtures/tee-synthetic-round-v3.json")).unwrap();
    let v: Value = serde_json::from_str(&raw).unwrap();
    (v["round"].clone(), v["expected"].clone())
}

#[test]
fn template_v3_re_encrypts_every_question_and_scores_the_decrypted_answers_like_python() {
    let (round, exp) = fixture_v3();
    let got = score(&round).unwrap();
    for k in ["model", "n", "total", "benchmark_root", "policy_hash", "run_root", "signer", "seal_block_hash"] {
        assert_eq!(got[k], exp[k], "{k}");
    }
    assert_eq!(got["total"], 2); // item 2's answer is encrypted to another key: unreadable, so 0
    assert_eq!(got["unreadable"], 1); // and counted, so a deliberately unreadable answer shows in the attested output
}

#[test]
fn template_v3_with_a_key_other_than_the_signers_is_refused() {
    let (mut round, _) = fixture_v3();
    // a valid secp256k1 key (the generator point), but not the one the questions went to or the one that signed
    round["model_pub"] = "79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f8179848\
3ada7726a3c4655da4fbfc0e1108a8fd17b448a68554199c47d08ffb10d4b8".into();
    assert!(score(&round).unwrap_err().contains("request_policy_mismatch"));
}

#[test]
fn template_v3_without_the_model_key_is_refused() {
    let (mut round, _) = fixture_v3();
    round.as_object_mut().unwrap().remove("model_pub");
    assert!(score(&round).unwrap_err().contains("model's key"));
}
