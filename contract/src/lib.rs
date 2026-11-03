//! Fūin registry: append-only seals and run commitments for private benchmarks.
//!
//! No owner/admin methods and no upgrade path in code. After deploy the registry
//! account's full-access key is deleted so the code cannot be replaced.

use near_sdk::store::LookupMap;
use near_sdk::{env, near, require, AccountId, BlockHeight, NearToken, PanicOnDefault, Promise};

const MAX_ID: usize = 64;
const MAX_MODELS: usize = 8;
const MAX_RUNS: usize = 32;

#[near(serializers = [json, borsh])]
#[derive(Clone)]
pub struct Benchmark {
    pub owner: AccountId,
    pub benchmark_id: String,
    pub root: String,
    pub n: u32,
    pub policy_hash: String,
    pub models: Vec<String>,
    pub seal_height: BlockHeight,
    pub last_commit_height: Option<BlockHeight>,
    pub close_height: Option<BlockHeight>,
    pub runs: Vec<RunRecord>,
}

#[near(serializers = [json, borsh])]
#[derive(Clone)]
pub struct RunRecord {
    pub model_id: String,
    pub run_index: u32,
    pub run_root: String,
    pub total_score: u32,
    pub commit_height: BlockHeight,
}

#[near(contract_state)]
#[derive(PanicOnDefault)]
pub struct Registry {
    benchmarks: LookupMap<String, Benchmark>,
}

fn key(owner: &AccountId, benchmark_id: &str) -> String {
    format!("{owner}/{benchmark_id}")
}

fn require_hex32(s: &str, what: &str) {
    require!(
        s.len() == 64 && s.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)),
        format!("{what} must be 64 lowercase hex characters")
    );
}

fn require_id(s: &str, what: &str) {
    require!(
        !s.is_empty() && s.len() <= MAX_ID && s.bytes().all(|b| b.is_ascii_graphic() && b != b'/'),
        format!("{what} must be 1-{MAX_ID} printable ASCII characters without '/'")
    );
}

/// Callers pay for the storage their call adds; any excess deposit is refunded.
fn charge_storage(before: u64) {
    let added = env::storage_usage().saturating_sub(before) as u128;
    let cost = added * env::storage_byte_cost().as_yoctonear();
    let paid = env::attached_deposit().as_yoctonear();
    require!(paid >= cost, format!("attach at least {cost} yoctoNEAR to pay for {added} bytes of storage"));
    if paid > cost {
        Promise::new(env::predecessor_account_id()).transfer(NearToken::from_yoctonear(paid - cost)).detach();
    }
}

#[near]
impl Registry {
    #[init]
    pub fn new() -> Self {
        Self { benchmarks: LookupMap::new(b"b") }
    }

    /// Seal a benchmark: its Merkle root, size and policy hash, under the caller's account.
    #[payable]
    pub fn seal(&mut self, benchmark_id: String, root: String, n: u32, policy_hash: String, models: Vec<String>) {
        let owner = env::predecessor_account_id();
        require_id(&benchmark_id, "benchmark_id");
        require_hex32(&root, "root");
        require_hex32(&policy_hash, "policy_hash");
        require!(n >= 1, "n must be at least 1");
        require!(!models.is_empty() && models.len() <= MAX_MODELS, "1-8 models");
        for (i, m) in models.iter().enumerate() {
            require!(!m.is_empty() && m.len() <= 128 && m.is_ascii(), "model ids are 1-128 ASCII characters");
            require!(!models[..i].contains(m), "duplicate model id");
        }
        let k = key(&owner, &benchmark_id);
        require!(!self.benchmarks.contains_key(&k), "benchmark already sealed");
        let before = env::storage_usage();
        self.benchmarks.insert(
            k,
            Benchmark {
                owner,
                benchmark_id,
                root,
                n,
                policy_hash,
                models,
                seal_height: env::block_height(),
                last_commit_height: None,
                close_height: None,
                runs: vec![],
            },
        );
        self.benchmarks.flush();
        charge_storage(before);
    }

