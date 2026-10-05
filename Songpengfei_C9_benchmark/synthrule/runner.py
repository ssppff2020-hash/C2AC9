"""
SynthRule — protocol orchestration and metric computation.

The four phases are run as independent work units, which is what makes the
suite cheap to run in parallel.  Phase C is internally sequential by
construction -- each item depends on the corrections shown for the previous
ones -- but it generates its own history, so it never blocks the other phases.

Reported quantities, and what each is for
-----------------------------------------
acc_a   prior-only accuracy            the floor; a learning gain is measured
                                       against this, not against zero
acc_b   accuracy after k examples      the learning measurement proper
acc_c   accuracy with running feedback KSTAR's dR -> K update
acc_d   accuracy with explicit rules   the execution ceiling

learning_gain  = acc_b - acc_a   how much the examples were worth
feedback_gain  = late_C - early_C  whether corrections changed behaviour
induction_gap  = acc_d - acc_b   the key isolation metric: can the model
                                   *execute* rules it cannot *induce*?
familiar_delta = acc_b(familiar) - acc_b(novel)  the contamination probe

Uncertainty is reported as Wilson intervals for proportions (correct at small
n, unlike the normal approximation) and bootstrap intervals for differences
of means.

Author: Songpengfei
"""

from __future__ import annotations

import json
import math
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .agents import Agent, ItemContext, make_agent
from .generator import Task, build_task_set, load_tasks, save_tasks
from .prompts import build_phase_a, build_phase_b, build_phase_c, build_phase_d
from .scoring import format_answer, parse_answer, score_answer

Seq = List[str]


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


@dataclass
class BenchmarkConfig:
    seed: int = 20260931
    n_novel: int = 10
    n_familiar: int = 4
    difficulties: Tuple[int, ...] = (1, 2, 3, 4)
    alphabet_types: Tuple[str, ...] = ("pseudoword", "glyph", "latin")

    n_support: int = 6
    n_items_a: int = 3
    n_items_b: int = 6
    n_items_c: int = 8
    n_items_d: int = 3

    agents: Tuple[str, ...] = ("oracle", "random", "identity", "align")
    concurrency: int = 8
    task_set_path: Optional[str] = None

    @property
    def n_query(self) -> int:
        return self.n_items_a + self.n_items_b + self.n_items_c + self.n_items_d


# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------


