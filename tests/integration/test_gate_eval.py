"""The CI evaluation command must reject regressions and invalid fixtures."""

import json

import pytest
from typer.testing import CliRunner

from predoc_pipeline.cli import app

POSITIVE = {
    "text": "The department is hiring a full-time research assistant in economics. "
            "Applications are invited until 1 March 2027.",
    "title": "Research Assistant",
    "expect_pass": True,
}
NEGATIVE = {
    "text": "The school invites applications for a tenure-track assistant professor "
            "position in economics. Apply by 1 November.",
    "title": "Assistant Professor of Economics",
    "expect_pass": False,
}


def _evaluate(tmp_path, records):
    fixtures = tmp_path / "fixtures.jsonl"
    fixtures.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
    return CliRunner().invoke(app, ["eval", "--fixtures", str(fixtures)])


@pytest.mark.parametrize("fixture", [POSITIVE, NEGATIVE])
def test_misclassified_fixture_fails_the_command(tmp_path, fixture):
    result = _evaluate(tmp_path, [{**fixture, "expect_pass": not fixture["expect_pass"]}])
    assert result.exit_code == 1, result.output
    assert "1 fixture(s) did not match" in result.output


def test_reports_separate_confusion_matrices_for_each_path(tmp_path):
    result = _evaluate(tmp_path, [POSITIVE, {**NEGATIVE, "known_vacancy": True}])
    assert result.exit_code == 0, result.output
    assert "board: n=1 tp=0 fp=0 tn=1 fn=0" in result.output
    assert "strict: n=1 tp=1 fp=0 tn=0 fn=0" in result.output


def test_fixture_url_uses_the_production_non_vacancy_gate(tmp_path):
    result = _evaluate(tmp_path, [{
        **POSITIVE,
        "url": "https://example.org/people/faculty/profile",
        "expect_pass": False,
    }])
    assert result.exit_code == 0, result.output
    assert "tn=1 fn=0" in result.output


@pytest.mark.parametrize("contents", ["", "\n# no labelled examples\n"])
def test_empty_fixture_set_is_not_a_successful_evaluation(tmp_path, contents):
    fixtures = tmp_path / "empty.jsonl"
    fixtures.write_text(contents, encoding="utf-8")
    result = CliRunner().invoke(app, ["eval", "--fixtures", str(fixtures)])
    assert result.exit_code == 1, result.output
    assert "no labelled fixtures" in result.output


@pytest.mark.parametrize("field", ["expect_pass", "known_vacancy", "allow_phd", "allow_postdoc"])
def test_string_false_is_rejected_instead_of_evaluated_as_true(tmp_path, field):
    result = _evaluate(tmp_path, [{**POSITIVE, field: "false"}])
    assert result.exit_code == 1, result.output
    assert f"{field} must be a JSON boolean" in result.output
    assert "line 1" in result.output


@pytest.mark.parametrize("record", [
    [], None, {}, {**POSITIVE, "text": None}, {**POSITIVE, "url": False},
])
def test_invalid_fixture_shape_has_a_useful_error(tmp_path, record):
    result = _evaluate(tmp_path, [record])
    assert result.exit_code == 1, result.output
    assert "invalid fixture at line 1" in result.output


def test_invalid_json_reports_its_source_line(tmp_path):
    fixtures = tmp_path / "broken.jsonl"
    fixtures.write_text('# comment\n{"text":\n', encoding="utf-8")
    result = CliRunner().invoke(app, ["eval", "--fixtures", str(fixtures)])
    assert result.exit_code == 1, result.output
    assert "invalid fixture at line 2" in result.output


def test_fixture_path_must_be_a_readable_file(tmp_path):
    result = CliRunner().invoke(app, ["eval", "--fixtures", str(tmp_path)])
    assert result.exit_code == 1, result.output
    assert "could not read fixtures" in result.output