    /// Commit one run's result root and total; the registry assigns the run index.
    #[payable]
    pub fn commit_run(&mut self, benchmark_id: String, model_id: String, run_root: String, total_score: u32) -> u32 {
        let owner = env::predecessor_account_id();
        require_hex32(&run_root, "run_root");
        let b = self.benchmarks.get_mut(&key(&owner, &benchmark_id)).unwrap_or_else(|| env::panic_str("no such benchmark for this owner"));
        let height = env::block_height();
        require!(b.close_height.is_none(), "round is closed");
        require!(height > b.seal_height, "run must execute in a later block than its seal");
        require!(b.models.contains(&model_id), "model not in the sealed list");
        require!(total_score <= b.n, "total_score exceeds n");
        require!(b.runs.len() < MAX_RUNS, "run limit reached for this benchmark");
        let run_index = b.runs.iter().filter(|r| r.model_id == model_id).count() as u32;
        b.runs.push(RunRecord { model_id, run_index, run_root, total_score, commit_height: height });
        b.last_commit_height = Some(height);
        let before = env::storage_usage();
        self.benchmarks.flush();
        charge_storage(before);
        run_index
    }

    /// Close the round: no more runs; the audit seed is taken from a finalized block after this one.
    #[payable]
    pub fn close_round(&mut self, benchmark_id: String) {
        let owner = env::predecessor_account_id();
        let b = self.benchmarks.get_mut(&key(&owner, &benchmark_id)).unwrap_or_else(|| env::panic_str("no such benchmark for this owner"));
        require!(b.close_height.is_none(), "round already closed");
        let height = env::block_height();
        require!(height > b.last_commit_height.unwrap_or(b.seal_height), "close must execute after the last commit");
        b.close_height = Some(height);
        let before = env::storage_usage();
        self.benchmarks.flush();
        charge_storage(before);
    }

    pub fn get_benchmark(&self, owner: AccountId, benchmark_id: String) -> Option<Benchmark> {
        self.benchmarks.get(&key(&owner, &benchmark_id)).cloned()
    }

