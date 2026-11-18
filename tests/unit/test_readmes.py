"""The two READMEs exist, carry the fiction notice and link each other (task 15.1)."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
README = {
    "README.md": ("Fiction notice", "README.es.md"),
    "README.es.md": ("Aviso de ficción", "README.md"),
}


@pytest.mark.parametrize("name", README)
def test_readme_has_notice_company_and_link_to_the_other(name: str) -> None:
    marker, other = README[name]
    path = ROOT / name
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert marker in text
    assert "Distribuidora El Hornero" in text
    assert f"]({other})" in text


@pytest.mark.parametrize("name", README)
def test_results_cite_the_release_report_and_every_earlier_run(name: str) -> None:
    text = (ROOT / name).read_text(encoding="utf-8")
    assert "pendiente de la corrida" not in text and "pending the v0.1 release run" not in text
    for report in ("v0.1.md", "v0.1-run2.md", "v0.1-run3.md", "v0.1-run4.md"):
        assert f"evals/reports/{report}" in text
        assert (ROOT / "evals" / "reports" / report).is_file()


@pytest.mark.parametrize("name", README)
def test_readme_names_the_test_admin_url_and_decision_log(name: str) -> None:
    text = (ROOT / name).read_text(encoding="utf-8")
    assert "DALE_TEST_ADMIN_URL" in text
    assert "openspec/changes/v01-core/decision-log.md" in text
