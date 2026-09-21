"""Self-contained HTML dashboard — one file, inline CSS/JS, zero external assets.

Everything (numbers, prompt excerpts, sketches) is rendered into the file; the
dashboard works offline and makes no network requests.
"""
from __future__ import annotations

import html as _html
from typing import List, Optional

from . import __version__
from .audit import VERDICT_LABELS, VERDICT_ORDER, Audit
from .code_scan import CodeScan
from .heuristics import WEIGHTS
from .report import redact_text

_VERDICT_COLORS = {
    "likely": "#059669",
    "maybe": "#d97706",
    "unlikely": "#64748b",
    "insufficient": "#9ca3af",
}

_CSS = """
:root{--ink:#0f172a;--muted:#64748b;--line:#e2e8f0;--bg:#f8fafc;--card:#ffffff;--accent:#4f46e5}
*{box-sizing:border-box}
body{margin:0;font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:var(--ink);background:var(--bg)}
.wrap{max-width:1100px;margin:0 auto;padding:28px 20px 60px}
header h1{margin:0 0 4px;font-size:26px;letter-spacing:-.02em}
.meta{color:var(--muted);font-size:13px;margin-bottom:22px}
.meta .chip{display:inline-block;background:#eef2ff;color:#3730a3;border-radius:99px;padding:1px 10px;margin-right:6px;font-weight:600}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin:18px 0 26px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.card .label{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.card .value{font-size:24px;font-weight:700;margin-top:2px}
.card .sub{font-size:12px;color:var(--muted)}
section{margin:26px 0}
h2{font-size:18px;margin:0 0 10px;letter-spacing:-.01em}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;font-size:13.5px}
th,td{padding:7px 10px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}
th{background:#f1f5f9;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);white-space:nowrap}
tr:last-child td{border-bottom:none}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
tr.total td{font-weight:700;background:#f8fafc}
.pill{display:inline-block;border-radius:99px;padding:0 9px;font-size:12px;font-weight:600;color:#fff;white-space:nowrap}
.bar-row{display:grid;grid-template-columns:220px 1fr 110px;gap:10px;align-items:center;margin:6px 0;font-size:13px}
.bar-track{background:#eef2f7;border-radius:6px;height:14px;overflow:hidden}
.bar-fill{height:100%;border-radius:6px;min-width:2px}
.bar-row .num{text-align:right;font-variant-numeric:tabular-nums;color:var(--muted)}
.controls{display:flex;gap:10px;margin:10px 0;flex-wrap:wrap}
.controls input{padding:7px 10px;border:1px solid var(--line);border-radius:8px;font-size:13px;min-width:240px}
.controls .hint{align-self:center;color:var(--muted);font-size:12px}
th.sortable{cursor:pointer;user-select:none}
th.sortable:hover{color:var(--accent)}
code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px}
pre{background:#0f172a;color:#e2e8f0;padding:12px 14px;border-radius:10px;overflow-x:auto}
details.map{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin:8px 0}
details.map summary{cursor:pointer;font-weight:600}
details.map .tmpl{color:var(--muted);font-weight:400;font-size:12.5px}
.note{color:var(--muted);font-size:12.5px;margin-top:8px}
footer{border-top:1px solid var(--line);margin-top:34px;padding-top:14px;color:var(--muted);font-size:12.5px}
footer ul{margin:6px 0;padding-left:18px}
@media(max-width:720px){.bar-row{grid-template-columns:120px 1fr 90px}}
"""

_JS = """
function siFilter(input, tableId){
  var q = input.value.toLowerCase();
  document.querySelectorAll('#' + tableId + ' tbody tr').forEach(function(tr){
    tr.style.display = tr.textContent.toLowerCase().indexOf(q) >= 0 ? '' : 'none';
  });
}
function siSort(th){
  var table = th.closest('table'), tbody = table.querySelector('tbody');
  var idx = Array.prototype.indexOf.call(th.parentNode.children, th);
  var dir = th.dataset.dir === 'asc' ? -1 : 1;
  th.parentNode.querySelectorAll('th').forEach(function(o){ delete o.dataset.dir; });
  th.dataset.dir = dir === 1 ? 'asc' : 'desc';
  var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
  rows.sort(function(a, b){
    var av = a.children[idx].dataset.v || a.children[idx].textContent.trim();
    var bv = b.children[idx].dataset.v || b.children[idx].textContent.trim();
    var an = parseFloat(av), bn = parseFloat(bv);
    if (!isNaN(an) && !isNaN(bn)) return (an - bn) * dir;
    return av.localeCompare(bv) * dir;
  });
  rows.forEach(function(r){ tbody.appendChild(r); });
}
"""