    pub fn get_run(&self, owner: AccountId, benchmark_id: String, model_id: String, run_index: u32) -> Option<RunRecord> {
        self.benchmarks
            .get(&key(&owner, &benchmark_id))?
            .runs
            .iter()
            .find(|r| r.model_id == model_id && r.run_index == run_index)
            .cloned()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use near_sdk::test_utils::{accounts, VMContextBuilder};
    use near_sdk::testing_env;

    const H: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const R: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

    fn at(who: usize, height: u64) {
        pay(who, height, NearToken::from_millinear(100));
    }

    fn pay(who: usize, height: u64, deposit: NearToken) {
        testing_env!(VMContextBuilder::new()
            .predecessor_account_id(accounts(who))
            .block_height(height)
            .attached_deposit(deposit)
            .build());
    }

    fn sealed() -> Registry {
        at(0, 10);
        let mut r = Registry::new();
        r.seal("suite".into(), H.into(), 5, H.into(), vec!["m1".into(), "m2".into()]);
        r
    }

    #[test]
    fn happy_path_numbers_runs_and_closes() {
        let mut r = sealed();
        at(0, 11);
        assert_eq!(r.commit_run("suite".into(), "m1".into(), R.into(), 4), 0);
        at(0, 12);
        assert_eq!(r.commit_run("suite".into(), "m1".into(), R.into(), 5), 1);
        assert_eq!(r.commit_run("suite".into(), "m2".into(), R.into(), 3), 0);
        at(0, 13);
        r.close_round("suite".into());
        let b = r.get_benchmark(accounts(0), "suite".into()).unwrap();
        assert_eq!((b.seal_height, b.close_height, b.runs.len()), (10, Some(13), 3));
        assert_eq!(r.get_run(accounts(0), "suite".into(), "m1".into(), 1).unwrap().total_score, 5);
    }

    #[test]
    #[should_panic(expected = "already sealed")]
    fn no_overwrite() {
        let mut r = sealed();
        r.seal("suite".into(), R.into(), 5, H.into(), vec!["m1".into()]);
    }

    #[test]
    fn same_id_is_scoped_per_owner() {
        let mut r = sealed();
        at(1, 11);
        r.seal("suite".into(), R.into(), 3, H.into(), vec!["m1".into()]);
        assert_eq!(r.get_benchmark(accounts(1), "suite".into()).unwrap().n, 3);
        assert_eq!(r.get_benchmark(accounts(0), "suite".into()).unwrap().n, 5);
    }

    #[test]
    #[should_panic(expected = "no such benchmark for this owner")]
    fn others_cannot_commit() {
        let mut r = sealed();
        at(1, 11);
        r.commit_run("suite".into(), "m1".into(), R.into(), 1);
    }

    #[test]
    #[should_panic(expected = "later block than its seal")]
    fn commit_same_block_as_seal() {
        let mut r = sealed();
        r.commit_run("suite".into(), "m1".into(), R.into(), 1);
    }

    #[test]
    #[should_panic(expected = "round is closed")]
    fn no_commit_after_close() {
        let mut r = sealed();
        at(0, 11);
        r.close_round("suite".into());
        at(0, 12);
        r.commit_run("suite".into(), "m1".into(), R.into(), 1);
    }

    #[test]
    #[should_panic(expected = "after the last commit")]
    fn close_same_block_as_commit() {
        let mut r = sealed();
        at(0, 11);
        r.commit_run("suite".into(), "m1".into(), R.into(), 1);
        r.close_round("suite".into());
    }

    #[test]
    #[should_panic(expected = "exceeds n")]
    fn score_range() {
        let mut r = sealed();
        at(0, 11);
        r.commit_run("suite".into(), "m1".into(), R.into(), 6);
    }

    #[test]
    #[should_panic(expected = "not in the sealed list")]
    fn unsealed_model() {
        let mut r = sealed();
        at(0, 11);
        r.commit_run("suite".into(), "gpt".into(), R.into(), 1);
    }

    #[test]
    #[should_panic(expected = "64 lowercase hex")]
    fn bad_root() {
        at(0, 10);
        let mut r = Registry::new();
        r.seal("s".into(), "AB".into(), 1, H.into(), vec!["m".into()]);
    }

    #[test]
    #[should_panic(expected = "to pay for")]
    fn seal_without_storage_deposit_is_rejected() {
        pay(0, 10, NearToken::from_yoctonear(0));
        let mut r = Registry::new();
        r.seal("s".into(), H.into(), 1, H.into(), vec!["m".into()]);
    }

    #[test]
    #[should_panic(expected = "to pay for")]
    fn commit_without_storage_deposit_is_rejected() {
        let mut r = sealed();
        pay(0, 11, NearToken::from_yoctonear(0));
        r.commit_run("suite".into(), "m1".into(), R.into(), 1);
    }

    #[test]
    #[should_panic(expected = "run limit")]
    fn run_count_is_capped() {
        let mut r = sealed();
        for h in 0..=MAX_RUNS as u64 {
            at(0, 11 + h);
            r.commit_run("suite".into(), "m1".into(), R.into(), 1);
        }
    }

    #[test]
    #[should_panic(expected = "1-64 printable")]
    fn oversized_id_is_rejected() {
        at(0, 10);
        let mut r = Registry::new();
        r.seal("x".repeat(65), H.into(), 1, H.into(), vec!["m".into()]);
    }

    #[test]
    #[should_panic(expected = "1-8 models")]
    fn too_many_models_is_rejected() {
        at(0, 10);
        let mut r = Registry::new();
        r.seal("s".into(), H.into(), 1, H.into(), (0..9).map(|i| format!("m{i}")).collect());
    }
}
