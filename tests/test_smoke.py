"""Smoke tests for COLDFORGE — import the core, run it on the demo, assert real behavior."""
import json
import os
import subprocess
import sys

import pytest

from coldforge import (
    TOOL_NAME,
    TOOL_VERSION,
    load_contacts,
    render_all,
    render_template,
    lint_text,
    find_placeholders,
    Contact,
)
from coldforge.cli import main

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
DEMO = os.path.join(ROOT, "demos", "01-basic")
BODY = os.path.join(DEMO, "body.txt")
CONTACTS = os.path.join(DEMO, "contacts.csv")


def _body_text():
    with open(BODY, encoding="utf-8") as fh:
        return fh.read()


def test_metadata():
    assert TOOL_NAME == "coldforge"
    assert TOOL_VERSION.count(".") == 2


def test_load_contacts():
    contacts = load_contacts(CONTACTS)
    assert len(contacts) == 4
    assert contacts[0].email == "alice@acme.io"
    assert contacts[0].get("company") == "Acme Robotics"


def test_load_contacts_requires_email(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("name,company\nx,y\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_contacts(str(bad))


def test_find_placeholders():
    ph = find_placeholders(_body_text())
    assert "first_name" in ph
    assert "company" in ph
    assert "role" in ph


def test_render_fills_and_fallbacks():
    c = Contact(email="x@y.com", fields={"first_name": "Sam", "company": "Z Inc"})
    out, missing = render_template(_body_text(), c)
    assert "Hi Sam," in out
    assert "Z Inc" in out
    # role has a |there fallback, so it is NOT missing and renders the fallback
    assert "as there" in out
    assert missing == []
    # no leftover placeholders
    assert "{{" not in out


def test_render_reports_missing_required_field():
    results = render_all(_body_text(), load_contacts(CONTACTS))
    by_email = {r.email: r for r in results}
    dana = by_email["dana@example.com"]
    assert "first_name" in dana.missing
    # role is NOT missing because it has a fallback
    assert "role" not in dana.missing


def test_clean_template_scores_low():
    results = render_all(_body_text(), load_contacts(CONTACTS))
    alice = next(r for r in results if r.email == "alice@acme.io")
    report = lint_text(alice.body, template=_body_text())
    assert report.score <= 25
    assert report.grade in ("A", "B")


def test_spammy_text_scores_high_and_flags_rules():
    spam = "ACT NOW!! 100% FREE risk-free guaranteed cash bonus click here now!!!"
    report = lint_text(spam)
    assert report.score >= 45
    assert report.grade in ("D", "F")
    rules = {f.rule for f in report.findings}
    assert "spam_words" in rules
    assert "all_caps" in rules
    assert "exclamation" in rules


def test_unresolved_placeholder_is_flagged():
    report = lint_text("Hi {{first_name}}, here is a reasonably long sentence "
                       "about your company and the value we provide to teams.")
    rules = {f.rule for f in report.findings}
    assert "unresolved_placeholder" in rules


def test_cli_render_table_exit_zero(capsys):
    rc = main(["render", "-t", BODY, "-c", CONTACTS])
    out = capsys.readouterr().out
    assert "alice@acme.io" in out
    assert rc == 0  # nothing over default max-score


def test_cli_render_strict_missing_exit_three():
    rc = main(["render", "-t", BODY, "-c", CONTACTS, "--strict"])
    assert rc == 3  # dana is missing first_name


def test_cli_render_json_shape(capsys):
    rc = main(["--format", "json", "render", "-t", BODY, "-c", CONTACTS])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert data["tool"] == "coldforge"
    assert data["summary"]["contacts"] == 4
    assert len(data["results"]) == 4
    assert "spam" in data["results"][0]


def test_cli_lint_threshold_exit_two(tmp_path, capsys):
    spam = tmp_path / "spam.txt"
    spam.write_text("ACT NOW!! 100% FREE risk-free guaranteed cash click here!!!",
                    encoding="utf-8")
    rc = main(["lint", "-t", str(spam), "--max-score", "25"])
    assert rc == 2


def test_module_entrypoint_version():
    proc = subprocess.run(
        [sys.executable, "-m", "coldforge", "--version"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert proc.returncode == 0
    assert "coldforge" in proc.stdout
