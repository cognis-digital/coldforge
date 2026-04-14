"""Core engine for COLDFORGE.

Two jobs, both done for real:

1. Template rendering: ``{{field}}`` placeholders are filled from a contacts CSV
   row. Supports ``{{field|fallback}}`` default values and reports any row that
   is missing data for a required placeholder.

2. Spam linting: a deterministic, rule-based scorer that flags the things that
   actually get cold email flagged — spam-trigger words, ALL CAPS, exclamation
   spam, link/image heuristics, missing personalization, etc. Produces a 0-100
   score (higher = spammier) plus per-finding penalties so a CI gate can fail.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Contact:
    """One row from the contacts CSV. ``email`` is required; everything else
    is arbitrary template data."""

    email: str
    fields: Dict[str, str] = field(default_factory=dict)

    def get(self, key: str, default: str = "") -> str:
        if key == "email":
            return self.email
        return self.fields.get(key, default)


@dataclass
class RenderResult:
    email: str
    subject: str
    body: str
    missing: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SpamFinding:
    rule: str
    message: str
    penalty: int
    matches: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SpamReport:
    score: int          # 0-100, higher = spammier
    grade: str          # A / B / C / D / F
    findings: List[SpamFinding] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "grade": self.grade,
            "findings": [f.to_dict() for f in self.findings],
        }


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------


def load_contacts(path: str) -> List[Contact]:
    """Load contacts from a CSV file. Requires an ``email`` column."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError("CSV has no header row")
        headers = [h.strip() for h in reader.fieldnames]
        if "email" not in headers:
            raise ValueError(
                "contacts CSV must have an 'email' column; got: "
                + ", ".join(headers)
            )
        contacts: List[Contact] = []
        for raw in reader:
            row = {(k.strip() if k else k): (v.strip() if v else "")
                   for k, v in raw.items()}
            email = row.get("email", "")
            if not email:
                continue
            fields = {k: v for k, v in row.items() if k and k != "email"}
            contacts.append(Contact(email=email, fields=fields))
    return contacts


# ---------------------------------------------------------------------------
# Templating
# ---------------------------------------------------------------------------

_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*(?:\|([^}]*))?\}\}")


def find_placeholders(template: str) -> List[str]:
    """Return the distinct field names referenced in a template."""
    seen: List[str] = []
    for m in _PLACEHOLDER.finditer(template):
        name = m.group(1)
        if name not in seen:
            seen.append(name)
    return seen


def missing_fields(template: str, contact: Contact) -> List[str]:
    """Placeholders with no value AND no fallback for this contact."""
    missing: List[str] = []
    for m in _PLACEHOLDER.finditer(template):
        name, fallback = m.group(1), m.group(2)
        value = contact.get(name, "")
        if not value and fallback is None and name not in missing:
            missing.append(name)
    return missing


def render_template(template: str, contact: Contact) -> Tuple[str, List[str]]:
    """Render a single template for a contact.

    Returns (rendered_text, missing_field_names). Missing fields with a
    ``|fallback`` use the fallback; missing without fallback render empty
    and are reported.
    """
    missing: List[str] = []

    def repl(m: re.Match) -> str:
        name, fallback = m.group(1), m.group(2)
        value = contact.get(name, "")
        if value:
            return value
        if fallback is not None:
            return fallback.strip()
        if name not in missing:
            missing.append(name)
        return ""

    return _PLACEHOLDER.sub(repl, template), missing


def render_all(
    body_template: str,
    contacts: Iterable[Contact],
    subject_template: str = "",
) -> List[RenderResult]:
    """Render body (and optional subject) for every contact."""
    results: List[RenderResult] = []
    for c in contacts:
        body, miss_b = render_template(body_template, c)
        subject, miss_s = ("", [])
        if subject_template:
            subject, miss_s = render_template(subject_template, c)
        missing = list(dict.fromkeys(miss_s + miss_b))
        results.append(
            RenderResult(email=c.email, subject=subject, body=body, missing=missing)
        )
    return results


# ---------------------------------------------------------------------------
# Spam linting
# ---------------------------------------------------------------------------

# Words/phrases that classifiers and humans treat as cold-email spam signals.
SPAM_WORDS = [
    "act now", "apply now", "buy now", "call now", "click here", "click below",
    "order now", "sign up free", "100% free", "100% satisfied", "risk free",
    "risk-free", "no obligation", "no cost", "no fees", "no catch",
    "limited time", "limited offer", "act immediately", "don't delete",
    "this isn't spam", "this is not spam", "not spam", "guarantee",
    "guaranteed", "cash bonus", "earn money", "earn extra cash",
    "make money", "double your", "extra income", "free money", "free gift",
    "free trial", "free access", "winner", "you've been selected",
    "you have been selected", "congratulations", "urgent", "important information",
    "dear friend", "once in a lifetime", "miracle", "amazing",
    "increase sales", "increase traffic", "best price", "lowest price",
    "special promotion", "while supplies last", "unsubscribe",
    "crypto", "bitcoin", "investment opportunity", "pre-approved",
    "this won't last", "satisfaction guaranteed",
]

