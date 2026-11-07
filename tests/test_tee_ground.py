"""Answer-key grounding: the Python reference, and the verifier's offline check on a real grounded certificate."""
import json
from pathlib import Path

import pytest

from fuin import tee

FX = json.loads((Path(__file__).parent / "fixtures/tee-ground-cases.json").read_text())
CERT = Path(__file__).parent.parent / "examples/cert-near-dev-96-r6-glm-5.3-flash.json"


def test_reference_reproduces_the_parity_cases():
    for c in FX["cases"]:
        items = [json.loads(x["item_jcs"]) for x in c["items"]]
        assert tee.ground_round(items, [x["salt"] for x in c["items"]], FX["files"]) == c["expected"]


@pytest.mark.parametrize("path", ["../a.md", "/a.md", "a.md?x", "a b.md", ""])
def test_unsafe_paths_are_refused(path):
    item = json.loads(FX["cases"][1]["items"][0]["item_jcs"])
    item["source"]["path"] = path
    with pytest.raises(ValueError):
        tee.ground_sources([item])


def test_real_grounding_passes_offline_and_names_the_flagged_items():
    cert = json.loads(CERT.read_text())
    got = tee.check_ground_local(cert["run"]["evidence"]["tee_ground"], cert)
    assert got["commit"] in tee.tee_policy()["ground_commits"] and got["flagged"] == [14, 35, 46, 94]


def _mutated(mutate):
    cert = json.loads(CERT.read_text())
    ev = cert["run"]["evidence"]["tee_ground"]
    mutate(ev["output"])
    ev["record"]["output_hash"] = __import__("hashlib").sha256(tee._sorted_compact(ev["output"]).encode()).hexdigest()
    return ev, cert


@pytest.mark.parametrize("mutate", [lambda o: o.update(n=95), lambda o: o.update(flagged=3), lambda o: o.update(flags=o["flags"][:-2]),
                                    lambda o: o.update(flags=o["flags"][:-1] + "3"), lambda o: o.update(repo="fork/docs")])
def test_inconsistent_groundings_are_refused(mutate):
    with pytest.raises(tee.TeeRefused):
        tee.check_ground_local(*_mutated(mutate))


def test_unpinned_commit_cant_certify():
    with pytest.raises(tee.TeeUnapproved):
        tee.check_ground_local(*_mutated(lambda o: o.update(commit="33" * 20)))
