"""Command-line interface."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

from . import __version__
from .audit import VERDICT_LABELS, Audit, run_audit
from .calibration import DEFAULT_BINS, load_decisions, summarize
from .calib_report import render_calib_html, render_calib_markdown
from .code_scan import CodeScan, scan_code
from .migrate import apply_patch
from .migrate import generate as generate_migration
from .parsers import FORMATS
from .pricing import DEFAULT_DIVISOR, VENDOR_CLAIM_DIVISOR
from .report import render_markdown
from .report_html import render_html
from .selfcheck import run_selfcheck

LOG_SUFFIXES = ("*.jsonl", "*.ndjson", "*.json", "*.csv", "*.tsv")
DEFAULT_REPORT = "jev-audit-report.md"
DEFAULT_HTML = "jev-audit-dashboard.html"
DEFAULT_CALIB_REPORT = "calibration-report.md"
DEFAULT_CALIB_HTML = "calibration-dashboard.html"


def _fixtures_dir():
    from importlib.resources import files

    return Path(str(files("should_i_jev").joinpath("fixtures")))


def _demo_paths() -> List[Path]:
    root = _fixtures_dir()
    return sorted(Path(str(p)) for pattern in LOG_SUFFIXES for p in root.glob(pattern))


def _sample_code_dir() -> Path:
    return _fixtures_dir() / "sample_code"


def _expand(inputs: List[str]) -> List[Path]:
    paths: List[Path] = []
    for raw in inputs:
        p = Path(raw)
        if p.is_dir():
            found = [f for pattern in LOG_SUFFIXES for f in sorted(p.glob(pattern))]
            if not found:
                print(f"warning: no log files found in directory {p}", file=sys.stderr)
            paths.extend(found)
        else:
            paths.append(p)
    return paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="should-i-jev",
        description=(
            "Scan LLM usage logs for decision-shaped calls and estimate what moving "
            "them to JEV would save. Runs fully locally; nothing is uploaded."
        ),
    )
    parser.add_argument("inputs", nargs="*", help="log files or directories (JSONL/JSON/CSV/TSV)")
    parser.add_argument("--demo", action="store_true", help="run on the bundled sample logs and sample code")
    parser.add_argument(
        "--scan-code", action="append", default=None, metavar="PATH",
        help="also statically scan a codebase for decision-shaped LLM call sites (repeatable)",
    )
    parser.add_argument(
        "--html", nargs="?", const=DEFAULT_HTML, default=None, metavar="FILE",
        help=f"also write a self-contained HTML dashboard (default file: {DEFAULT_HTML})",
    )
    parser.add_argument(
        "--jev-selfcheck", action="store_true",
        help="ask Jev which calls/sites should move to Jev (offline stand-in unless "
        "--jev-base-url / JEV_BASE_URL is set)",
    )
    parser.add_argument(
        "--jev-base-url", default=None, metavar="URL",
        help="Jev API base URL for the self-check (env: JEV_BASE_URL)",
    )
    parser.add_argument(
        "--jev-api-key", default=None, metavar="KEY",
        help="Jev API bearer key for the self-check (env: JEV_API_KEY)",
    )
    parser.add_argument(
        "--jev-mock", action="store_true",
        help="force the offline stand-in backend for the self-check",
    )
    parser.add_argument(
        "--format", default="auto", choices=FORMATS,
        help="force a parser instead of auto-detect (default: auto)",
    )
    parser.add_argument("--report", default=DEFAULT_REPORT, help=f"markdown report path (default: {DEFAULT_REPORT})")
    parser.add_argument("--min-score", type=float, default=0.60, help="score threshold for 'likely' (default: 0.60)")
    parser.add_argument("--maybe-threshold", type=float, default=0.35, help="score threshold for 'maybe' (default: 0.35)")
    parser.add_argument("--top", type=int, default=25, help="how many top candidates to list (default: 25)")
    parser.add_argument("--no-redact", action="store_true", help="do not redact excerpts in the report")
    parser.add_argument("--price-file", type=Path, default=None, help="JSON of {model: [input, output]} USD per 1M tokens")
    parser.add_argument("--jev-divisor", type=int, default=DEFAULT_DIVISOR, help="conservative JEV cost divisor (default: 100)")
    parser.add_argument(
        "--jev-divisor-optimistic", type=int, default=VENDOR_CLAIM_DIVISOR,
        help="optimistic JEV cost divisor (default: 400, the vendor claim)",
    )
    parser.add_argument("--version", action="version", version=f"should-i-jev {__version__}")
    return parser


def _fmt_money(x: float) -> str:
    return f"${x:,.2f}"


def _print_summary(audit, scan=None) -> None:
    counts = audit.counts()
    spend = audit.spend()
    savings = audit.savings()
    total = audit.total_calls
    total_spend = audit.total_spend

    def share(v):
        return f"{(counts[v] / total * 100 if total else 0):5.1f}%"

    print()
    if total:
        print(f"parsed {total} calls from {len(audit.files)} log file(s)")
        for v in ("likely", "maybe", "unlikely", "insufficient"):
            print(f"  {VERDICT_LABELS[v]:<18} {counts[v]:>5} calls  {share(v)}   {_fmt_money(spend[v]):>10}")
        if counts["insufficient"]:
            print("  (insufficient data = text-less usage-export rows; not included in savings)")
    if scan is not None:
        print(
            f"code scan: {scan.files_scanned} file(s) → {len(scan.findings)} LLM call sites "
            f"({scan.decision_shaped} decision-shaped)"
        )
    if not total and scan is None:
        return
    print()
    prov = audit.cost_provenance()
    print()
    print(f"  audited spend (these logs)   {_fmt_money(total_spend):>10}   [{prov['logged']} logged / {prov['estimated']} estimated]")
    print(f"  migratable spend             {_fmt_money(audit.migratable_spend):>10}")
    if total_spend:
        cons_pct = savings["conservative"] / total_spend * 100
        opt_pct = savings["vendor_claim"] / total_spend * 100
        print(
            f"  savings  conservative ÷{audit.divisor:<3}  {_fmt_money(savings['conservative']):>10}   ({cons_pct:.1f}% of audited spend)"
        )
        print(
            f"           vendor claim  ÷{audit.divisor_optimistic:<3}  {_fmt_money(savings['vendor_claim']):>10}   ({opt_pct:.1f}% of audited spend)"
        )
    print()


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "calibrate":
        return calibrate_main(argv[1:])
    if argv and argv[0] == "migrate":
        return migrate_main(argv[1:])
    if argv and argv[0] == "audit":
        argv = argv[1:]
    args = build_parser().parse_args(argv)

    if args.demo:
        paths = _demo_paths()
        code_roots = [_sample_code_dir()]
    else:
        if not args.inputs and not args.scan_code:
            build_parser().print_help()
            print("\nno inputs given — pass log files/directories and/or --scan-code PATH, or try --demo")
            return 2
        paths = _expand(args.inputs)
        code_roots = [Path(p) for p in (args.scan_code or [])]

    if not (0 < args.maybe_threshold <= args.min_score <= 1):
        print("error: require 0 < maybe-threshold <= min-score <= 1", file=sys.stderr)
        return 2

    readable: List[Path] = []
    for p in paths:
        if not p.is_file():
            print(f"warning: skipping missing file {p}", file=sys.stderr)
        else:
            readable.append(p)
    if not readable and not code_roots:
        print("error: no readable input files", file=sys.stderr)
        return 2

    if args.price_file is not None and not args.price_file.is_file():
        print(f"error: price file not found: {args.price_file}", file=sys.stderr)
        return 2

    scan = None
    for root in code_roots:
        if not root.exists():
            print(f"warning: skipping missing code path {root}", file=sys.stderr)
            continue
        sub = scan_code(root)
        if scan is None:
            scan = sub
        else:
            scan.files_scanned += sub.files_scanned
            scan.findings.extend(sub.findings)
            scan.errors += sub.errors
    if scan is not None:
        scan.findings.sort(key=lambda f: (-f.detail.score, f.path, f.line))

    audit = (
        run_audit(
            readable,
            fmt=args.format,
            likely_threshold=args.min_score,
            maybe_threshold=args.maybe_threshold,
            price_file=args.price_file,
            divisor=args.jev_divisor,
            divisor_optimistic=args.jev_divisor_optimistic,
        )
        if readable
        else Audit([], [], 0)
    )
    if not audit.pairs and (scan is None or not scan.findings):
        print("error: no parsable calls or code findings in the given inputs", file=sys.stderr)
        return 1

    selfcheck = None
    if args.jev_selfcheck:
        base_url = "mock" if args.jev_mock else args.jev_base_url
        selfcheck = run_selfcheck(scan=scan, audit=audit, base_url=base_url, api_key=args.jev_api_key)

    report_path = Path(args.report)
    report_path.write_text(
        render_markdown(
            audit, top_n=max(0, args.top), redact=not args.no_redact, scan=scan,
            selfcheck=selfcheck,
        ),
        encoding="utf-8",
    )

    html_path = None
    if args.html is not None:
        html_path = Path(args.html)
        html_path.write_text(
            render_html(audit, scan=scan, redact=not args.no_redact, selfcheck=selfcheck),
            encoding="utf-8",
        )

    _print_summary(audit, scan)
    if selfcheck is not None:
        backend = "mock" if selfcheck.mock else "live endpoint"
        print(
            f"  jev self-check     : {selfcheck.n} item(s) vs {backend} — "
            f"agreement {selfcheck.agreement:.0%}"
        )
    print(f"report → {report_path.resolve()}")
    if html_path is not None:
        print(f"dashboard → {html_path.resolve()}")
    return 0


# --------------------------------------------------------------------------- calibrate

def calibrate_main(argv) -> int:
    parser = argparse.ArgumentParser(
        prog="should-i-jev calibrate",
        description=(
            "Calibration metrics for decision models: ECE / MCE / Brier, reliability "
            "bins and risk-coverage (selective accuracy). Input: JSONL of "
            '{"p": 0.82, "correct": true, "model": "...", "question": "..."}.'
        ),
    )
    parser.add_argument("file", help="decision records (JSONL)")
    parser.add_argument("--baseline", default=None, help="second decision set to compare against")
    parser.add_argument("--report", default=DEFAULT_CALIB_REPORT, help=f"markdown report (default: {DEFAULT_CALIB_REPORT})")
    parser.add_argument(
        "--html", nargs="?", const=DEFAULT_CALIB_HTML, default=None, metavar="FILE",
        help=f"also write an HTML report with SVG charts (default: {DEFAULT_CALIB_HTML})",
    )
    parser.add_argument("--bins", type=int, default=DEFAULT_BINS, help="confidence bins (default: 10)")
    args = parser.parse_args(argv)

    if not (2 <= args.bins <= 50):
        print("error: --bins must be between 2 and 50", file=sys.stderr)
        return 2

    def _load(path, fallback_name):
        records, skipped = load_decisions(path)
        name = records[0].model if records and records[0].model != "unknown" else Path(path).stem
        return records, skipped, name

    try:
        records, skipped, name = _load(args.file, None)
    except OSError as exc:
        print(f"error: cannot read {args.file}: {exc}", file=sys.stderr)
        return 2
    if not records:
        print(f"error: no usable decision records in {args.file}", file=sys.stderr)
        return 1

    summaries = [{"name": name, "summary": summarize(records, args.bins)}]
    if args.baseline:
        try:
            base_records, base_skipped, base_name = _load(args.baseline, None)
        except OSError as exc:
            print(f"error: cannot read {args.baseline}: {exc}", file=sys.stderr)
            return 2
        if not base_records:
            print(f"error: no usable decision records in {args.baseline}", file=sys.stderr)
            return 1
        skipped += base_skipped
        if base_name == name:
            base_name += " (baseline)"
        summaries.append({"name": base_name, "summary": summarize(base_records, args.bins)})

    report_path = Path(args.report)
    report_path.write_text(render_calib_markdown(summaries, skipped=skipped), encoding="utf-8")

    html_path = None
    if args.html is not None:
        html_path = Path(args.html)
        html_path.write_text(render_calib_html(summaries, skipped=skipped), encoding="utf-8")

    print()
    for s in summaries:
        m = s["summary"]
        print(f"calibration: {s['name']} — {m['n']} decisions")
        print(
            f"  accuracy {m['accuracy']:.3f}   avg conf {m['avg_p']:.3f}   "
            f"ECE {m['ece']:.3f}   MCE {m['mce']:.3f}   Brier {m['brier']:.3f}"
        )
        cov = m["coverage"]
        print(
            f"  acc@90%cov {cov.get(0.9, 0):.3f}   acc@99%cov {cov.get(0.99, 0):.3f}"
        )
    print()
    print(f"report → {report_path.resolve()}")
    if html_path is not None:
        print(f"charts → {html_path.resolve()}")
    return 0


# --------------------------------------------------------------------------- migrate

def migrate_main(argv) -> int:
    parser = argparse.ArgumentParser(
        prog="should-i-jev migrate",
        description=(
            "Generate a reviewable migration changeset for decision-shaped LLM call "
            "sites: jev_maps.py sketches + MIGRATION.md + a git patch marking every "
            "site. --apply runs git apply and prints the PR commands."
        ),
    )
    parser.add_argument("--scan-code", required=True, metavar="PATH", help="codebase to scan")
    parser.add_argument("--out-dir", default="jev-migration", help="output directory (default: jev-migration)")
    parser.add_argument("--min-score", type=float, default=0.60, help="score cut for marked sites (default: 0.60)")
    parser.add_argument("--apply", action="store_true", help="git-apply the patch to the scanned tree")
    args = parser.parse_args(argv)

    root = Path(args.scan_code)
    if not root.exists():
        print(f"error: no such path: {root}", file=sys.stderr)
        return 2

    scan = scan_code(root)
    if not scan.findings:
        print(f"error: no LLM call sites found under {root}", file=sys.stderr)
        return 1

    out = generate_migration(scan, Path(args.out_dir), min_score=args.min_score)
    print()
    print(
        f"migration set: {scan.files_scanned} file(s) scanned → {len(scan.findings)} call site(s) "
        f"→ {out.sites} decision-shaped (score ≥ {args.min_score:.2f}) → {out.maps_n} Jev map(s)"
    )
    for f in out.files:
        print(f"  {f}")

    if args.apply:
        ok, err = apply_patch(out.patch, root)
        if not ok:
            print(f"error: git apply failed: {err}", file=sys.stderr)
            return 1
        print(f"\napplied {out.patch} to {root}")
        print("next steps:")
        print("  git checkout -b jev-migration && git add -A")
        print('  git commit -m "Mark decision-shaped LLM call sites and add Jev map sketches"')
        print("  git push -u origin jev-migration")
        print(f"  gh pr create --title 'jev-migration' --body-file {out.out_dir / 'MIGRATION.md'}")
    else:
        print(f"\napply with: git apply {out.patch}   (or re-run with --apply)")
    return 0
