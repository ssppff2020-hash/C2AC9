# SynthRule

**A benchmark for measuring genuine learning in language models.**

Track 1 — Learning · Google DeepMind × Kaggle, *Measuring Progress Toward AGI: Cognitive Abilities*
Author: **Songpengfei** · Version 1.0.0

---

## The question

When a model answers a few-shot prompt correctly, has it **learned** something — or has it
**retrieved** something?

These two explanations predict the same behaviour on almost every benchmark we have, and they
mean completely different things for how close we are to AGI. SynthRule is built to pull them
apart.

The design commits to one hard requirement: **the answer must be provably unavailable before the
model sees the examples.** Everything else follows from that.

## The task

Each puzzle is a *rule universe*: a small symbol alphabet plus an ordered list of 1–4 rewriting
rules drawn from a fixed grammar of seven primitives (substitute, duplicate, delete, reverse,
conditional reverse, conditional rotate, swap).

The model is shown six solved examples and must apply the same rules to a fresh, held-out input:

```
Puzzle symbols: zo, ke, ru, fa

Solved examples for THIS puzzle:
  [zo, ke, ru]      ->  [ru, ke, zo]
  [fa, zo, ke, ru]  ->  [ru, ke, zo, fa]
  [ke, ru, fa]      ->  [fa, ru, ke]
  ...

Question: [fa, ke, ru, zo]  ->  ?
```

**The answer is not in any pre-training corpus**, because the universe did not exist until the
seed was drawn. Symbols, rules, and their order are all sampled at run time.

Rule grammar is disclosed; the rules themselves never are. This keeps the task well-posed — a low
score means induction failed, not that the model guessed a different ontology — while leaving the
entire induction problem intact.

## Four phases, and why each exists

| Phase | What the model gets | What it measures |
|---|---|---|
| **A** | no examples | the prior-only floor |
| **B** | 6 solved examples | **learning** |
| **C** | examples + running corrections | learning from feedback (KSTAR `ΔR → K`) |
| **D** | the rules stated in English | the execution ceiling |

The whole design hinges on Phase D.

**Induction Gap = acc(D) − acc(B)** is the headline number. A model whose gap is near zero can
both execute and induce. A model that aces D while stalling on B is executing fine and failing to
learn — precisely the failure mode a Learning benchmark exists to expose. Without D, those two
models are indistinguishable.

Phase C operationalises the KSTAR loop literally. The model acts, is shown the true result, and
the discrepancy is the only new information it receives. If accuracy on later items does not exceed
earlier items, the model is restating its first guess rather than updating its knowledge.

## Metrics

| Metric | Definition | Reads as |
|---|---|---|
| `learning_gain` | acc(B) − acc(A) | what the examples were worth |
| `feedback_gain` | acc(late C) − acc(early C) | whether corrections changed behaviour |
| `induction_gap` | acc(D) − acc(B) | can it *execute* what it cannot *induce*? |
| `familiar_delta` | acc(B\|familiar) − acc(B\|novel) | contamination probe (below) |

Uncertainty: Wilson score intervals for proportions (correct at the small `n` this suite runs at),
bootstrap intervals for differences of means.

## Three anti-gaming mechanisms

A benchmark is only as good as the shortcuts it closes. SynthRule closes three.

**1. Procedural novelty.** Universes are generated, never curated. Seeds are published so every
number is reproducible, but a fresh seed produces puzzles no model has seen.

**2. The positional-shortcut gate.** A puzzle built only from `substitute` and `swap` rules is
solvable by memorising "symbol X at this position becomes Y" — pattern completion wearing the
costume of learning. Our own first pilot proved this is not hypothetical: a trivial position-mapper
scored 0.75. The generator now *rejects* any universe whose rules a position-wise map can imitate,
verified behaviourally by fitting the map on half the probes and testing on the other half.

**3. The identifiability gate.** A rule that leaves no trace in the examples is unlearnable. Any
universe where ablating a rule changes no support output is rejected as unfair.

A fourth check guards against a subtler issue: at least 60% of items must actually be *changed* by
the rules. Conditional rules such as `reverse_if` leave many sequences alone, and if too many items
are inactive, echoing the input becomes a viable strategy.

## Contamination probe

Pre-training contamination cannot be proved absent, so SynthRule tries to *detect* it rather than
claim immunity. A subset of universes uses plain Latin letters and deliberately textbook rules
(reversal, adjacent swap) — transformations a large model has almost certainly seen described.

If a model scores substantially higher on familiar universes than on procedurally generated ones of
equal difficulty, it is showing a retrieval advantage. The gap is reported as `familiar_delta`.

## Reference baselines

Every model score is anchored between computable reference points:

| Baseline | Strategy | Expected |
|---|---|---|
| `oracle` | consults the ground-truth solver | **1.000** — anything else means the harness is broken |
| `random` | samples from the alphabet | ≈ 0 |
| `identity` | echoes the input | ≈ 0 (near-ceiling of the activeness filter) |
| `align` | position-wise majority substitution | low — the bar a real inducer must clear |

## Results