def _esc(x) -> str:
    return _html.escape(str(x), quote=True)


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _clip(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def _pill(verdict: str) -> str:
    color = _VERDICT_COLORS.get(verdict, "#64748b")
    label = _esc(VERDICT_LABELS.get(verdict, verdict))
    return f'<span class="pill" style="background:{color}">{label}</span>'


def _bar(label_html: str, value: float, maximum: float, color: str, right_text: str) -> str:
    width = (value / maximum * 100) if maximum else 0
    return (
        f'<div class="bar-row"><div>{label_html}</div>'
        f'<div class="bar-track"><div class="bar-fill" style="width:{width:.1f}%;background:{color}"></div></div>'
        f'<div class="num">{_esc(right_text)}</div></div>'
    )


def render_html(
    audit: Audit, scan: Optional[CodeScan] = None, redact: bool = True, top_n: int = 50
) -> str:
    scrub = redact_text if redact else (lambda t: t)

    counts = audit.counts()
    spend = audit.spend()
    savings = audit.savings()
    total_calls = audit.total_calls
    total_spend = audit.total_spend
    tally = audit.signal_tally()

    def share(v: str) -> float:
        return (counts[v] / total_calls) if total_calls else 0.0

    def spend_share(v: str) -> float:
        return (spend[v] / total_spend) if total_spend else 0.0

    p: List[str] = []
    add = p.append

    # ------------------------------------------------------------------ head
    add("<!doctype html>")
    add('<html lang="en"><head><meta charset="utf-8">')
    add('<meta name="viewport" content="width=device-width, initial-scale=1">')
    add("<title>JEV migration audit</title>")
    add(f"<style>{_CSS}</style></head><body><div class='wrap'>")

    # ------------------------------------------------------------------ header
    add("<header><h1>JEV migration audit</h1>")
    add(
        '<div class="meta"><span class="chip">unofficial</span>'
        f"generated { _esc(audit.generated_at) } · should-i-jev v{_esc(__version__)} · "
        f"{len(audit.files)} log file(s) · {total_calls:,} calls · {len(audit.models)} model(s)"
    )
    if audit.skipped_lines:
        add(f" · {audit.skipped_lines} line(s) skipped")
    add("</div></header>")

    # ------------------------------------------------------------------ stat cards
    add('<div class="cards">')
    add(
        f'<div class="card"><div class="label">Likely JEV-shaped</div>'
        f'<div class="value" style="color:{_VERDICT_COLORS["likely"]}">{counts["likely"]:,}</div>'
        f'<div class="sub">{_pct(share("likely"))} of calls · {_money(spend["likely"])}</div></div>'
    )
    add(
        f'<div class="card"><div class="label">Worth a look</div>'
        f'<div class="value" style="color:{_VERDICT_COLORS["maybe"]}">{counts["maybe"]:,}</div>'
        f'<div class="sub">{_pct(share("maybe"))} of calls · {_money(spend["maybe"])}</div></div>'
    )
    add(
        f'<div class="card"><div class="label">Migratable spend</div>'
        f'<div class="value">{_money(audit.migratable_spend)}</div>'
        f'<div class="sub">of {_money(total_spend)} audited</div></div>'
    )
    cons = savings["conservative"]
    add(
        f'<div class="card"><div class="label">Est. savings (÷{audit.divisor})</div>'
        f'<div class="value" style="color:var(--accent)">{_money(cons)}</div>'
        f'<div class="sub">{_pct(cons / total_spend) if total_spend else "0%"} of spend · '
        f"÷{audit.divisor_optimistic} vendor claim: {_money(savings['vendor_claim'])}</div></div>"
    )
    if scan is not None:
        add(
            f'<div class="card"><div class="label">Code call sites</div>'
            f'<div class="value">{scan.decision_shaped} / {len(scan.findings)}</div>'
            f'<div class="sub">decision-shaped in {_esc(scan.root)}</div></div>'
        )
    add("</div>")

    # ------------------------------------------------------------------ verdicts
    add('<section id="verdicts"><h2>Verdict breakdown</h2>')
    max_calls = max([counts[v] for v in VERDICT_ORDER] + [1])
    for v in VERDICT_ORDER:
        add(
            _bar(
                _pill(v),
                counts[v],
                max_calls,
                _VERDICT_COLORS.get(v, "#64748b"),
                f"{counts[v]:,} · {_pct(share(v))}",
            )
        )
    add("<table><thead><tr><th>Verdict</th><th class='num'>Calls</th><th class='num'>Share</th>"
        "<th class='num'>Est. cost</th><th class='num'>Cost share</th></tr></thead><tbody>")
    for v in VERDICT_ORDER:
        add(
            f"<tr><td>{_pill(v)}</td><td class='num'>{counts[v]:,}</td>"
            f"<td class='num'>{_pct(share(v))}</td><td class='num'>{_money(spend[v])}</td>"
            f"<td class='num'>{_pct(spend_share(v))}</td></tr>"
        )
    add(f"<tr class='total'><td>Total</td><td class='num'>{total_calls:,}</td><td class='num'>100%</td>"
        f"<td class='num'>{_money(total_spend)}</td><td class='num'>100%</td></tr>")
    add("</tbody></table>")
    if counts["insufficient"]:
        add(
            '<div class="note">insufficient data = text-less usage-export rows; excluded from '
            "the migration estimate rather than guessed at.</div>"
        )
    add("</section>")

    # ------------------------------------------------------------------ models
    add('<section id="models"><h2>By model</h2><table>'
        "<thead><tr><th>Model</th><th class='num'>Calls</th><th class='num'>Est. cost</th>"
        "<th class='num'>Cost share</th><th class='num'>Likely</th></tr></thead><tbody>")
    model_rows = audit.models_table()
    for row in model_rows:
        cost_share = (row["cost"] / total_spend) if total_spend else 0.0
        add(
            f"<tr><td><code>{_esc(row['model'])}</code></td><td class='num'>{row['calls']:,}</td>"
            f"<td class='num'>{_money(row['cost'])}</td><td class='num'>{_pct(cost_share)}</td>"
            f"<td class='num'>{row['likely']:,}</td></tr>"
        )
    add("</tbody></table></section>")

    # ------------------------------------------------------------------ signals
    add('<section id="signals"><h2>Signals observed</h2>')
    for name, weight in WEIGHTS.items():
        matched = tally.get(name, 0)
        add(
            _bar(
                f"<code>{_esc(name)}</code> <span class='num' style='color:var(--muted)'>×{weight:.2f}</span>",
                matched,
                total_calls or 1,
                "#4f46e5",
                f"{matched:,}",
            )
        )
    add(
        '<div class="note">Score = Σ(weight × signal); generative-looking prompts with zero '
        "decision verbs are scaled down 40%.</div></section>"
    )

    # ------------------------------------------------------------------ candidates
    likely_top = [
        (c, d) for c, d in audit.top_candidates(top_n) if d.verdict == "likely"
    ]
    add('<section id="candidates"><h2>Top migration candidates</h2>')
    add(
        '<div class="controls"><input placeholder="Filter candidates… (model, prompt, signal)" '
        "oninput=\"siFilter(this,'cand-table')\"><span class=\"hint\">click a column header to sort</span></div>"
    )
    add('<table id="cand-table"><thead><tr><th class="sortable" onclick="siSort(this)">#</th>'
        '<th class="sortable" onclick="siSort(this)">Model</th>'
        '<th class="sortable num" onclick="siSort(this)">In/Out</th>'
        '<th class="sortable num" onclick="siSort(this)">Cost</th>'
        '<th class="sortable num" onclick="siSort(this)">Score</th>'
        "<th>Signals</th><th>Prompt (redacted)</th><th>Output</th></tr></thead><tbody>")
    for i, (call, detail) in enumerate(likely_top, start=1):
        usd, _, _, _ = audit.cost_of(call)
        in_tok = call.input_tokens if call.input_tokens is not None else "?"
        out_tok = call.output_tokens if call.output_tokens is not None else "?"
        signals = ", ".join(
            f"{k} ({v:.1f})"
            for k, v in sorted(detail.signals.items(), key=lambda kv: -kv[1])
            if v > 0
        ) or "—"
        add(
            f"<tr><td data-v='{i}'>{i}</td>"
            f"<td data-v='{_esc(call.model)}'><code>{_esc(call.model)}</code></td>"
            f"<td class='num' data-v='{in_tok if isinstance(in_tok, int) else 0}'>{in_tok}/{out_tok}</td>"
            f"<td class='num' data-v='{usd:.6f}'>{_money(usd)}</td>"
            f"<td class='num' data-v='{detail.score:.4f}'><b>{detail.score:.2f}</b></td>"
            f"<td>{_esc(signals)}</td>"
            f"<td>{_esc(_clip(scrub(call.prompt_excerpt), 110))}</td>"
            f"<td>{_esc(_clip(scrub(call.output_excerpt), 40))}</td></tr>"
        )
    add("</tbody></table></section>")

    # ------------------------------------------------------------------ code sites
    if scan is not None:
        add('<section id="code-sites"><h2>Code call sites</h2>')
        add(
            f"<div class='note'>Static scan of <code>{_esc(scan.root)}</code>: "
            f"{scan.files_scanned} file(s) scanned, {len(scan.findings)} LLM call site(s), "
            f"{scan.decision_shaped} decision-shaped. Python via AST; JS/TS via patterns.</div>"
        )
        if scan.findings:
            add("<table><thead><tr><th>Location</th><th>Lang</th><th>Model</th><th>API</th>"
                "<th>Handling</th><th class='num'>Score</th><th>Verdict</th>"
                "<th>Prompt (redacted)</th></tr></thead><tbody>")
            for f in scan.findings:
                add(
                    f"<tr><td><code>{_esc(f.path)}:{f.line}</code></td><td>{f.language}</td>"
                    f"<td><code>{_esc(f.model or '?')}</code></td>"
                    f"<td><code>{_esc(f.api)}</code></td>"
                    f"<td>{_esc(', '.join(f.handling) or '—')}</td>"
                    f"<td class='num'><b>{f.detail.score:.2f}</b></td>"
                    f"<td>{_pill(f.detail.verdict)}</td>"
                    f"<td>{_esc(_clip(scrub(f.prompt_excerpt), 80))}</td></tr>"
                )
            add("</tbody></table>")
        add("</section>")

    # ------------------------------------------------------------------ jev maps
    maps = audit.jev_maps()
    add('<section id="maps"><h2>Suggested JEV maps</h2>')
    if not maps:
        add("<div class='note'>No high-confidence clusters found.</div>")
    for m in maps:
        add(
            f"<details class='map' open><summary>{_esc(m['role'])} "
            f"<span class='tmpl'>“{_esc(m['template'])}” · {m['calls']:,} call(s) · "
            f"score {m['score_range'][0]:.2f}–{m['score_range'][1]:.2f}</span></summary><pre>"
        )
        lines = [
            "# Sketch only — adapt names, options and question phrasing to your domain.",
            f"class {m['role']}({m['kind']}):",
            f"    question = {_clip(scrub(m['example']), 90)!r}",
        ]
        if m["kind"] == "Score" and m["options"]:
            lines.append(f"    range = ({m['options'][0]:g}, {m['options'][1]:g})   # observed min/max")
        elif m["options"]:
            lines.append(f"    options = {m['options']!r}")
        elif m["note"]:
            lines.append(f"    # {m['note']}")
        add("\n".join(_esc(x) for x in lines))
        add("</pre></details>")
    add("</section>")

    # ------------------------------------------------------------------ footer
    prov = audit.cost_provenance()
    add("<footer><b>Methodology &amp; privacy</b><ul>")
    add(
        f"<li>Prices as of {_esc(audit.price_as_of)} ({_esc(audit.price_source)}); "
        f"{prov['logged']:,} call(s) priced from logged costs, {prov['estimated']:,} estimated."
        "</li>"
    )
    add(
        f"<li>JEV cost modeled as divisor scenarios: conservative ÷{audit.divisor} (headline), "
        f"vendor claim ÷{audit.divisor_optimistic}. Savings = migratable_spend × (1 − 1/divisor). "
        "The ~200× latency claim is not measured.</li>"
    )
    unknown = audit.unknown_models()
    if unknown:
        add("<li>Unknown models priced at table median: " + "; ".join(
            _esc(u) for u in unknown
        ) + "</li>")
    add(
        "<li>Fully local: no network calls, nothing uploaded. Excerpts redacted "
        "(keys, tokens, emails, long hex).</li>"
    )
    add(
        "<li>Unofficial community tool, not affiliated with TypeSafe. Directional estimates — "
        "benchmark before migrating. MIT licensed.</li>"
    )
    add("</ul></footer>")

    add(f"</div><script>{_JS}</script></body></html>")
    return "\n".join(p)
