"""Each kind of round prints exactly the limits that apply to it (they were once picked by list position and drifted)."""
from fuin import verify as V


def test_named_limits_are_the_right_ones():
    assert V.LIMIT_SAMPLING.startswith("Sampling assumes")
    assert V.LIMIT_REVEALS.startswith("Reveals permanently disclose")
    assert V.LIMIT_TIMING.startswith("The seal precedes the result commitment")
    assert V.LIMIT_RESAMPLE.startswith("An owner could send the same sealed request")
    assert len({V.LIMIT_SAMPLING, V.LIMIT_REVEALS, V.LIMIT_TIMING, V.LIMIT_RESAMPLE}) == 4