def wilson_interval(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson score interval -- behaves sensibly at n as small as 3, which is
    exactly the regime this benchmark operates in."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1.0 + z * z / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (centre - half) / denom), min(1.0, (centre + half) / denom))


def bootstrap_ci(
    values: Sequence[float], n_resamples: int = 4000, alpha: float = 0.05, seed: int = 0
) -> Tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    if len(values) == 1:
        return (values[0], values[0])
    rng = random.Random(seed)
    k = len(values)
    means = []
    for _ in range(n_resamples):
        means.append(sum(values[rng.randrange(k)] for _ in range(k)) / k)
    means.sort()
    lo = means[int(alpha / 2 * n_resamples)]
    hi = means[min(n_resamples - 1, int((1 - alpha / 2) * n_resamples) - 1)]
    return (lo, hi)


def _proportion(rows: Sequence["ItemResult"]) -> Dict[str, object]:
    n = len(rows)
    k = sum(r.exact for r in rows)
    lo, hi = wilson_interval(k, n)
    unparsed = sum(1 for r in rows if not r.parsed)
    answered = n - unparsed
    # Accuracy over items the model actually answered. Reported next to the
    # headline figure so that a run truncated by the harness can never be
    # mistaken for a model that failed -- the distinction that produced a
    # fabricated floor effect in our own first pilot.
    answered_acc = (
        sum(r.exact for r in rows if r.parsed) / answered if answered else 0.0
    )
    return {
        "n": n,
        "correct": k,
        "accuracy": (k / n) if n else 0.0,
        "accuracy_answered": answered_acc,
        "answered": answered,
        "ci95": [lo, hi],
        "partial": (sum(r.partial for r in rows) / n) if n else 0.0,
        "unparsed": unparsed,
        "truncated": sum(1 for r in rows if r.truncated),
    }


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------


@dataclass
class ItemResult:
    agent: str
    task_uid: str
    phase: str
    difficulty: int
    alphabet_type: str
    familiar: bool
    index: int
    inp: Seq
    gold: Seq
    predicted: Optional[Seq]
    raw: str
    exact: int
    partial: float
    parsed: bool
    latency_s: float
    truncated: bool = False


# --------------------------------------------------------------------------
# Phase execution
# --------------------------------------------------------------------------


def _ctx(task: Task, inp: Seq, gold: Seq) -> ItemContext:
    return ItemContext(
        symbols=list(task.universe.symbols),
        inp=list(inp),
        gold=list(gold),
        support=list(task.support),
    )


def _run_simple_phase(
    agent: Agent, task: Task, phase: str, items: Sequence[Tuple[Seq, Seq]]
) -> List[ItemResult]:
    builder = {
        "A": build_phase_a,
        "B": build_phase_b,
        "D": build_phase_d,
    }[phase]

    out: List[ItemResult] = []
    for i, (inp, gold) in enumerate(items):
        prompt = builder(task, i + 1, len(items), inp)
        t0 = time.time()
        reply = agent.answer(prompt, _ctx(task, inp, gold))
        dt = time.time() - t0
        raw = reply.text
        pred = parse_answer(raw, task.universe.symbols)
        sc = score_answer(pred, gold)
        out.append(
            ItemResult(
                agent=agent.name,
                task_uid=task.universe.uid,
                phase=phase,
                difficulty=task.universe.difficulty,
                alphabet_type=task.universe.alphabet_type,
                familiar=task.universe.familiar,
                index=i,
                inp=list(inp),
                gold=list(gold),
                predicted=pred,
                raw=raw,
                exact=sc.exact,
                partial=sc.partial,
                parsed=sc.parsed,
                latency_s=round(dt, 3),
                truncated=reply.truncated,
            )
        )
    return out


def _run_phase_c(
    agent: Agent, task: Task, items: Sequence[Tuple[Seq, Seq]]
) -> List[ItemResult]:
    """Sequential feedback loop. Each call carries the full correction history."""
    out: List[ItemResult] = []
    history: List[Tuple[Seq, Optional[str], Seq]] = []

    for i, (inp, gold) in enumerate(items):
        prompt = build_phase_c(task, i + 1, len(items), inp, history)
        t0 = time.time()
        reply = agent.answer(prompt, _ctx(task, inp, gold))
        dt = time.time() - t0
        raw = reply.text
        pred = parse_answer(raw, task.universe.symbols)
        sc = score_answer(pred, gold)
        out.append(
            ItemResult(
                agent=agent.name,
                task_uid=task.universe.uid,
                phase="C",
                difficulty=task.universe.difficulty,
                alphabet_type=task.universe.alphabet_type,
                familiar=task.universe.familiar,
                index=i,
                inp=list(inp),
                gold=list(gold),
                predicted=pred,
                raw=raw,
                exact=sc.exact,
                partial=sc.partial,
                parsed=sc.parsed,
                latency_s=round(dt, 3),
                truncated=reply.truncated,
            )
        )
        history.append(
            (list(inp), format_answer(pred) if pred is not None else None, list(gold))
        )
    return out


def run_benchmark(cfg: BenchmarkConfig, verbose: bool = True) -> Dict[str, object]:
    # -- task set ---------------------------------------------------------
    if cfg.task_set_path and Path(cfg.task_set_path).exists():
        tasks = load_tasks(Path(cfg.task_set_path))
        if verbose:
            print(f"[synthrule] loaded {len(tasks)} tasks from {cfg.task_set_path}")
    else:
        tasks = build_task_set(
            seed=cfg.seed,
            n_novel=cfg.n_novel,
            n_familiar=cfg.n_familiar,
            difficulties=cfg.difficulties,
            alphabet_types=cfg.alphabet_types,
            n_support=cfg.n_support,
            n_query=cfg.n_query,
        )
        if cfg.task_set_path:
            save_tasks(tasks, Path(cfg.task_set_path))
        if verbose:
            print(f"[synthrule] generated {len(tasks)} tasks (seed={cfg.seed})")

    # -- split the query pool across phases -------------------------------
    def slice_items(task: Task) -> Dict[str, List[Tuple[Seq, Seq]]]:
        q = task.query
        a_end = cfg.n_items_a
        b_end = a_end + cfg.n_items_b
        c_end = b_end + cfg.n_items_c
        return {
            "A": q[:a_end],
            "B": q[a_end:b_end],
            "C": q[b_end:c_end],
            "D": q[c_end : c_end + cfg.n_items_d],
        }

    # -- agents -----------------------------------------------------------
    agents: List[Agent] = [make_agent(n, seed=cfg.seed) for n in cfg.agents]

    # -- work units -------------------------------------------------------
    jobs = []
    for agent in agents:
        for task in tasks:
            per_phase = slice_items(task)
            for phase in ("A", "B", "C", "D"):
                items = per_phase[phase]
                if items:
                    jobs.append((agent, task, phase, items))

    if verbose:
        print(f"[synthrule] {len(jobs)} work units, concurrency={cfg.concurrency}")

    results: List[ItemResult] = []
    done = 0
    with ThreadPoolExecutor(max_workers=cfg.concurrency) as pool:
        futs = {}
        for agent, task, phase, items in jobs:
            if phase == "C":
                fut = pool.submit(_run_phase_c, agent, task, items)
            else:
                fut = pool.submit(_run_simple_phase, agent, task, phase, items)
            futs[fut] = (agent.name, task.universe.uid, phase)

        for fut in as_completed(futs):
            agent_name, uid, phase = futs[fut]
            try:
                results.extend(fut.result())
            except Exception as exc:
                print(f"[synthrule] FAILED {agent_name} {uid} {phase}: {exc!r}")
            done += 1
            if verbose and done % 10 == 0:
                print(f"[synthrule]   {done}/{len(jobs)} units complete")

    results.sort(key=lambda r: (r.agent, r.task_uid, r.phase, r.index))
    summary = aggregate(results, cfg, agents)
    return {"config": asdict(cfg), "results": [asdict(r) for r in results], "summary": summary}


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------


def _mean_metric(rows: Sequence["ItemResult"], phase: str) -> float:
    return _proportion([r for r in rows if r.phase == phase])["accuracy"]


def aggregate(
    results: Sequence[ItemResult], cfg: BenchmarkConfig, agents: Sequence[Agent]
) -> Dict[str, object]:
    by_agent: Dict[str, object] = {}

    for agent in agents:
        rows = [r for r in results if r.agent == agent.name]
        if not rows:
            continue

        overall = {
            ph: _proportion([r for r in rows if r.phase == ph]) for ph in "ABCD"
        }

        # -- per-task metrics, then bootstrap across tasks -----------------
        uids = sorted({r.task_uid for r in rows})
        gains: Dict[str, List[float]] = {
            "learning_gain": [],
            "feedback_gain": [],
            "induction_gap": [],
        }
        for uid in uids:
            trows = [r for r in rows if r.task_uid == uid]
            acc: Dict[str, float] = {}
            for ph in "ABCD":
                ph_rows = [r for r in trows if r.phase == ph]
                acc[ph] = (
                    sum(r.exact for r in ph_rows) / len(ph_rows) if ph_rows else float("nan")
                )
            c_rows = sorted([r for r in trows if r.phase == "C"], key=lambda r: r.index)
            if c_rows:
                half = max(1, len(c_rows) // 2)
                early = sum(r.exact for r in c_rows[:half]) / half
                late_rows = c_rows[half:] or c_rows[:half]
                late = sum(r.exact for r in late_rows) / len(late_rows)
            else:
                early = late = float("nan")

            gains["learning_gain"].append(acc["B"] - acc["A"])
            gains["feedback_gain"].append(late - early)
            gains["induction_gap"].append(acc["D"] - acc["B"])

        metrics: Dict[str, object] = {}
        for key, vals in gains.items():
            clean = [v for v in vals if not math.isnan(v)]
            if clean:
                lo, hi = bootstrap_ci(clean, seed=cfg.seed)
                metrics[key] = {
                    "mean": sum(clean) / len(clean),
                    "ci95": [lo, hi],
                    "n_tasks": len(clean),
                    "per_task": [round(v, 4) for v in vals],
                }

        # -- breakdowns ----------------------------------------------------
        def breakdown(keyfn) -> Dict[str, object]:
            buckets: Dict[str, List[ItemResult]] = {}
            for r in rows:
                buckets.setdefault(str(keyfn(r)), []).append(r)
            return {
                k: {ph: _proportion([x for x in v if x.phase == ph])["accuracy"] for ph in "ABCD"}
                for k, v in sorted(buckets.items())
            }

        familiar_block = {
            "novel": {
                ph: _proportion(
                    [r for r in rows if r.phase == ph and not r.familiar]
                )
                for ph in "ABCD"
            },
            "familiar": {
                ph: _proportion([r for r in rows if r.phase == ph and r.familiar])
                for ph in "ABCD"
            },
        }

        by_agent[agent.name] = {
            "overall": overall,
            "metrics": metrics,
            "by_difficulty": breakdown(lambda r: r.difficulty),
            "by_alphabet": breakdown(lambda r: r.alphabet_type),
            "familiar_vs_novel": familiar_block,
            "errors": getattr(getattr(agent, "usage", None), "errors", 0),
        }

    usage = {}
    for agent in agents:
        u = getattr(agent, "usage", None)
        if u is not None:
            usage[agent.name] = u.as_dict()

    return {
        "by_agent": by_agent,
        "usage": usage,
        "n_items": len(results),
        "n_tasks": len({r.task_uid for r in results}),
    }
