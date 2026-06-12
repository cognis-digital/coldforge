"""COLDFORGE command-line interface.

Subcommands
-----------
  render   Render a template against a contacts CSV and lint each message.
  lint     Lint a single template/text file (no CSV needed).

Examples
--------
  # Render + lint every contact, pretty table
  coldforge render --template body.txt --contacts contacts.csv

  # CI gate: fail (exit 2) if any message scores above 25
  coldforge render -t body.txt -c contacts.csv --max-score 25 --format json

  # Just lint a draft
  coldforge lint --template body.txt

Exit codes
----------
  0  success, nothing over threshold
  2  one or more messages exceeded --max-score (CI gate failure)
  3  rendering had missing required fields and --strict was set
  1  usage / IO error
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from . import TOOL_NAME, TOOL_VERSION
from .core import (
    load_contacts,
    render_all,
    lint_text,
    find_placeholders,
    SpamReport,
)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _print_table(rows: List[dict]) -> None:
    if not rows:
        print("(no contacts)")
        return
    cols = ["email", "score", "grade", "missing", "top_issue"]
    widths = {c: len(c) for c in cols}
    for r in rows:
        for c in cols:
            widths[c] = max(widths[c], len(str(r.get(c, ""))))
    header = "  ".join(c.ljust(widths[c]) for c in cols)
    print(header)
    print("  ".join("-" * widths[c] for c in cols))
    for r in rows:
        print("  ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols))


def _top_issue(report: SpamReport) -> str:
    if not report.findings:
        return "-"
    worst = max(report.findings, key=lambda f: f.penalty)
    return f"{worst.rule}(+{worst.penalty})"


def _cmd_render(args: argparse.Namespace) -> int:
    body = _read(args.template)
    subject = _read(args.subject) if args.subject else ""
    contacts = load_contacts(args.contacts)
    results = render_all(body, contacts, subject_template=subject)

    rows = []
    payload = []
    over = 0
    had_missing = False
    for res in results:
        report = lint_text(res.body, template=body)
        if res.missing:
            had_missing = True
        if report.score > args.max_score:
            over += 1
        rows.append({
            "email": res.email,
            "score": report.score,
            "grade": report.grade,
            "missing": ",".join(res.missing) or "-",
            "top_issue": _top_issue(report),
        })
        payload.append({
            "email": res.email,
            "subject": res.subject,
            "body": res.body,
            "missing": res.missing,
            "spam": report.to_dict(),
        })

    if args.format == "json":
        print(json.dumps({
            "tool": TOOL_NAME,
            "version": TOOL_VERSION,
            "max_score": args.max_score,
            "placeholders": find_placeholders(body),
            "results": payload,
            "summary": {
                "contacts": len(results),
                "over_threshold": over,
                "with_missing_fields": sum(1 for r in results if r.missing),
            },
        }, indent=2))
    else:
        _print_table(rows)
        print()
        print(f"{len(results)} contact(s); {over} over score {args.max_score}; "
              f"{sum(1 for r in results if r.missing)} with missing fields.")

    if args.strict and had_missing:
        return 3
    if over:
        return 2
    return 0


def _cmd_lint(args: argparse.Namespace) -> int:
    text = _read(args.template)
    report = lint_text(text, template=text)

    if args.format == "json":
        print(json.dumps({
            "tool": TOOL_NAME,
            "version": TOOL_VERSION,
            "max_score": args.max_score,
            "spam": report.to_dict(),
        }, indent=2))
    else:
        print(f"score: {report.score}/100  grade: {report.grade}")
        if not report.findings:
            print("  no issues — looks clean")
        for f in report.findings:
            extra = ("  → " + ", ".join(f.matches)) if f.matches else ""
            print(f"  [+{f.penalty:>2}] {f.rule}: {f.message}{extra}")

    return 2 if report.score > args.max_score else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description="Outreach-as-code: render personalized cold emails from a "
                    "template + contacts CSV, with a CI spam linter.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--version", action="version",
                   version=f"{TOOL_NAME} {TOOL_VERSION}")
    p.add_argument("--format", choices=["table", "json"], default="table",
                   help="output format (default: table)")

    sub = p.add_subparsers(dest="command")

    pr = sub.add_parser("render", help="render template over a contacts CSV + lint")
    pr.add_argument("-t", "--template", required=True, help="body template file")
    pr.add_argument("-c", "--contacts", required=True, help="contacts CSV file")
    pr.add_argument("-s", "--subject", help="optional subject template file")
    pr.add_argument("--max-score", type=int, default=25,
                    help="fail (exit 2) if any message scores above this (default 25)")
    pr.add_argument("--strict", action="store_true",
                    help="exit 3 if any contact is missing a required field")
    pr.set_defaults(func=_cmd_render)

    pl = sub.add_parser("lint", help="lint a single template/draft file")
    pl.add_argument("-t", "--template", required=True, help="template/text file")
    pl.add_argument("--max-score", type=int, default=25,
                    help="fail (exit 2) if score above this (default 25)")
    pl.set_defaults(func=_cmd_lint)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    try:
        return args.func(args)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
