# Release notes

## v0.3.0 — the full audit → calibrate → migrate loop

The tool now covers the whole "should I move this to Jev?" workflow:

- **`should-i-jev calibrate`** — calibration harness for decision models:
  ECE / MCE / Brier, reliability bins, and risk–coverage (selective accuracy:
  how accurate would the model be if it only answered its most-confident X%
  and abstained — Noul — on the rest?). Baseline comparison, per-question-type
  breakdown, markdown + HTML reports with inline-SVG reliability diagrams and
  risk–coverage curves.
- **`--jev-selfcheck`** — "use Jev to find where Jev belongs": every flagged
  call site becomes a typed Choice question asked to a Jev endpoint, with an
  agreement score against the heuristics. Offline stand-in backend by default;
  real endpoint via `--jev-base-url` / `JEV_API_KEY`.
- **`should-i-jev migrate`** — one-click migration PR: generates
  `jev_maps.py` typed-question sketches, a per-site `MIGRATION.md`, and a git
  patch marking every decision-shaped call site with `TODO(jev-migrate)`.
  `--apply` runs `git apply` and prints the branch / `gh pr create` sequence.

Also: shared map builder for logs + code, README screenshots, 87 tests,
still zero dependencies.

## v0.2.0 — code scan + HTML dashboard

- Static code scan (`--scan-code`): Python via AST, JS/TS via patterns —
  find decision-shaped LLM call sites in the repo, not just in logs.
- Self-contained HTML dashboard (`--html`): stat cards, verdict/cost bars,
  sortable & filterable candidate table, code call sites, JEV map sketches.
  Inline CSS/JS, no CDN, works offline.

## v0.1.0 — the auditor

- Parse LiteLLM / Langfuse / OpenAI / Anthropic usage exports (JSONL/JSON/CSV/TSV).
- Six decision-shape heuristics with corpus-level output-diversity signal.
- Dated price table + divisor-scenario savings (conservative ÷100 headline,
  vendor-claimed ÷400 shown alongside); text-less usage rows reported as
  *insufficient data* instead of guessed at.
- Markdown audit report with JEV map sketches, prompt redaction, fully local.
