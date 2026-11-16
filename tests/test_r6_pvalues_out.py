"""--out and --pvalues-out in a temp folder: the detector-swap builder writes nothing under
results/tables/ (guards the 2026-11-14 incident, where r6_pvalues.csv was always overwritten)."""
import hashlib
from pathlib import Path

import pytest

import evaluation.r6_detector_swap as m

REPO = Path(m.REPO_ROOT)
E2E = REPO.parent / "RS-e2e" / "experiments"


def _snapshot(d: Path) -> dict:
    return {p.name: (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in sorted(d.iterdir()) if p.is_file()}


def _roots():
    """Shipped run roots, or the RS-e2e copies when this checkout lacks the git-ignored runs."""
    for base in (REPO / "experiments", E2E):
        roots = {"gine_scores": base / "R1_gine_causal", "gine_b0": base / "R2_b0" / "gine_causal",
                 "gine_full": base / "R4_partition" / "runs" / "average"}
        if all((p / "seed1").exists() or any(p.glob("scores_test_seed1*")) for p in roots.values()):
            return base, roots
    return None, None


def test_pvalues_out_keeps_results_tables_untouched(tmp_path, monkeypatch):
    base, roots = _roots()
    labels = next((d for d in (REPO / "contract" / "out", E2E.parent / "contract" / "out")
                   if (d / "labels_test.parquet").exists()), None)
    if base is None or labels is None:
        pytest.skip("detector runs or contract labels not available in this checkout")
    det = {k: dict(v) for k, v in m.DETECTORS.items()}
    det["gine_causal"]["scores"] = roots["gine_scores"]
    det["gine_causal"]["runs"] = {"b0": roots["gine_b0"], "full": roots["gine_full"]}
    monkeypatch.setattr(m, "DETECTORS", det)

    before = _snapshot(m.TABLES)
    out, pv = tmp_path / "swap.csv", tmp_path / "sub" / "pvalues.csv"
    m.main(["--detectors", "gine_causal", "--seeds", "1", "2", "--n-boot", "20", "--n-perm", "50",
            "--labels-dir", str(labels),
            "--out", str(out), "--pvalues-out", str(pv)])
    assert out.exists() and pv.exists()
    assert _snapshot(m.TABLES) == before