_WORD_RE = re.compile(r"[A-Za-z']+")
_URL_RE = re.compile(r"https?://[^\s)>\]]+", re.IGNORECASE)
_PLACEHOLDER_LEFTOVER = re.compile(r"\{\{[^}]*\}\}")
_GREETING_FIELDS = ("first_name", "firstname", "name", "company")


def _grade(score: int) -> str:
    if score <= 10:
        return "A"
    if score <= 25:
        return "B"
    if score <= 45:
        return "C"
    if score <= 70:
        return "D"
    return "F"


def lint_text(text: str, template: Optional[str] = None) -> SpamReport:
    """Score a piece of outreach text for spamminess (0=clean, 100=very spammy).

    If ``template`` is given, COLDFORGE additionally checks whether the message
    is personalized (uses a known greeting field) and whether unresolved
    ``{{placeholders}}`` leaked into the rendered output.
    """
    findings: List[SpamFinding] = []
    score = 0
    lower = text.lower()

    # 1. Spam-trigger words/phrases.
    hits: List[str] = []
    for phrase in SPAM_WORDS:
        if phrase in lower:
            hits.append(phrase)
    if hits:
        penalty = min(40, 6 * len(hits))
        findings.append(SpamFinding(
            rule="spam_words",
            message=f"{len(hits)} spam-trigger phrase(s) found",
            penalty=penalty,
            matches=hits,
        ))
        score += penalty

    # 2. ALL CAPS words (length >= 3, exclude common acronyms by length only).
    words = _WORD_RE.findall(text)
    caps = [w for w in words if len(w) >= 4 and w.isupper()]
    if caps:
        penalty = min(20, 4 * len(caps))
        findings.append(SpamFinding(
            rule="all_caps",
            message=f"{len(caps)} ALL-CAPS word(s) (shouty)",
            penalty=penalty,
            matches=caps[:10],
        ))
        score += penalty

    # 3. Exclamation overload.
    excl = text.count("!")
    if excl >= 2:
        penalty = min(15, 3 * excl)
        findings.append(SpamFinding(
            rule="exclamation",
            message=f"{excl} exclamation marks",
            penalty=penalty,
            matches=[],
        ))
        score += penalty

    # 4. Too many links.
    urls = _URL_RE.findall(text)
    if len(urls) > 2:
        penalty = min(20, 6 * (len(urls) - 2))
        findings.append(SpamFinding(
            rule="too_many_links",
            message=f"{len(urls)} links (keep cold email to <=2)",
            penalty=penalty,
            matches=urls[:10],
        ))
        score += penalty

    # 5. Money/currency symbol spam.
    money = re.findall(r"\$\s?\d", text)
    if len(money) >= 2:
        penalty = min(12, 4 * len(money))
        findings.append(SpamFinding(
            rule="money_amounts",
            message=f"{len(money)} dollar amounts",
            penalty=penalty,
            matches=[],
        ))
        score += penalty

    # 6. Length: too short reads like spam, too long gets skimmed/flagged.
    n_words = len(words)
    if n_words < 20:
        findings.append(SpamFinding(
            rule="too_short",
            message=f"only {n_words} words — too thin to feel personal",
            penalty=8,
            matches=[],
        ))
        score += 8
    elif n_words > 200:
        findings.append(SpamFinding(
            rule="too_long",
            message=f"{n_words} words — cold email should be ~50-150",
            penalty=8,
            matches=[],
        ))
        score += 8

    # 7. Leftover unresolved template placeholders.
    leftover = _PLACEHOLDER_LEFTOVER.findall(text)
    if leftover:
        penalty = min(30, 10 * len(leftover))
        findings.append(SpamFinding(
            rule="unresolved_placeholder",
            message=f"{len(leftover)} unresolved {{{{placeholder}}}}",
            penalty=penalty,
            matches=leftover[:10],
        ))
        score += penalty

    # 8. Personalization check (only meaningful when we know the template).
    if template is not None:
        used = set(find_placeholders(template))
        if not (used & set(_GREETING_FIELDS)):
            findings.append(SpamFinding(
                rule="no_personalization",
                message="template uses no greeting/name/company field",
                penalty=12,
                matches=[],
            ))
            score += 12

    score = max(0, min(100, score))
    return SpamReport(score=score, grade=_grade(score), findings=findings)
