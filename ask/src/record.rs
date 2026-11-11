//! The record protocol behind "asked once": how an ask claims an item, and how it writes the final answer.
//!
//! One record per (round, model, item). It is `pending` with an attempt count, or `final`. An ask goes through four
//! steps, each one storage operation:
//!   start     read the record (creating it pending, with no attempts, if absent); a final record ends the ask here
//!   claim     compare-and-set from the record as read to {pending, attempts + 1, this ask's own random id}
//!   confirm   read the record back: it must be, byte for byte, this ask's claim, or the ask stops
//!   finalize  compare-and-set from that confirmed claim to the final record
//! The model is called only between confirm and finalize.
//!
//! What this guarantees, however asks overlap, time out or restart (tests below try every interleaving):
//!   - the attempt count never goes down;
//!   - every model call belongs to its own confirmed claim, so the count is never below the number of model calls;
//!   - at most one ask finalises, the final record is never rewritten, and its count covers every model call made.
//!
//! The first asker (build dbbb286b…, round 7) read the record back in `confirm` without comparing it. An ask that lost
//! the record to a later claim then finalised against that later claim with its own, lower, count: one retry could go
//! uncounted. A claim that never reaches the model is still counted here; the count may overstate, never understate.

use serde_json::{json, Value};

/// Storage with compare-and-set on a handle to the bytes as stored (OutLayer's sealed storage; a map in the tests).
pub trait Store {
    type Handle;
    fn get(&self, name: &str) -> Result<Option<(Vec<u8>, Self::Handle)>, String>;
    fn set_if_absent(&self, name: &str, value: &[u8]) -> Result<bool, String>;
    fn set_if_equals(&self, name: &str, expected: &Self::Handle, value: &[u8]) -> Result<bool, String>;
}

pub enum Start<H> {
    Final(Value),
    Pending { attempts: u64, handle: H },
}

