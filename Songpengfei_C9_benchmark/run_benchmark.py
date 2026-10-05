#!/usr/bin/env python
"""
SynthRule — command line entry point.

Examples
--------
Smoke test (no network, instant):

    python run_benchmark.py --pilot --agents oracle random --out results/pilot.json

Full run against the configured model:

    python run_benchmark.py --agents oracle random identity align llm \\
        --out results/full.json

Freeze the task set first so a third party can re-run the exact same puzzles:

    python run_benchmark.py --freeze-tasks data/tasks_seed20260931.json --dry-run

Author: Songpengfei
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

# Windows consoles default to a legacy code page; the glyph alphabet would
# crash on print() without this.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

from synthrule.generator import build_task_set, save_tasks  # noqa: E402
from synthrule.runner import BenchmarkConfig, run_benchmark  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_benchmark",
        description="SynthRule: measure genuine learning in language models.",
    )
    p.add_argument("--seed", type=int, default=20260931, help="master seed for task generation")
    p.add_argument("--n-novel", type=int, default=10, help="number of procedurally generated universes")
    p.add_argument("--n-familiar", type=int, default=4, help="number of contamination-probe universes")
    p.add_argument(
        "--difficulties", type=int, nargs="+", default=[1, 2, 3, 4],
        help="rule-count tiers to cycle through",
    )
    p.add_argument(
        "--alphabets", nargs="+", default=["pseudoword", "glyph", "latin"],
        choices=["pseudoword", "glyph", "latin"],
    )
    p.add_argument("--support", type=int, default=6, help="solved examples per puzzle")
    p.add_argument("--items-a", type=int, default=3)
    p.add_argument("--items-b", type=int, default=6)
    p.add_argument("--items-c", type=int, default=8)
    p.add_argument("--items-d", type=int, default=3)
    p.add_argument(
        "--agents", nargs="+", default=["oracle", "random", "identity", "align", "llm"],
        help="'llm', 'llm:<model-id>', or any of oracle/random/identity/align",
    )
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--tasks", type=str, default=None, help="path to a frozen task set JSON")
    p.add_argument("--freeze-tasks", type=str, default=None, help="write the generated task set here")
    p.add_argument("--out", type=str, default="results/run.json")
    p.add_argument("--pilot", action="store_true", help="3 universes, baselines only, fast")
    p.add_argument("--dry-run", action="store_true", help="build tasks and exit without calling agents")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    cfg = BenchmarkConfig(
        seed=args.seed,
        n_novel=3 if args.pilot else args.n_novel,
        n_familiar=1 if args.pilot else args.n_familiar,
        difficulties=tuple(args.difficulties),
        alphabet_types=tuple(args.alphabets),
        n_support=args.support,
        n_items_a=args.items_a,
        n_items_b=args.items_b,
        n_items_c=args.items_c,
        n_items_d=args.items_d,
        agents=tuple(args.agents),
        concurrency=args.concurrency,
        task_set_path=args.tasks,
    )

    if args.dry_run or args.freeze_tasks:
        # Honouring --tasks here matters: without it, inspecting a frozen set
        # silently regenerates the *default* suite instead, which is exactly the
        # kind of quiet mismatch that makes a reproduction untrustworthy.
        if args.tasks and Path(args.tasks).exists():
            from synthrule.generator import load_tasks

            tasks = load_tasks(Path(args.tasks))
            print(f"loaded {len(tasks)} frozen tasks from {args.tasks}")
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
        print(f"built {len(tasks)} tasks")
        for t in tasks:
            u = t.universe
            tag = "FAMILIAR" if u.familiar else "novel"
            print(f"  {u.uid:28s} d={u.difficulty} alpha={u.alphabet_type:10s} {tag}")
            for i, r in enumerate(u.rules, 1):
                print(f"      R{i}. {r.describe()}")
        if args.freeze_tasks:
            save_tasks(tasks, Path(args.freeze_tasks))
            print(f"frozen -> {args.freeze_tasks}")
        if args.dry_run:
            return 0

    payload = run_benchmark(cfg, verbose=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== summary ===")
    for agent, block in payload["summary"]["by_agent"].items():
        ov = block["overall"]
        line = "  ".join(f"{ph}={ov[ph]['accuracy']:.3f}" for ph in "ABCD")
        print(f"{agent:24s} {line}")
    print(f"\nwrote {out}  ({payload['summary']['n_items']} scored items)")
    if payload["summary"]["usage"]:
        print("usage:", json.dumps(payload["summary"]["usage"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
