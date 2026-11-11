"""Each kind of round prints exactly the limits that apply to it (they were once picked by list position and drifted)."""
from fuin import verify as V


def test_named_limits_are_the_right_ones():
    assert V.LIMIT_SAMPLING.startswith("Sampling assumes")
    assert V.LIMIT_REVEALS.startswith("Reveals permanently disclose")
    assert V.LIMIT_TIMING.startswith("The seal precedes the result commitment")
    assert V.LIMIT_RESAMPLE.startswith("An owner could send the same sealed request")
    assert len({V.LIMIT_SAMPLING, V.LIMIT_REVEALS, V.LIMIT_TIMING, V.LIMIT_RESAMPLE}) == 4


def test_only_the_first_asker_carries_the_overlap_limit():
    from fuin import tee
    v1, v2 = tee.tee_policy()["askers"][:2]
    lim = lambda a: V.asked_limit({"audit": {"asker_wasm_sha256": a["wasm_sha256"]}})
    assert "overlap by milliseconds" in lim(v1) and lim(v1) == V.ASKED_LIMIT_V1  # round 7's printed limit is unchanged
    assert "overlap" not in lim(v2) and lim(v2) == V.ASKED_LIMIT
