//! Answer-key grounding must match the Python reference exactly (scripts/make_ground_fixture.py writes the cases).
use serde_json::Value;
use std::collections::HashMap;

#[test]
fn grounding_matches_python() {
    let raw = std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/../tests/fixtures/tee-ground-cases.json")).unwrap();
    let fx: Value = serde_json::from_str(&raw).unwrap();
    let files: HashMap<String, String> =
        fx["files"].as_object().unwrap().iter().map(|(k, v)| (k.clone(), v.as_str().unwrap().to_string())).collect();
    for c in fx["cases"].as_array().unwrap() {
        let items = fuin_tee::items_from_json(c).unwrap();
        assert_eq!(fuin_tee::ground_round(&items, &files).unwrap(), c["expected"]);
    }
}

#[test]
fn refuses_what_it_cannot_fetch_safely() {
    let raw = std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/../tests/fixtures/tee-ground-cases.json")).unwrap();
    let fx: Value = serde_json::from_str(&raw).unwrap();
    for (from, to) in [("\"path\":\"a.md\"", "\"path\":\"../a.md\""), ("\"path\":\"a.md\"", "\"path\":\"a.md?x\""),
                       ("e2d2ea173cf462bcf518ecae5650984a221d5183", "E2D2EA173CF462BCF518ECAE5650984A221D5183")] {
        let mut c = fx["cases"][0].clone();
        let s = c["items"][0]["item_jcs"].as_str().unwrap().replace(from, to);
        c["items"][0]["item_jcs"] = s.into();
        assert!(fuin_tee::ground_sources(&fuin_tee::items_from_json(&c).unwrap()).is_err(), "{to}");
    }
    let mut c = fx["cases"][0].clone();  // a second commit
    let s = c["items"][1]["item_jcs"].as_str().unwrap().replace("e2d2ea17", "f2d2ea17");
    c["items"][1]["item_jcs"] = s.into();
    assert!(fuin_tee::ground_sources(&fuin_tee::items_from_json(&c).unwrap()).is_err());
}
