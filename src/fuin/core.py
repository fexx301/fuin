"""Pure protocol core: encoding, Merkle commitments, audit size and sampling (spec: Encoding, Audit strength)."""

import hashlib
import json
import math
from fractions import Fraction
from math import comb

import rfc8785

TARGET = Fraction(95, 100)
MAX_SAFE_INT = 2**53 - 1


def sha256(*parts: bytes) -> bytes:
    return hashlib.sha256(b"".join(parts)).digest()


def u64(x: int) -> bytes:
    return x.to_bytes(8, "big")


def jcs(obj) -> bytes:
    """RFC 8785 canonical JSON, UTF-8."""
    _check_ints(obj)
    return rfc8785.dumps(obj)


def _check_ints(obj):
    if isinstance(obj, bool):
        return
    if isinstance(obj, int) and abs(obj) > MAX_SAFE_INT:
        raise ValueError("integer outside the interoperable exact range")
    if isinstance(obj, dict):
        for v in obj.values():
            _check_ints(v)
    elif isinstance(obj, list):
        for v in obj:
            _check_ints(v)


def loads_strict(data: bytes | str):
    """Parse JSON rejecting duplicate keys and non-finite numbers."""

    def pairs(kv):
        d = {}
        for k, v in kv:
            if k in d:
                raise ValueError(f"duplicate key {k!r}")
            d[k] = v
        return d

    def bad_constant(c):
        raise ValueError(f"non-finite number {c}")

    if isinstance(data, bytes):
        data = data.decode("utf-8")  # strict: invalid UTF-8 raises
    return json.loads(data, object_pairs_hook=pairs, parse_constant=bad_constant)


# --- Merkle (spec: leaves ordered by index, duplicate last node at odd widths) ---

def benchmark_leaf(i: int, salt: bytes, item: dict) -> bytes:
    if len(salt) != 32:
        raise ValueError("salt must be 32 bytes")
    return sha256(b"\x00", u64(i), salt, jcs(item))


def run_leaf(i: int, bleaf: bytes, req_sha: bytes, resp_sha: bytes, score: int) -> bytes:
    if score not in (0, 1):
        raise ValueError("score must be 0 or 1")
    return sha256(b"\x02", u64(i), bleaf, req_sha, resp_sha, bytes([score]))


def parent(left: bytes, right: bytes) -> bytes:
    return sha256(b"\x01", left, right)


def _next_level(level: list[bytes]) -> list[bytes]:
    if len(level) % 2:
        level = level + [level[-1]]
    return [parent(level[j], level[j + 1]) for j in range(0, len(level), 2)]


def merkle_root(leaves: list[bytes]) -> bytes:
    if not leaves:
        raise ValueError("n must be >= 1")
    level = list(leaves)
    while len(level) > 1:
        level = _next_level(level)
    return level[0]


def merkle_proof(leaves: list[bytes], i: int) -> list[bytes]:
    level, idx, proof = list(leaves), i, []
    while len(level) > 1:
        sib = idx ^ 1
        proof.append(level[sib] if sib < len(level) else level[idx])
        level, idx = _next_level(level), idx // 2
    return proof


def verify_proof(leaf: bytes, i: int, n: int, proof: list[bytes], root: bytes) -> bool:
    if not (n >= 1 and 0 <= i < n):
        return False
    node, idx, width, used = leaf, i, n, 0
    while width > 1:
        if used >= len(proof):
            return False
        sib = proof[used]
        used += 1
        if idx % 2 == 0:
            if idx == width - 1 and sib != node:  # odd-width last node pairs with itself
                return False
            node = parent(node, sib)
        else:
            node = parent(sib, node)
        idx, width = idx // 2, (width + 1) // 2
    return used == len(proof) and node == root


# --- Audit strength (exact rational arithmetic) ---

def p_detect(n: int, d: int, k: int) -> Fraction:
    miss = comb(n - d, k) if k <= n - d else 0
    return 1 - Fraction(miss, comb(n, k))


def audit_size(n: int, target: Fraction = TARGET) -> tuple[int, int]:
    """Return (D, k): D = ceil(n/10) bad scores, smallest k detecting one with probability >= target."""
    if n < 1:  # a clear error, not an "unreachable" assertion, for library callers (review 13)
        raise ValueError("a round needs at least one item")
    d = math.ceil(n / 10)
    for k in range(1, n + 1):
        if p_detect(n, d, k) >= target:
            return d, k
    raise AssertionError("unreachable: k = n always detects")


# --- Sampler (rejection sampling, no modulo bias) ---

def audit_seed(selected_block_hash: bytes, context_hash: bytes) -> bytes:
    return sha256(b"fuin-audit-v1", selected_block_hash, context_hash)


def context_hash(ctx: dict) -> bytes:
    return sha256(jcs(ctx))


def sample_indices(seed: bytes, n: int, k: int, max_counter: int = 1 << 20) -> list[int]:
    if not 1 <= k <= n:
        raise ValueError("need 1 <= k <= n")
    limit = (2**256 // n) * n
    chosen: set[int] = set()
    for counter in range(max_counter):
        x = int.from_bytes(sha256(seed, u64(counter)), "big")
        if x < limit:
            chosen.add(x % n)
            if len(chosen) == k:
                return sorted(chosen)
    raise ValueError("sampler counter exhausted")


B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(b: bytes) -> str:
    n, out = int.from_bytes(b, "big"), ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + out


def b58decode(s: str) -> bytes:
    n = 0
    for c in s:
        n = n * 58 + B58.index(c)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return b"\0" * (len(s) - len(s.lstrip("1"))) + raw


def seal_bound_nonce(item_nonce_hex: str, seal_block_hash_b58: str) -> str:
    """Request template v2: sha256("fuin-nonce-v2" ‖ sealed item nonce ‖ seal block hash). The seal block's hash doesn't
    exist until the seal lands, so no request with this nonce, and no answer signed over it, can predate the seal."""
    return sha256(b"fuin-nonce-v2", bytes.fromhex(item_nonce_hex), b58decode(seal_block_hash_b58)).hex()


MAX_ITEMS = 1_000_000  # the most items one round may have (the verifier's bound; the registry contract doesn't cap it)
NUMBER_EXP = 100       # a sealed numeric answer or tolerance must be finite with magnitude within 10^-100 .. 10^100


def sealed_number_ok(s, tolerance: bool = False) -> bool:
    """A numeric item's sealed answer or tolerance, as all three scorers can read it: a decimal string (Python's Decimal
    syntax), finite (no Infinity or NaN), with an exponent the browser and TEE scorers can scale, and a tolerance >= 0."""
    from decimal import Decimal, InvalidOperation
    if not isinstance(s, str):
        return False
    try:
        d = Decimal(s)
    except InvalidOperation:
        return False
    return d.is_finite() and (d.is_zero() or -NUMBER_EXP <= d.adjusted() <= NUMBER_EXP) and (not tolerance or d >= 0)
