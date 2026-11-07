from pathlib import Path

# The verifier's policies: shipped inside the package when installed (uv tool install, pip), else policy/ in the checkout.
POLICY = next((p for p in (Path(__file__).parent / "policy", Path(__file__).resolve().parents[2] / "policy") if p.is_dir()),
              Path(__file__).resolve().parents[2] / "policy")
