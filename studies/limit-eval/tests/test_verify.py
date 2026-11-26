import pathlib, shutil
from limit_eval import verify as V

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_committed_results_and_readme_reproduce():
    ok, lines = V.check(str(ROOT / "results"), str(ROOT / "README.md"))
    assert ok, "\n".join(lines)
    assert lines[-1] == "RECEIPTS REPRODUCE"


def test_readme_summary_numbers_are_parsed():
    fracs, ivals = V.readme_numbers((ROOT / "README.md").read_text())
    for x in ["0/105", "90/105", "46/105", "136/136", "134/136", "134/134"]:
        assert x in fracs, x
    assert "[0.948, 0.996]" in ivals


def test_canary_one_byte_in_committed_results_fails(tmp_path):
    shutil.copytree(ROOT / "results", tmp_path / "results")
    p = tmp_path / "results" / "baseline.md"
    p.write_text(p.read_text().replace("90/105", "91/105", 1))
    ok, lines = V.check(str(tmp_path / "results"), str(ROOT / "README.md"))
    assert not ok and any(l.startswith("FAIL baseline.md") for l in lines)


def test_canary_readme_number_not_in_rerun_fails(tmp_path):
    r = tmp_path / "README.md"
    r.write_text((ROOT / "README.md").read_text().replace("mixed 46/105", "mixed 47/105", 1))
    ok, lines = V.check(str(ROOT / "results"), str(r))
    assert not ok and any("missing: 47/105" in l for l in lines)


def test_canary_missing_committed_file_fails(tmp_path):
    (tmp_path / "results").mkdir()
    shutil.copy(ROOT / "results" / "baseline.md", tmp_path / "results" / "baseline.md")
    ok, lines = V.check(str(tmp_path / "results"), str(ROOT / "README.md"))
    assert not ok and any("missing from" in l for l in lines)