pub fn start<S: Store>(s: &S, name: &str) -> Result<Start<S::Handle>, String> {
    let (bytes, handle) = match s.get(name)? {
        Some(x) => x,
        None => {
            s.set_if_absent(name, br#"{"s":"pending","a":0}"#)?;
            s.get(name)?.ok_or("record vanished")?
        }
    };
    let rec: Value = serde_json::from_slice(&bytes).map_err(|_| "record unreadable")?;
    if rec["s"] == "final" {
        return Ok(Start::Final(rec));
    }
    Ok(Start::Pending { attempts: rec["a"].as_u64().ok_or("record has no attempt count")?, handle })
}

/// Returns this ask's claim as written; its attempt number is `attempts + 1`.
pub fn claim<S: Store>(s: &S, name: &str, attempts: u64, handle: &S::Handle, id: &str) -> Result<Vec<u8>, String> {
    let mine = json!({"s": "pending", "a": attempts + 1, "c": id}).to_string().into_bytes();
    if !s.set_if_equals(name, handle, &mine)? {
        return Err("another ask of this item is in progress".into());
    }
    Ok(mine)
}

/// A handle to this ask's own claim, or an error when another ask has claimed since: then this ask makes no model call.
pub fn confirm<S: Store>(s: &S, name: &str, mine: &[u8]) -> Result<S::Handle, String> {
    match s.get(name)? {
        Some((bytes, handle)) if bytes == mine => Ok(handle),
        _ => Err("another ask claimed this item".into()),
    }
}

pub fn finalize<S: Store>(s: &S, name: &str, claim: &S::Handle, fin: &Value) -> Result<(), String> {
    if !s.set_if_equals(name, claim, fin.to_string().as_bytes())? {
        return Err("record changed during the ask".into());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;

    /// One record. Every write gets a new version, as every sealing gets new ciphertext: equal bytes written twice
    /// are still told apart.
    #[derive(Clone, Default)]
    struct Mem {
        rec: RefCell<Option<(u64, Vec<u8>)>>,
        writes: RefCell<u64>,
    }
    impl Mem {
        fn put(&self, v: &[u8]) {
            *self.writes.borrow_mut() += 1;
            *self.rec.borrow_mut() = Some((*self.writes.borrow(), v.to_vec()));
        }
        fn value(&self) -> Option<Value> {
            self.rec.borrow().as_ref().map(|(_, b)| serde_json::from_slice(b).unwrap())
        }
    }
    impl Store for Mem {
        type Handle = u64;
        fn get(&self, _: &str) -> Result<Option<(Vec<u8>, u64)>, String> {
            Ok(self.rec.borrow().as_ref().map(|(ver, b)| (b.clone(), *ver)))
        }
        fn set_if_absent(&self, _: &str, v: &[u8]) -> Result<bool, String> {
            if self.rec.borrow().is_some() {
                return Ok(false);
            }
            self.put(v);
            Ok(true)
        }
        fn set_if_equals(&self, _: &str, expected: &u64, v: &[u8]) -> Result<bool, String> {
            if self.rec.borrow().as_ref().map(|(ver, _)| ver) != Some(expected) {
                return Ok(false);
            }
            self.put(v);
            Ok(true)
        }
    }

    /// One ask as a machine that takes one storage step at a time, so asks can be interleaved at every point.
    #[derive(Clone)]
    struct Ask {
        id: String,
        pc: u8,          // 0 start, 1 claim, 2 confirm, 3 model call, 4 finalize, 5 over
        dies_after: u8,  // the ask is killed (a timeout, a crash) once it has taken this many steps
        attempts: u64,
        h: u64,
        mine: Vec<u8>,
    }

    #[derive(Clone, Default)]
    struct World {
        mem: Mem,
        calls: u64,           // model calls made
        finals: u64,          // asks that finalised
        final_rec: Option<Value>,
        low_water: u64,       // highest attempt count seen
    }

    /// `careless` is the first asker's confirm: read the record back and trust it.
    fn step(a: &mut Ask, w: &mut World, careless: bool) {
        if a.pc >= a.dies_after {
            a.pc = 5;
            return;
        }
        match a.pc {
            0 => match start(&w.mem, "r").unwrap() {
                Start::Final(_) => a.pc = 5,
                Start::Pending { attempts, handle } => { a.attempts = attempts; a.h = handle; a.pc = 1; }
            },
            1 => match claim(&w.mem, "r", a.attempts, &a.h, &a.id) {
                Ok(mine) => { a.mine = mine; a.attempts += 1; a.pc = 2; }
                Err(_) => a.pc = 5,
            },
            2 => {
                let got = if careless { w.mem.get("r").unwrap().map(|(_, h)| h).ok_or(String::new()) } else { confirm(&w.mem, "r", &a.mine) };
                match got { Ok(h) => { a.h = h; a.pc = 3; } Err(_) => a.pc = 5 }
            }
            3 => { w.calls += 1; a.pc = 4; }
            _ => {
                if finalize(&w.mem, "r", &a.h, &json!({"s": "final", "a": a.attempts, "by": a.id})).is_ok() {
                    w.finals += 1;
                }
                a.pc = 5;
            }
        }
    }

    /// What must hold after every step. Returns the first broken rule.
    fn broken(w: &mut World) -> Option<&'static str> {
        let rec = w.mem.value();
        let a = rec.as_ref().and_then(|r| r["a"].as_u64()).unwrap_or(0);
        if a < w.low_water {
            return Some("the attempt count went down");
        }
        w.low_water = a;
        if w.finals > 1 {
            return Some("two asks finalised");
        }
        if let Some(f) = &w.final_rec {
            if rec.as_ref() != Some(f) {
                return Some("a final record was rewritten");
            }
        } else if rec.as_ref().map_or(false, |r| r["s"] == "final") {
            w.final_rec = rec.clone();
        }
        if rec.as_ref().map_or(false, |r| r["s"] == "final") && a < w.calls {
            return Some("the final count is below the model calls made");
        }
        None
    }

    /// Every interleaving of the asks' steps. Returns how many schedules ran and the first broken rule, if any.
    fn explore(asks: Vec<Ask>, w: World, careless: bool, seen: &mut u64) -> Option<&'static str> {
        let live: Vec<usize> = (0..asks.len()).filter(|&i| asks[i].pc < 5).collect();
        if live.is_empty() {
            *seen += 1;
            return None;
        }
        for i in live {
            let (mut asks2, mut w2) = (asks.clone(), w.clone());
            step(&mut asks2[i], &mut w2, careless);
            if let Some(b) = broken(&mut w2).or_else(|| explore(asks2, w2, careless, seen)) {
                return Some(b);
            }
        }
        None
    }

    fn asks(n: usize, dies_after: &[u8]) -> Vec<Ask> {
        (0..n).map(|i| Ask { id: format!("ask{i}"), pc: 0, dies_after: dies_after[i], attempts: 0, h: 0, mine: vec![] }).collect()
    }

    #[test]
    fn overlapping_asks_never_lose_an_attempt() {
        let mut seen = 0;
        assert_eq!(explore(asks(2, &[9, 9]), World::default(), false, &mut seen), None);
        assert_eq!(explore(asks(3, &[9, 9, 9]), World::default(), false, &mut seen), None);
        assert!(seen > 1000, "only {seen} schedules");
    }

    #[test]
    fn asks_killed_at_any_step_never_lose_an_attempt() {
        // timeouts and crashes: each of three overlapping asks dies after 0 to 4 steps, or runs to the end
        let mut seen = 0;
        for a in 0..=5u8 {
            for b in 0..=5u8 {
                for c in [1u8, 3, 5] {
                    assert_eq!(explore(asks(3, &[a, b, c]), World::default(), false, &mut seen), None, "dies after {a}, {b}, {c}");
                }
            }
        }
        assert!(seen > 10_000, "only {seen} schedules");
    }

    #[test]
    fn a_restart_after_a_timeout_is_counted_and_a_final_answer_is_never_asked_again() {
        let mut w = World::default();
        let mut first = asks(1, &[4]).remove(0);   // claims, calls the model, is killed before it can finalise
        while first.pc < 5 { step(&mut first, &mut w, false); }
        assert_eq!((w.calls, w.finals), (1, 0));
        let mut second = Ask { id: "restart".into(), pc: 0, dies_after: 9, attempts: 0, h: 0, mine: vec![] };
        while second.pc < 5 { step(&mut second, &mut w, false); }
        assert_eq!(w.mem.value().unwrap()["a"], 2);                          // both model calls are in the count
        assert_eq!((w.calls, w.finals), (2, 1));
        let mut third = Ask { id: "again".into(), pc: 0, dies_after: 9, attempts: 0, h: 0, mine: vec![] };
        while third.pc < 5 { step(&mut third, &mut w, false); }
        assert_eq!((w.calls, w.finals), (2, 1));                             // a final record ends the ask at once
        assert_eq!(w.mem.value().unwrap()["by"], "restart");
    }

    #[test]
    fn an_ask_that_lost_its_claim_makes_no_model_call() {
        let (mut w, mut a) = (World::default(), asks(2, &[9, 9]));
        step(&mut a[0], &mut w, false); step(&mut a[0], &mut w, false);      // ask0: start, claim
        step(&mut a[1], &mut w, false); step(&mut a[1], &mut w, false);      // ask1 claims over it
        while a[0].pc < 5 { step(&mut a[0], &mut w, false); }
        assert_eq!(w.calls, 0);                                              // ask0 stopped at confirm
        while a[1].pc < 5 { step(&mut a[1], &mut w, false); }
        assert_eq!((w.calls, w.finals), (1, 1));
        assert_eq!(w.mem.value().unwrap()["a"], 2);                          // ask0's claim stays counted
    }

    #[test]
    fn these_tests_catch_the_first_askers_race() {
        // the same search, with confirm as the first asker had it, finds the undercount: an ask that lost the record
        // to a later claim finalises with its own, lower, count
        let mut seen = 0;
        assert_eq!(explore(asks(2, &[9, 9]), World::default(), true, &mut seen), Some("the attempt count went down"));
    }

    #[test]
    fn a_record_without_a_count_is_refused() {
        let w = World::default();
        w.mem.put(br#"{"s":"pending"}"#);
        assert!(matches!(start(&w.mem, "r"), Err(e) if e.contains("attempt count")));
    }
}
