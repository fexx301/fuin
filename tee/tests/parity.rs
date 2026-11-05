//! The TEE scorer must score exactly like the sealed Python scorers: 3,000 generated edge cases (Unicode case folding,
//! whitespace, digits, numeric forms), scored by Python into tests/fixtures/scorer-parity.json.
use serde_json::Value;

#[test]
fn generated_edge_cases_match_python() {
    let raw = std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/../tests/fixtures/scorer-parity.json")).unwrap();
    let cases: Value = serde_json::from_str(&raw).unwrap();
    let (mut ok, mut total, mut bad) = (0, 0, vec![]);
    for c in cases["cases"].as_array().unwrap() {
        for (v2, key) in [(false, "v1"), (true, "v2")] {
            total += 1;
            let got = fuin_tee::score_text(&c["item"], c["content"].as_str().unwrap(), v2);
            if got.as_ref().ok().map(|s| u64::from(*s)) == c[key].as_u64() { ok += 1 } else if bad.len() < 8 { bad.push(format!("{key} {} {:?} → {:?}", c["item"], c["content"], got)) }
        }
    }
    assert_eq!(ok, total, "mismatches:\n{}", bad.join("\n"));
}