Measured on `deepseek-v4-flash`, 14 frozen universes, exact-match accuracy.
Raw figures count truncated items as wrong; the bracketed figure excludes them.

| Phase | Main (1–4 rules, 6 examples) | Hard (4–6 rules, 4 examples) |
|---|---|---|
| A — prior only | 7.1% | 0.0% |
| **B — induction** | **88.1%** (96.1%) | **57.5%** (79.3%) |
| C — feedback | 87.5% (96.1%) | 60.0% (80.0%) |
| D — explicit rules | **100.0%** | **100.0%** |
| **Induction gap (D−B)** | **+0.119** [+0.04, +0.21] | **+0.425** [+0.28, +0.60] |
| `oracle` check | 100.0% ✓ | 100.0% ✓ |
| worst non-LLM baseline | 11.9% | 12.5% |

Reading the two rows together is the point: **the same model executes perfectly (D=100%)
and induces imperfectly (B=88% / 58%)**. With easy puzzles the gap nearly vanishes; with
hard ones it opens to 0.425. That gap is the failure mode a Learning benchmark exists to
measure, and it is invisible to any protocol without a Phase-D control.

The main run hits a **ceiling** (96.1% answered-only), so it has little discrimination
headroom; the hard run lands in the intended 20–80% band. Full data in
`results/` and `../Songpengfei_C9_测试结果.md`.

## Status and limitations

This is a working benchmark, not a finished one. Stated plainly:

- **One model tested.** Cross-model discrimination is *not* demonstrated — only that the
  suite has headroom to discriminate.
- **The contamination probe is inconclusive.** `familiar_delta` was −0.067 in the main run
  and +0.167 in the hard run — opposite signs, on 10–24 items per condition. Report it as
  underpowered, not as evidence either way.
- **Reasoning models truncate.** 6.1% of main-run and 18.8% of hard-run items hit
  `max_tokens` and were scored 0, so hard-mode difficulty is partly a harness artifact.
  Both raw and answered-only figures are always reported.
- **Novelty is argued, not proved.** Procedural generation makes memorising *this puzzle*
  impossible; it says nothing about the *rule grammar*'s presence in pre-training.
- **No human data.** The protocol and predicted distribution are specified in the proposal;
  participants were not recruited.

## Install and run

```bash
pip install -r requirements.txt

# Unit tests — no network needed
python tests/test_synthrule.py

# Inspect generated puzzles without calling any model
python run_benchmark.py --dry-run

# Freeze a task set for exact third-party reproduction
python run_benchmark.py --freeze-tasks data/tasks_seed20260931.json --dry-run

# Re-run the exact frozen puzzles
python run_benchmark.py --tasks data/tasks_seed20260931.json --agents oracle align llm

# Full run
python run_benchmark.py --n-novel 10 --n-familiar 4 \
    --agents oracle random identity align llm --out results/full.json
```

Model configuration is read from the environment:

```bash
export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
export ANTHROPIC_AUTH_TOKEN=...
export ANTHROPIC_MODEL=deepseek-v4-flash
```

## Layout

```
run_benchmark.py          CLI entry point
synthrule/
  universe.py             rule language + deterministic executor (ground truth)
  generator.py            procedural construction, the three validity gates, contamination probe
  prompts.py              the four protocol phases
  agents.py               reference baselines + LLM adapter
  scoring.py              answer parsing, exact + partial credit
  runner.py               orchestration, metrics, confidence intervals
tests/test_synthrule.py   25 tests
configs/                  example configuration
data/                     frozen task sets
results/                  run outputs
```

## Correctness of the ground truth

Every number this benchmark reports rests on the rule executor being right. So it is verified by
**two independent implementations**: `Rule.apply` in `universe.py`, and a longhand
transcription of the English rule descriptions in the test suite. The tests assert they agree on
every generated item, across all three alphabets and all four difficulty tiers. Two specific traps
are pinned by dedicated tests: a sequential `swap` would silently cancel itself, and pseudoword
symbols must never be split into letters.

## Known limitations

Stated plainly, because a benchmark that oversells itself is worse than a modest one.

- **Novelty is argued, not proved.** Procedural generation makes memorisation of *this specific
  puzzle* impossible; it does not prove the *rule grammar* is unrepresented in pre-training. The
  contamination probe measures the residual risk; it does not eliminate it.
- **Glyph alphabets carry a tokenization confound.** Unusual symbols may be hard to perceive
  rather than hard to reason about. The `pseudoword` alphabet exists as the clean comparison, and
  results are reported per alphabet so the confound is visible rather than hidden.
- **Exact-match scoring is strict.** One wrong symbol scores zero. Partial credit is reported
  alongside to keep the signal graded.
- **The human baseline is specified, not collected.** Section 3 of the proposal gives the protocol
  and the predicted distribution; running it needs participants, which was outside this scope.

## References

See `../Songpengfei_C9_拿来说明.md` for the full attribution ledger, including what was borrowed
from each source and what was deliberately discarded.

## License

Released for the DeepMind × Kaggle challenge and the Elite 20 programme.
