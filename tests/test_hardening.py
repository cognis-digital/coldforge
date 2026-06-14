"""Hardening tests — edge cases, bad input, and error paths for COLDFORGE."""
from __future__ import annotations

import pytest

from coldforge.cli import main
from coldforge.core import (
    load_contacts,
    lint_text,
    render_all,
    scan,
    to_json,
    TOOL_NAME,
    TOOL_VERSION,
)

# ---------------------------------------------------------------------------
# CLI: missing / unreadable files -> exit 1 + stderr message
# ---------------------------------------------------------------------------


def test_cli_render_missing_template_exits_one(capsys, tmp_path):
    contacts = tmp_path / "c.csv"
    contacts.write_text("email\ntest@example.com\n", encoding="utf-8")
    rc = main(["render", "-t", str(tmp_path / "no_such_file.txt"), "-c", str(contacts)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "error:" in err.lower()


def test_cli_render_missing_contacts_exits_one(capsys, tmp_path):
    tmpl = tmp_path / "body.txt"
    tmpl.write_text("Hi {{first_name}}, welcome.", encoding="utf-8")
    rc = main(["render", "-t", str(tmpl), "-c", str(tmp_path / "no_such.csv")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "error:" in err.lower()


def test_cli_lint_missing_file_exits_one(capsys, tmp_path):
    rc = main(["lint", "-t", str(tmp_path / "ghost.txt")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "error:" in err.lower()


# ---------------------------------------------------------------------------
# CLI: --max-score out of range -> exit 1
# ---------------------------------------------------------------------------


def test_cli_max_score_too_high_exits_one(capsys, tmp_path):
    tmpl = tmp_path / "body.txt"
    tmpl.write_text("Hi there, just reaching out.", encoding="utf-8")
    rc = main(["lint", "-t", str(tmpl), "--max-score", "200"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "max-score" in err


def test_cli_max_score_negative_exits_one(capsys, tmp_path):
    tmpl = tmp_path / "body.txt"
    tmpl.write_text("Hi there, just reaching out.", encoding="utf-8")
    rc = main(["lint", "-t", str(tmpl), "--max-score", "-5"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "max-score" in err


# ---------------------------------------------------------------------------
# core: CSV edge cases
# ---------------------------------------------------------------------------


def test_load_contacts_empty_csv_body(tmp_path):
    """CSV with header but no data rows returns empty list (not an error)."""
    f = tmp_path / "empty.csv"
    f.write_text("email,first_name\n", encoding="utf-8")
    contacts = load_contacts(str(f))
    assert contacts == []


def test_load_contacts_skips_blank_email_rows(tmp_path):
    f = tmp_path / "blanks.csv"
    f.write_text(
        "email,first_name\n"
        "alice@example.com,Alice\n"
        ",Bob\n"
        "charlie@example.com,Charlie\n",
        encoding="utf-8",
    )
    contacts = load_contacts(str(f))
    assert len(contacts) == 2
    assert contacts[0].email == "alice@example.com"
    assert contacts[1].email == "charlie@example.com"


def test_load_contacts_no_email_column_raises(tmp_path):
    f = tmp_path / "noemail.csv"
    f.write_text("name,company\nAlice,Acme\n", encoding="utf-8")
    with pytest.raises(ValueError, match="email"):
        load_contacts(str(f))


# ---------------------------------------------------------------------------
# core: lint_text edge cases
# ---------------------------------------------------------------------------


def test_lint_empty_string():
    """lint_text on empty string should return a SpamReport, not crash."""
    report = lint_text("")
    assert report.score >= 0
    assert report.grade in ("A", "B", "C", "D", "F")


def test_lint_wrong_type_raises():
    with pytest.raises(TypeError):
        lint_text(None)  # type: ignore[arg-type]


def test_lint_score_clamped_to_100():
    """Piling on many spam signals must never exceed 100."""
    very_spammy = (
        "ACT NOW!! 100% FREE GUARANTEED CASH BONUS WIN PRIZE!!! "
        "CLICK HERE CLICK BELOW ORDER NOW SIGN UP FREE!!! "
        "http://spam1.com http://spam2.com http://spam3.com http://spam4.com "
        "$100 $200 $300 $400 dear friend earn money make money double your income!!!"
    )
    report = lint_text(very_spammy)
    assert report.score <= 100


# ---------------------------------------------------------------------------
# core: render_all with empty contacts
# ---------------------------------------------------------------------------


def test_render_all_empty_contacts():
    results = render_all("Hi {{first_name}},", [])
    assert results == []


# ---------------------------------------------------------------------------
# core: scan / to_json (mcp_server helpers)
# ---------------------------------------------------------------------------


def test_scan_returns_list():
    result = scan("hello world, this is a test message about our product.")
    assert isinstance(result, list)
    assert len(result) >= 1
    assert "score" in result[0]


def test_to_json_round_trips():
    findings = scan("quick test message")
    serialised = to_json(findings)
    import json
    parsed = json.loads(serialised)
    assert isinstance(parsed, list)


# ---------------------------------------------------------------------------
# core: TOOL_NAME / TOOL_VERSION exported from core
# ---------------------------------------------------------------------------


def test_core_exports_tool_identity():
    assert TOOL_NAME == "coldforge"
    assert TOOL_VERSION.count(".") == 2
