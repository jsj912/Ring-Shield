"""--score-only / --score-batch-size / --ckpt-dir argument rules in models/mega_adapter.py."""
import pytest

mega = pytest.importorskip("models.mega_adapter")


@pytest.mark.parametrize("argv", [
    ["--ckpt-dir", "x"],                      # --ckpt-dir without --score-only
    ["--score-only", "--dry-run"],            # exclusive modes
])
def test_bad_flag_combinations_exit_before_loading(argv, monkeypatch):
    monkeypatch.setattr(mega, "load_paths", lambda: pytest.fail("data loading reached"))
    with pytest.raises(SystemExit):
        mega.main(argv)


def test_score_only_skips_training_loop():
    src = open(mega.__file__, encoding="utf-8").read()
    assert "range(1, (0 if a.score_only else a.epochs) + 1)" in src
    assert "if not a.score_only:\n            pd.DataFrame(log).to_csv" in src
