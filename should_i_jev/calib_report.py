"""Calibration reports: markdown + self-contained HTML with inline SVG charts."""
from __future__ import annotations

import html as _html
from datetime import datetime, timezone
from typing import Dict, List, Optional

from . import __version__
from .calibration import COVERAGE_LEVELS, ReliabilityBin

_COLORS = ["#4f46e5", "#059669", "#d97706", "#db2777", "#0891b2"]


def _esc(x) -> str:
    return _html.escape(str(x), quote=True)


def _fmt(x: Optional[float], digits: int = 3) -> str:
    return "—" if x is None else f"{x:.{digits}f}"


# --------------------------------------------------------------------------- markdown

def _bin_table_md(bins: List[ReliabilityBin]) -> List[str]:
    lines = [
        "| confidence bin | n | avg conf | accuracy | gap | |gap| |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for b in bins:
        bar = "▇" * int(round(b.abs_gap * 40)) if b.n else ""
        lines.append(
            f"| {b.lo:.1f}–{b.hi:.1f} | {b.n} | {_fmt(b.conf) if b.n else '—'} | "
            f"{_fmt(b.acc) if b.n else '—'} | {_fmt(b.gap, 3) if b.n else '—'} | "
            f"{_fmt(b.abs_gap, 3) if b.n else '—'} {bar} |"
        )
    return lines


def render_calib_markdown(summaries: List[Dict], skipped: int = 0) -> str:
    """summaries: ordered list of {name, summary} dicts — first is the candidate,
    the rest are baselines."""
    lines: List[str] = []
    add = lines.append
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    add("# Decision-model calibration report")
    add("")
    add(f"_Generated {generated} by should-i-jev v{__version__} (unofficial)._")
    add("")
    total_n = sum(s["summary"]["n"] for s in summaries)
    add(f"**Inputs:** {len(summaries)} decision set(s), {total_n} records"
        + (f", {skipped} unparseable/skipped line(s)." if skipped else "."))
    add("")

    add("## Headline metrics")
    add("")
    add("| model | n | accuracy | avg conf | ECE ↓ | MCE ↓ | Brier ↓ | acc@90%cov | acc@99%cov |")
    add("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for s in summaries:
        m = s["summary"]
        cov = m["coverage"]
        add(
            f"| `{_esc(s['name'])}` | {m['n']} | {m['accuracy']:.3f} | {m['avg_p']:.3f} | "
            f"**{m['ece']:.3f}** | {m['mce']:.3f} | {m['brier']:.3f} | "
            f"{_fmt(cov.get(0.9))} | {_fmt(cov.get(0.99))} |"
        )
    add("")
    add(
        "ECE = Σ (bin share × |accuracy − confidence|). Lower is better: it measures "
        "whether stated probabilities can be trusted. acc@X%cov = selective accuracy "
        "when the model answers only its most-confident X% and abstains (Noul) on the rest."
    )
    add("")

    for s in summaries:
        m = s["summary"]
        add(f"## Reliability — `{_esc(s['name'])}`")
        add("")
        lines.extend(_bin_table_md(m["bins"]))
        add("")

    add("## Risk–coverage (selective accuracy)")
    add("")
    add("| coverage | " + " | ".join(f"`{_esc(s['name'])}`" for s in summaries) + " |")
    add("|---:|" + "---:|" * len(summaries))
    for level in COVERAGE_LEVELS:
        row = [_fmt(s["summary"]["coverage"].get(level)) for s in summaries]
        add(f"| {level * 100:.0f}% | " + " | ".join(row) + " |")
    add("")
    add(
        "Read it as: _if the model only answered above a confidence cut keeping X% of "
        "questions, its accuracy would be …_. A well-calibrated model lets you pick the "
        "cut; an overconfident one cannot."
    )
    add("")

    for s in summaries:
        groups = s["summary"]["groups"]
        if len(groups) > 1:
            add(f"## Per-question breakdown — `{_esc(s['name'])}`")
            add("")
            add("| question | n | accuracy | ECE | avg conf |")
            add("|---|---:|---:|---:|---:|")
            for g in groups[:12]:
                add(
                    f"| `{_esc(g['question'])}` | {g['n']} | {g['acc']:.3f} | "
                    f"{g['ece']:.3f} | {g['avg_p']:.3f} |"
                )
            add("")

    add("## Methodology & caveats")
    add("")
    add(
        "- p = probability the model assigned to its own answer (Jev returns it natively; "
        "for LLMs use the top-choice probability). correct = ground-truth hit flag."
    )
    add("- Equal-width confidence bins (default 10). Small bins make ECE noisy — "
        "treat bins with n < ~30 as indicative only.")
    add("- Local computation only; nothing is uploaded.")
    add("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- SVG charts

def reliability_svg(summary: Dict, color: str = "#4f46e5", width: int = 560, height: int = 300) -> str:
    bins: List[ReliabilityBin] = summary["bins"]
    pad_l, pad_b, pad_t, pad_r = 44, 34, 26, 10
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    n = len(bins)
    bw = plot_w / n

    def y(v: float) -> float:
        return pad_t + plot_h * (1.0 - v)

    parts: List[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" aria-label="reliability diagram">'
    )
    parts.append(f'<rect width="{width}" height="{height}" fill="#ffffff"/>')
    # grid + diagonal
    for v in (0.0, 0.25, 0.5, 0.75, 1.0):
        parts.append(
            f'<line x1="{pad_l}" y1="{y(v):.1f}" x2="{width - pad_r}" y2="{y(v):.1f}" '
            f'stroke="#e2e8f0" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{pad_l - 6}" y="{y(v) + 4:.1f}" text-anchor="end" font-size="10" fill="#64748b">{v:.1f}</text>'
        )
    parts.append(
        f'<line x1="{pad_l}" y1="{y(1)}" x2="{width - pad_r}" y2="{y(0)}" '
        f'stroke="#94a3b8" stroke-dasharray="4 4" stroke-width="1"/>'
    )
    # bars = empirical accuracy, tick = mean confidence
    for i, b in enumerate(bins):
        x = pad_l + i * bw
        if b.n:
            acc_h = plot_h * b.acc
            parts.append(
                f'<rect x="{x + 3:.1f}" y="{y(b.acc):.1f}" width="{bw - 6:.1f}" height="{acc_h:.1f}" '
                f'fill="{color}" fill-opacity="0.55" stroke="{color}" stroke-width="0.5"/>'
            )
            parts.append(
                f'<line x1="{x + 2:.1f}" y1="{y(b.conf):.1f}" x2="{x + bw - 2:.1f}" y2="{y(b.conf):.1f}" '
                f'stroke="#0f172a" stroke-width="2"/>'
            )
        if i % max(1, n // 5) == 0:
            parts.append(
                f'<text x="{x + bw / 2:.1f}" y="{height - 20}" text-anchor="middle" font-size="10" '
                f'fill="#64748b">{b.lo:.1f}</text>'
            )
    parts.append(
        f'<text x="{pad_l + plot_w / 2}" y="{height - 4}" text-anchor="middle" font-size="11" '
        f'fill="#64748b">confidence →</text>'
    )
    parts.append(
        f'<text x="{pad_l - 6}" y="{pad_t - 10}" text-anchor="end" font-size="11" '
        f'fill="#64748b">acc ↑</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def risk_coverage_svg(summaries: List[Dict], width: int = 560, height: int = 300) -> str:
    pad_l, pad_b, pad_t, pad_r = 44, 34, 36, 10
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    def x(c: float) -> float:
        return pad_l + plot_w * c

    all_pts = [p for s in summaries for p in s["summary"]["rc"]]
    y_min = min((p["sel_acc"] for p in all_pts), default=0.0)
    y_min = max(0.0, min(y_min, 0.9))
    y_max = 1.0

    def y(v: float) -> float:
        return pad_t + plot_h * (1.0 - (v - y_min) / (y_max - y_min))

    parts: List[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" aria-label="risk-coverage curve">'
    )
    parts.append(f'<rect width="{width}" height="{height}" fill="#ffffff"/>')
    for v in (y_min, 0.5, 0.75, 1.0) if y_min < 0.5 else (0.5, 0.75, 1.0):
        parts.append(
            f'<line x1="{pad_l}" y1="{y(v):.1f}" x2="{width - pad_r}" y2="{y(v):.1f}" '
            f'stroke="#e2e8f0"/>'
        )
        parts.append(
            f'<text x="{pad_l - 6}" y="{y(v) + 4:.1f}" text-anchor="end" font-size="10" fill="#64748b">{v:.2f}</text>'
        )
    for c in (0.0, 0.25, 0.5, 0.75, 1.0):
        parts.append(
            f'<text x="{x(c):.1f}" y="{height - 20}" text-anchor="middle" font-size="10" '
            f'fill="#64748b">{c:.2f}</text>'
        )
    parts.append(
        f'<text x="{pad_l + plot_w / 2}" y="{height - 4}" text-anchor="middle" font-size="11" '
        f'fill="#64748b">coverage →</text>'
    )
    parts.append(
        f'<text x="{pad_l - 6}" y="{pad_t - 10}" text-anchor="end" font-size="11" '
        f'fill="#64748b">acc ↑</text>'
    )

    for idx, s in enumerate(summaries):
        color = _COLORS[idx % len(_COLORS)]
        pts = s["summary"]["rc"]
        if not pts:
            continue
        path = " ".join(f"{x(p['coverage']):.1f},{y(p['sel_acc']):.1f}" for p in pts)
        parts.append(f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="2.5"/>')
        parts.append(
            f'<text x="{width - pad_r}" y="{pad_t + 12 + idx * 14}" text-anchor="end" '
            f'font-size="11" fill="{color}">{_esc(s["name"])} (ECE {s["summary"]["ece"]:.3f})</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


# --------------------------------------------------------------------------- HTML

def render_calib_html(summaries: List[Dict], skipped: int = 0) -> str:
    from .report_html import _CSS  # share the dashboard look

    p: List[str] = []
    add = p.append
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total_n = sum(s["summary"]["n"] for s in summaries)

    add("<!doctype html><html lang='en'><head><meta charset='utf-8'>")
    add("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    add("<title>Decision-model calibration</title>")
    add(f"<style>{_CSS}</style></head><body><div class='wrap'>")
    add("<header><h1>Decision-model calibration</h1>")
    add(
        f"<div class='meta'><span class='chip'>unofficial</span>generated {generated} · "
        f"should-i-jev v{_esc(__version__)} · {len(summaries)} set(s) · {total_n:,} decisions"
        + (f" · {skipped} skipped" if skipped else "")
        + "</div></header>"
    )

    add("<section><h2>Headline metrics</h2><table><thead><tr>"
        "<th>model</th><th class='num'>n</th><th class='num'>accuracy</th>"
        "<th class='num'>avg conf</th><th class='num'>ECE ↓</th><th class='num'>MCE ↓</th>"
        "<th class='num'>Brier ↓</th><th class='num'>acc@90%cov</th>"
        "<th class='num'>acc@99%cov</th></tr></thead><tbody>")
    for idx, s in enumerate(summaries):
        m = s["summary"]
        cov = m["coverage"]
        color = _COLORS[idx % len(_COLORS)]
        add(
            f"<tr><td><b style='color:{color}'>{_esc(s['name'])}</b></td>"
            f"<td class='num'>{m['n']:,}</td><td class='num'>{m['accuracy']:.3f}</td>"
            f"<td class='num'>{m['avg_p']:.3f}</td><td class='num'><b>{m['ece']:.3f}</b></td>"
            f"<td class='num'>{m['mce']:.3f}</td><td class='num'>{m['brier']:.3f}</td>"
            f"<td class='num'>{_fmt(cov.get(0.9))}</td>"
            f"<td class='num'>{_fmt(cov.get(0.99))}</td></tr>"
        )
    add("</tbody></table>")
    add("<div class='note'>ECE = Σ(bin share × |accuracy − confidence|). "
        "acc@X%cov = accuracy when answering only the most-confident X% "
        "(abstaining/Noul on the rest).</div></section>")

    add("<section id='rc'><h2>Risk–coverage</h2>")
    add(risk_coverage_svg(summaries))
    add("<div class='note'>Higher selective accuracy at high coverage is the prize: "
        "a calibrated decision model lets you choose where to abstain.</div></section>")

    for idx, s in enumerate(summaries):
        color = _COLORS[idx % len(_COLORS)]
        add(f"<section><h2>Reliability — {_esc(s['name'])}</h2>")
        add(reliability_svg(s["summary"], color=color))
        add("<table><thead><tr><th>confidence bin</th><th class='num'>n</th>"
            "<th class='num'>avg conf</th><th class='num'>accuracy</th>"
            "<th class='num'>gap</th></tr></thead><tbody>")
        for b in s["summary"]["bins"]:
            add(
                f"<tr><td>{b.lo:.1f}–{b.hi:.1f}</td><td class='num'>{b.n}</td>"
                f"<td class='num'>{_fmt(b.conf) if b.n else '—'}</td>"
                f"<td class='num'>{_fmt(b.acc) if b.n else '—'}</td>"
                f"<td class='num'>{_fmt(b.gap) if b.n else '—'}</td></tr>"
            )
        add("</tbody></table></section>")

    add("<footer><ul>"
        "<li>p = probability assigned to the model's own answer; correct = ground-truth hit.</li>"
        "<li>Equal-width bins (default 10); bins with n &lt; ~30 are noisy.</li>"
        "<li>Fully local computation; no network calls. Unofficial, MIT.</li></ul></footer>")
    add("</div></body></html>")
    return "\n".join(p)
