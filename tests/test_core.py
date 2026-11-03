import os
from fractions import Fraction

import pytest

from fuin import core


def leaves(n):
    return [core.sha256(bytes([i % 256]), core.u64(i)) for i in range(n)]


@pytest.mark.parametrize("n", [1, 2, 3, 5, 7, 8, 60])
def test_proof_round_trip_every_index(n):
    ls = leaves(n)
    root = core.merkle_root(ls)
    for i in range(n):
        assert core.verify_proof(ls[i], i, n, core.merkle_proof(ls, i), root)


def test_one_leaf_root_is_leaf():
    ls = leaves(1)
    assert core.merkle_root(ls) == ls[0]
    assert core.merkle_proof(ls, 0) == []


def test_proof_failures():
    ls = leaves(5)
    root = core.merkle_root(ls)
    p = core.merkle_proof(ls, 2)
    assert not core.verify_proof(ls[3], 2, 5, p, root)  # wrong leaf
    assert not core.verify_proof(ls[2], 3, 5, p, root)  # wrong index
    assert not core.verify_proof(ls[2], 2, 5, p[:-1], root)  # missing sibling
    assert not core.verify_proof(ls[2], 2, 5, p + [ls[0]], root)  # extra sibling
    assert not core.verify_proof(ls[2], 2, 3, p, root)  # wrong n changes depth
    # same-depth n is not caught by a proof alone; the sealed n and full root rebuild bind it
    assert core.verify_proof(ls[2], 2, 6, p, root)
    # odd-width last node: its duplicate sibling must be itself
    p4 = core.merkle_proof(ls, 4)
    assert p4[0] == ls[4]
    assert not core.verify_proof(ls[4], 4, 5, [ls[0]] + p4[1:], root)


def test_index_order_not_hash_order():
    ls = leaves(4)
    assert core.merkle_root(ls) != core.merkle_root(sorted(ls))


def test_leaf_domain_separation_and_bytes():
    salt = bytes(32)
    item = {"q": "what is 2+2?", "a": "4"}
    b = core.benchmark_leaf(0, salt, item)
    assert b != core.benchmark_leaf(1, salt, item)
    assert b != core.benchmark_leaf(0, b"\x01" + bytes(31), item)
    r = core.run_leaf(0, b, bytes(32), bytes(32), 1)
    assert r != core.run_leaf(0, b, bytes(32), bytes(32), 0)
    with pytest.raises(ValueError):
        core.run_leaf(0, b, bytes(32), bytes(32), 2)


def test_jcs_canonical_and_strict_parse():
    assert core.jcs({"b": 1, "a": "é"}) == '{"a":"é","b":1}'.encode()
    with pytest.raises(ValueError):
        core.loads_strict('{"a":1,"a":2}')
    with pytest.raises(ValueError):
        core.loads_strict('{"a":NaN}')
    with pytest.raises(ValueError):
        core.jcs({"a": 2**60})


@pytest.mark.parametrize("n,d,k,pct", [(5, 1, 5, "100"), (50, 5, 22, "95.3614"), (60, 6, 23, "95.3564")])
def test_audit_size_matches_spec_table(n, d, k, pct):
    assert core.audit_size(n) == (d, k)
    assert f"{float(core.p_detect(n, d, k) * 100):.4f}".rstrip("0").rstrip(".") == pct


def test_old_ten_percent_sample_is_weak():
    assert f"{float(core.p_detect(60, 6, 6) * 100):.4f}" == "48.4116"


def test_sampler_deterministic_distinct_sorted():
    seed = core.sha256(b"seed")
    a = core.sample_indices(seed, 60, 23)
    assert a == core.sample_indices(seed, 60, 23)
    assert a == sorted(set(a)) and len(a) == 23 and all(0 <= x < 60 for x in a)
    assert a != core.sample_indices(core.sha256(b"other"), 60, 23)
    assert core.sample_indices(seed, 5, 5) == [0, 1, 2, 3, 4]


def test_sampler_roughly_uniform():
    counts = [0] * 10
    for t in range(2000):
        for x in core.sample_indices(core.sha256(core.u64(t)), 10, 1):
            counts[x] += 1
    assert min(counts) > 140 and max(counts) < 260


def test_seed_binds_context():
    blk = os.urandom(32)
    c1 = core.context_hash({"benchmark_id": "a"})
    c2 = core.context_hash({"benchmark_id": "b"})
    assert core.audit_seed(blk, c1) != core.audit_seed(blk, c2)
