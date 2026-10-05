"""
SynthRule — turn a results JSON into a Markdown report and a figure.

    python -m synthrule.report results/full.json --out results/report.md \\
        --figure results/phase_profile.png

The figure is a grouped bar chart: four protocol phases on the x axis, one bar
per agent.  It is the single most informative view of a SynthRule run, because
the Phase-B/Phase-D pair is the whole argument -- a tall D bar beside a short B
bar is a model that can execute rules it cannot induce.

Chart choices, per the project's visualization rules:
  * categorical hues assigned in the palette's fixed slot order, never cycled;
  * a legend is always present, and every bar carries its value as direct text
    so the PNG is readable on its own (the palette's light-surface contrast
    warning obliges visible labels or a table view -- the report ships both);
  * value text wears muted ink, never the series colour;
  * recessive grid, thin marks, a surface-coloured edge between adjacent bars.

Author: Songpengfei
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Sequence

# Validated categorical palette (light mode), fixed slot order.
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"

PHASES = "ABCD"
PHASE_LABEL = {
    "A": "A\nprior only",
    "B": "B\ninduction",
    "C": "C\nfeedback",
    "D": "D\nexplicit rules",
}


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


# --------------------------------------------------------------------------
# Figure
# --------------------------------------------------------------------------


def fig_phase_profile(payload: dict, out_png: Path, title: str = "") -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    by_agent = payload["summary"]["by_agent"]
    agents: List[str] = list(by_agent.keys())

    fig, ax = plt.subplots(figsize=(10.5, 4.6), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    n = len(agents)
    group_w = 0.78
    bar_w = group_w / max(1, n)
    xs = range(len(PHASES))

    for k, agent in enumerate(agents):
        vals = [by_agent[agent]["overall"][ph]["accuracy"] for ph in PHASES]
        offset = -group_w / 2 + bar_w * (k + 0.5)
        positions = [x + offset for x in xs]
        ax.bar(
            positions,
            vals,
            width=bar_w * 0.92,          # surface gap between adjacent bars
            color=PALETTE[k % len(PALETTE)],
            edgecolor=SURFACE,
            linewidth=1.4,
            label=agent,
            zorder=3,
        )
        for x, v in zip(positions, vals):
            ax.text(
                x,
                min(v + 0.022, 1.045),
                _pct(v),
                ha="center",
                va="bottom",
                fontsize=6.2,
                color=INK_MUTED,       # text tokens, never the series colour
                zorder=4,
            )

    ax.set_xticks(list(xs))
    ax.set_xticklabels([PHASE_LABEL[p] for p in PHASES], fontsize=9, color=INK_SECONDARY)
    ax.set_ylim(0, 1.12)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["0", "25%", "50%", "75%", "100%"], fontsize=8, color=INK_MUTED)
    ax.set_ylabel("exact-match accuracy", fontsize=9, color=INK_SECONDARY)
    ax.set_title(
        title or "SynthRule — accuracy by protocol phase",
        fontsize=12,
        color=INK_PRIMARY,
        pad=14,
        loc="left",
    )
    ax.text(
        0,
        1.015,
        "B vs D is the headline: a tall D beside a short B is a model that can execute rules it cannot induce.",
        transform=ax.transAxes,
        fontsize=8,
        color=INK_SECONDARY,
    )

    ax.yaxis.grid(True, color=GRIDLINE, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)
    ax.tick_params(axis="both", length=0)

    ax.legend(
        frameon=False,
        fontsize=8,
        ncol=min(n, 5),
        loc="upper center",
        bbox_to_anchor=(0.5, -0.16),
        labelcolor=INK_SECONDARY,
    )

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------


def _overall_table(payload: dict) -> str:
    by_agent = payload["summary"]["by_agent"]
    head = (
        "| Agent | Phase A<br>prior only | Phase B<br>induction | Phase C<br>feedback "
        "| Phase D<br>explicit rules | Phase D − B |\n"
        "|---|---|---|---|---|---|\n"
    )
    rows = []
    for agent, block in by_agent.items():
        ov = block["overall"]
        cells = []
        for ph in PHASES:
            acc = ov[ph]["accuracy"]
            lo, hi = ov[ph]["ci95"]
            cells.append(f"**{_pct(acc)}**<br><sub>{_pct(lo)}–{_pct(hi)}</sub>")
        gap = ov["D"]["accuracy"] - ov["B"]["accuracy"]
        rows.append(f"| `{agent}` | " + " | ".join(cells) + f" | **{gap:+.3f}** |")
    return head + "\n".join(rows)


def _answered_table(payload: dict) -> str:
    """Accuracy restricted to items the model actually answered.

    Kept separate from the headline table because the two answer different
    questions: the headline includes items the harness cut off (scored 0), this
    one excludes them. When the truncation column is all zeros they agree.
    """
    by_agent = payload["summary"]["by_agent"]
    head = (
        "| Agent | Phase A | Phase B | Phase C | Phase D | Unparsed / total |\n"
        "|---|---|---|---|---|---|\n"
    )
    rows = []
    for agent, block in by_agent.items():
        ov = block["overall"]
        # Falls back to the headline accuracy for results files written before
        # `accuracy_answered` existed.
        cells = [_pct(ov[p].get("accuracy_answered", ov[p]["accuracy"])) for p in PHASES]
        unp = sum(ov[p]["unparsed"] for p in PHASES)
        n = sum(ov[p]["n"] for p in PHASES)
        rows.append(f"| `{agent}` | " + " | ".join(cells) + f" | {unp} / {n} |")
    return head + "\n".join(rows)


def _metrics_table(payload: dict) -> str:
    by_agent = payload["summary"]["by_agent"]
    head = (
        "| Agent | learning gain<br>B − A | feedback gain<br>late C − early C "
        "| induction gap<br>D − B |\n|---|---|---|---|\n"
    )
    rows = []
    for agent, block in by_agent.items():
        m = block.get("metrics", {})
        cells = []
        for key in ("learning_gain", "feedback_gain", "induction_gap"):
            entry = m.get(key)
            if not entry:
                cells.append("—")
                continue
            lo, hi = entry["ci95"]
            cells.append(f"{entry['mean']:+.3f}<br><sub>[{lo:+.2f}, {hi:+.2f}]</sub>")
        rows.append(f"| `{agent}` | " + " | ".join(cells) + " |")
    return head + "\n".join(rows)


def _nested_table(payload: dict, key: str, title: str) -> str:
    lines = [f"**{title}**", "", "| Value | " + " | ".join(f"Phase {p}" for p in PHASES) + " |", "|---|" + "---|" * 4]
    for agent, block in payload["summary"]["by_agent"].items():
        sub = block.get(key) or {}
        if not sub:
            continue
        for bucket, per_phase in sub.items():
            vals = " | ".join(_pct(per_phase.get(p, 0.0)) for p in PHASES)
            lines.append(f"| `{agent}` · {bucket} | {vals} |")
    return "\n".join(lines)


def _health_table(payload: dict) -> str:
    lines = [
        "| Agent | Items | Unparsed | Truncated responses |",
        "|---|---|---|---|",
    ]
    for agent, block in payload["summary"]["by_agent"].items():
        ov = block["overall"]
        n = sum(ov[p]["n"] for p in PHASES)
        unp = sum(ov[p]["unparsed"] for p in PHASES)
        tr = sum(ov[p]["truncated"] for p in PHASES)
        lines.append(f"| `{agent}` | {n} | {unp} | {tr} |")
    return "\n".join(lines)


def _familiar_table(payload: dict) -> str:
    lines = [
        "| Agent | Novel B | Familiar B | familiar_delta (B) | Novel D | Familiar D |",
        "|---|---|---|---|---|---|",
    ]
    for agent, block in payload["summary"]["by_agent"].items():
        fv = block.get("familiar_vs_novel") or {}
        if not fv:
            continue
        nb = fv["novel"]["B"]["accuracy"]
        fb = fv["familiar"]["B"]["accuracy"]
        nd = fv["novel"]["D"]["accuracy"]
        fd = fv["familiar"]["D"]["accuracy"]
        lines.append(
            f"| `{agent}` | {_pct(nb)} | {_pct(fb)} | **{fb - nb:+.3f}** | {_pct(nd)} | {_pct(fd)} |"
        )
    return "\n".join(lines)


def render_markdown(payload: dict, out_md: Path, figure_name: str = "") -> None:
    cfg = payload["config"]
    summary = payload["summary"]

    parts: List[str] = []
    parts.append("# SynthRule — 运行结果 / Run Report\n")
    parts.append(
        f"- **模型 / Model:** {', '.join(a for a in summary['by_agent'] if a.startswith('llm')) or '(baselines only)'}\n"
        f"- **随机种子 / Seed:** `{cfg['seed']}`\n"
        f"- **任务数 / Tasks:** {summary['n_tasks']} "
        f"({cfg['n_novel']} novel + {cfg['n_familiar']} contamination-probe)\n"
        f"- **计分条目 / Scored items:** {summary['n_items']}\n"
        f"- **每题示例数 / Support examples:** {cfg['n_support']}\n"
        f"- **难度梯度 / Difficulty tiers:** {cfg['difficulties']} rules\n"
        f"- **字母表 / Alphabets:** {', '.join(cfg['alphabet_types'])}\n"
    )

    if figure_name:
        parts.append(f"\n![Phase profile]({figure_name})\n")

    parts.append("\n## 1. 各阶段准确率（精确匹配，95% Wilson 区间）\n")
    parts.append(_overall_table(payload))

    parts.append(
        "\n\n> 表中准确率以**全部计分条目**为分母；被 harness 截断而无法作答的条目记为 0。"
        "下表给出**仅计已作答条目**的准确率 —— 若两表一致，说明没有条目被截断。\n"
    )
    parts.append("\n## 2. 仅计已作答条目的准确率\n")
    parts.append(_answered_table(payload))

    parts.append("\n\n## 3. 派生指标（按任务 bootstrap 95% 区间）\n")
    parts.append(_metrics_table(payload))

    parts.append("\n\n## 4. 按难度分层\n")
    parts.append(_nested_table(payload, "by_difficulty", "难度 = 规则条数"))

    parts.append("\n\n## 5. 按字母表分层（tokenization 混淆检查）\n")
    parts.append(_nested_table(payload, "by_alphabet", "字母表家族"))

    parts.append("\n\n## 6. 训练数据污染探针\n")
    parts.append(_familiar_table(payload))
    parts.append(
        "\n\n> `familiar_delta` = 熟悉字母表上的 B 阶段准确率 − 陌生字母表上的 B 阶段准确率。"
        "显著为正说明模型在见过的变换上更强，即存在检索优势而非学习优势。"
    )

    parts.append("\n\n## 7. 运行健康度\n")
    parts.append(_health_table(payload))
    parts.append(
        "\n\n> `Unparsed` = 无法从回复中解析出答案；`Truncated` = 回复因 `max_tokens` 被截断。"
        "两者必须与「模型答错」区分开 —— 若截断数偏高，准确率是系统性低估的。"
    )

    if summary.get("usage"):
        parts.append("\n\n## 8. Token 用量\n")
        parts.append("| Agent | Calls | Errors | Truncated | Input | Output | Total |")
        parts.append("|---|---|---|---|---|---|---|")
        for agent, u in summary["usage"].items():
            parts.append(
                f"| `{agent}` | {u['calls']} | {u['errors']} | {u['truncated_responses']} "
                f"| {u['input_tokens']:,} | {u['output_tokens']:,} | {u['total_tokens']:,} |"
            )

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(parts) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m synthrule.report")
    p.add_argument("results", help="path to a results JSON produced by run_benchmark.py")
    p.add_argument("--out", default="results/report.md")
    p.add_argument("--figure", default="results/phase_profile.png")
    p.add_argument("--no-figure", action="store_true")
    args = p.parse_args(argv)

    payload = json.loads(Path(args.results).read_text(encoding="utf-8"))

    figure_name = ""
    if not args.no_figure:
        fig_path = Path(args.figure)
        fig_phase_profile(payload, fig_path)
        figure_name = fig_path.name
        print(f"figure -> {fig_path}")

    render_markdown(payload, Path(args.out), figure_name=figure_name)
    print(f"report -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
