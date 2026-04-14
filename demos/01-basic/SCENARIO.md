# Demo 01 — Basic render + spam lint

This demo shows COLDFORGE doing both of its jobs against real input:

1. **Render** a personalized cold email body from `body.txt` for each contact
   in `contacts.csv`, filling `{{first_name}}`, `{{company}}`, and using a
   `{{role|there}}` fallback.
2. **Lint** each rendered message and assign a 0-100 spam score so it can be
   used as a CI gate.

## Files

- `contacts.csv` — 4 contacts. One row (`dana@example.com`) intentionally
  leaves `first_name` blank to exercise the missing-field report.
- `body.txt` — a clean, personalized template that should score well (grade A/B).

## Run it

```bash
python -m coldforge render -t demos/01-basic/body.txt -c demos/01-basic/contacts.csv
```

or as JSON for piping / CI:

```bash
python -m coldforge render -t demos/01-basic/body.txt -c demos/01-basic/contacts.csv \
    --format json --max-score 25
```

## Expected result

- 4 contacts rendered.
- Each message is personalized (uses `{{first_name}}`/`{{company}}`) and short
  but substantial, so spam scores are **low** (grade A or B) — nothing exceeds
  the default `--max-score 25`, so the command exits **0**.
- The `dana@example.com` row reports `first_name` under **missing** (it renders
  empty because there is no fallback). With `--strict`, that makes the command
  exit **3**.

To see the linter bite, try a spammy template:

```bash
printf 'ACT NOW!! 100%% FREE risk-free guaranteed cash bonus click here!!!' > /tmp/spam.txt
python -m coldforge lint -t /tmp/spam.txt   # high score, exit 2
```
