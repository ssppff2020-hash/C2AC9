"""
SynthRule — procedural task generation.

Two properties are generated rather than curated, and both matter:

**Novelty (anti-contamination).**  Every universe is sampled at run time from
a random seed: a fresh symbol alphabet, a fresh rule list, a fresh composition
order.  Nothing about a generated puzzle is retrievable from a pre-training
corpus, because the puzzle did not exist until the seed was drawn.  We make no
stronger claim than that -- see `docs` in README for the honest boundary.

**Identifiability (anti-unfairness).**  A generated puzzle is only admitted if
*every* rule in it is observable: removing rule i must change the output of at
least one support example.  Without this filter the benchmark would sometimes
ask the model to infer a rule that leaves no trace in the evidence, i.e. to
guess the unguessable.  `validate_universe` is the gate.

Author: Songpengfei
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .universe import ALPHABET_POOLS, RULE_KINDS, Rule, Universe, apply_rules

# A sequence is a list of symbols.
Seq = List[str]
Pair = Tuple[Seq, Seq]

# Rules that are *not* expressible as a fixed symbol-at-each-position mapping.
# These change the order or the length of the sequence, so a purely positional
# strategy cannot imitate them. See `is_positionally_learnable`.
NON_POSITIONAL_KINDS = (
    "delete",
    "duplicate",
    "reverse",
    "reverse_if",
    "rotate_if_longer",
)


# --------------------------------------------------------------------------
# Sampling helpers
# --------------------------------------------------------------------------


def sample_symbols(rng: random.Random, alphabet_type: str, k: int) -> Seq:
    pool = ALPHABET_POOLS.get(alphabet_type)
    if pool is None:
        raise ValueError(
            f"unknown alphabet_type {alphabet_type!r}; "
            f"expected one of {sorted(ALPHABET_POOLS)}"
        )
    return rng.sample(pool, k)


def random_rule(
    rng: random.Random,
    symbols: Sequence[str],
    existing: Sequence[Rule],
    allowed_kinds: Sequence[str] = RULE_KINDS,
) -> Optional[Rule]:
    """Draw one rule that is not a duplicate of, or trivially cancelling with,
    what is already in the list."""
    kinds = [k for k in allowed_kinds if k != "swap" or len(symbols) >= 2]
    for _ in range(24):
        kind = rng.choice(kinds)
        a = rng.choice(symbols)
        b: Optional[str] = None
        n: Optional[int] = None

        if kind == "substitute":
            b = rng.choice([s for s in symbols if s != a])
        elif kind == "swap":
            b = rng.choice([s for s in symbols if s != a])
            # Canonicalise so swap(a,b) == swap(b,a) for de-duplication.
            if b < a:
                a, b = b, a
        elif kind == "rotate_if_longer":
            # n is capped at 3 on purpose: task items are 2-5 symbols long, and
            # a threshold of 4 would leave the rule dormant on most items,
            # making the universe nearly degenerate.
            n = rng.choice([2, 3])

        cand = Rule(kind=kind, a=a, b=b, n=n)

        if any(cand.signature() == e.signature() for e in existing):
            continue
        # Reject a rule that immediately undoes its predecessor: the pair
        # carries no learnable signal.
        if existing:
            prev = existing[-1]
            if _cancels(prev, cand):
                continue
        return cand
    return None


def _cancels(p: Rule, q: Rule) -> bool:
    """True for adjacent pairs whose composition is always the identity."""
    if p.kind == "reverse" and q.kind == "reverse":
        return True
    if p.kind == "swap" and q.kind == "swap" and p.a == q.a and p.b == q.b:
        return True
    if p.kind == "reverse_if" and q.kind == "reverse_if" and p.a == q.a:
        return True
    if p.kind == "delete" and q.kind == "delete" and p.a == q.a:
        return True
    return False


# --------------------------------------------------------------------------
# Validity gate
# --------------------------------------------------------------------------


def probe_inputs(rng: random.Random, symbols: Sequence[str], n: int = 60) -> List[Seq]:
    """Random sequences used only for validation, never shown to a model.

    Lengths mirror the task-item distribution (2-5) so that validity is judged
    against the same inputs the benchmark will actually pose.
    """
    out: List[Seq] = []
    seen = set()
    for _ in range(n * 3):
        length = rng.randint(2, 5)
        s = [rng.choice(list(symbols)) for _ in range(length)]
        key = tuple(s)
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= n:
            break
    return out


def probes_for_universe(u: Universe, n: int = 60) -> List[Seq]:
    """A probe set that depends only on the universe's content.

    Nothing may draw these from the ambient RNG. If validity depended on which
    probes happened to be sampled during generation, then a universe could
    pass at generation time and fail on re-validation -- and a third party
    re-running the suite would get different puzzles. Seeding from the
    universe's fingerprint makes admission a pure function of the universe.
    """
    digest = hashlib.sha256(u.fingerprint().encode("utf-8")).hexdigest()
    return probe_inputs(random.Random(int(digest[:16], 16)), u.symbols, n)


def validate_universe(u: Universe, probes: Sequence[Seq]) -> bool:
    """Admit a universe only if it is well-posed.

    Checks, in order:

    1. The composition is not the identity on every probe (rejects e.g.
       ``reverse; reverse`` -- a puzzle with nothing in it).
    2. Every rule is *observable*: ablating rule i changes at least one output.
       Rules failing this are unlearnable and would make the task unfair.
    3. The transformation actually does something on a decent share of probes,
       so the task is not near-degenerate.
    """
    if not u.rules:
        return False

    base = [apply_rules(p, u.rules) for p in probes]

    # (1) not the identity everywhere
    if all(list(p) == o for p, o in zip(probes, base)):
        return False

    # (2) every rule individually observable
    for i in range(len(u.rules)):
        ablated = list(u.rules[:i]) + list(u.rules[i + 1 :])
        if all(apply_rules(p, ablated) == b for p, b in zip(probes, base)):
            return False

    # (3) non-degeneracy: at least a third of probes are actually rewritten
    changed = sum(1 for p, o in zip(probes, base) if list(p) != o)
    return changed >= max(1, len(probes) // 3)


def _align_predict(inp: Sequence[str], mapping: Dict[str, str]) -> List[str]:
    """Exactly the strategy `AlignAgent` uses: rewrite each position in place."""
    return [mapping.get(t, t) for t in inp]


def _learn_positional_map(pairs: Sequence[Pair]) -> Dict[str, str]:
    counts: Dict[str, Counter] = {}
    for inp, out in pairs:
        for a, b in zip(inp, out):
            counts.setdefault(a, Counter())[b] += 1
    return {a: c.most_common(1)[0][0] for a, c in counts.items()}


def is_positionally_learnable(u: Universe, probes: Sequence[Seq]) -> bool:
    """Can a position-wise symbol map, fitted on some examples, generalise?

    This is the anti-shortcut gate, and it is the most important validity
    check in the generator.

    A puzzle built only from ``substitute`` and ``swap`` rules is solvable by
    memorising "symbol X at this position becomes Y" -- a shallow statistical
    fit with no representation of rule order, conditions, or length change.
    Such a puzzle measures pattern completion, not rule induction, so it is
    rejected. The check is deliberately behavioural: we fit the positional map
    on half the probes and ask whether it predicts the other half. If it does,
    the puzzle offers a shortcut and does not belong in a Learning benchmark.
    """
    pairs = [(list(p), u.apply(p)) for p in probes]
    if len(pairs) < 4:
        return True
    split = len(pairs) // 2
    mapping = _learn_positional_map(pairs[:split])
    holdout = pairs[split:]
    return all(_align_predict(i, mapping) == o for i, o in holdout)


def accepts(u: Universe, require_non_positional: bool = True) -> bool:
    """The full admission gate for a generated universe. Pure: same universe,
    same verdict, regardless of when or where it is called."""
    probes = probes_for_universe(u)
    if not validate_universe(u, probes):
        return False
    if require_non_positional and is_positionally_learnable(u, probes):
        return False
    return True


def _sample_rule_list(
    rng: random.Random,
    symbols: Sequence[str],
    difficulty: int,
    allowed_kinds: Sequence[str],
    force_non_positional: bool,
) -> Optional[List[Rule]]:
    """Draw `difficulty` rules, guaranteeing at least one non-positional rule
    at a random position when asked."""
    forced_at = rng.randrange(difficulty) if (force_non_positional and difficulty) else -1
    rules: List[Rule] = []
    for idx in range(difficulty):
        kinds = allowed_kinds
        if idx == forced_at:
            kinds = [k for k in allowed_kinds if k in NON_POSITIONAL_KINDS]
            if not kinds:
                return None
        r = random_rule(rng, symbols, rules, allowed_kinds=kinds)
        if r is None:
            return None
        rules.append(r)
    return rules


def generate_universe(
    rng: random.Random,
    difficulty: int,
    alphabet_type: str,
    uid: str,
    max_attempts: int = 2000,
    require_non_positional: bool = True,
) -> Universe:
    """Sample a valid universe, retrying until the validity gate passes."""
    for _ in range(max_attempts):
        k = rng.choice([3, 4, 5])
        symbols = sample_symbols(rng, alphabet_type, k)
        rules = _sample_rule_list(
            rng, symbols, difficulty, RULE_KINDS, require_non_positional
        )
        if rules is None:
            continue
        u = Universe(
            uid=uid,
            symbols=symbols,
            rules=rules,
            alphabet_type=alphabet_type,
            difficulty=difficulty,
        )
        if accepts(u, require_non_positional):
            return u
    raise RuntimeError(
        f"could not generate a valid universe "
        f"(difficulty={difficulty}, alphabet={alphabet_type})"
    )


# --------------------------------------------------------------------------
# Contamination probe
# --------------------------------------------------------------------------

# Deliberately "textbook" transformations: reversal and adjacent swapping over
# plain Latin letters are the canonical examples of a rewrite rule that a large
# model has almost certainly seen described.  A model that scores substantially
# higher here than on procedurally generated universes of equal difficulty is
# showing a retrieval advantage, not a learning advantage.
FAMILIAR_KINDS = ("reverse", "swap", "substitute", "rotate_if_longer")


def generate_familiar_universe(
    rng: random.Random,
    difficulty: int,
    uid: str,
    max_attempts: int = 2000,
    require_non_positional: bool = True,
) -> Universe:
    for _ in range(max_attempts):
        symbols = sample_symbols(rng, "latin", rng.choice([3, 4]))
        rules = _sample_rule_list(
            rng, symbols, difficulty, FAMILIAR_KINDS, require_non_positional
        )
        if rules is None:
            continue
        u = Universe(
            uid=uid,
            symbols=symbols,
            rules=rules,
            alphabet_type="latin",
            difficulty=difficulty,
            familiar=True,
        )
        if accepts(u, require_non_positional):
            return u
    raise RuntimeError(f"could not generate a familiar universe (difficulty={difficulty})")


# --------------------------------------------------------------------------
# Task assembly
# --------------------------------------------------------------------------


@dataclass
class Task:
    """A universe plus disjoint support (shown) and query (scored) item sets."""

    universe: Universe
    support: List[Pair] = field(default_factory=list)
    query: List[Pair] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "universe": self.universe.to_dict(),
            "support": [{"input": i, "output": o} for i, o in self.support],
            "query": [{"input": i, "output": o} for i, o in self.query],
        }

    @staticmethod
    def from_dict(d: Dict[str, object]) -> "Task":
        return Task(
            universe=Universe.from_dict(d["universe"]),  # type: ignore[arg-type]
            support=[(list(p["input"]), list(p["output"])) for p in d["support"]],  # type: ignore[index]
            query=[(list(p["input"]), list(p["output"])) for p in d["query"]],  # type: ignore[index]
        )


def make_task(
    universe: Universe,
    rng: random.Random,
    n_support: int,
    n_query: int,
    min_len: int = 2,
    max_len: int = 5,
    min_active_frac: float = 0.6,
) -> Task:
    """Build disjoint support/query item sets over `universe`.

    Two properties are enforced.

    *Disjointness.* Support inputs and query inputs never overlap, so a correct
    query answer cannot be reached by lookup -- only by having induced the
    rule list.

    *Activeness.* At least `min_active_frac` of items must be changed by the
    rules. Conditional rules such as ``reverse_if`` leave the sequence alone
    when their trigger is absent, and if too many items are inactive then
    echoing the input becomes a viable strategy and the usable scoring range
    collapses. Items are also shuffled, so the Phase-C early/late comparison
    cannot be confounded by activeness.
    """
    used: set = set()

    def draw(n: int) -> List[Pair]:
        out: List[Pair] = []
        for _ in range(n * 80):
            if len(out) >= n:
                break
            length = rng.randint(min_len, max_len)
            s = [rng.choice(universe.symbols) for _ in range(length)]
            key = tuple(s)
            if key in used:
                continue
            used.add(key)
            out.append((s, universe.apply(s)))
        return out

    def select(n: int) -> List[Pair]:
        pool = draw(n * 4 + 8)
        if len(pool) < n:
            raise RuntimeError("exhausted symbol space while building task items")
        active = [p for p in pool if p[0] != p[1]]
        inactive = [p for p in pool if p[0] == p[1]]
        need = min(len(active), max(1, math.ceil(n * min_active_frac)))
        chosen = active[:need]
        rest = inactive + active[need:]
        rng.shuffle(rest)
        chosen += rest[: n - len(chosen)]
        rng.shuffle(chosen)  # order must not correlate with activeness
        return chosen

    return Task(universe=universe, support=select(n_support), query=select(n_query))


def build_task_set(
    seed: int,
    n_novel: int,
    n_familiar: int,
    difficulties: Sequence[int],
    alphabet_types: Sequence[str],
    n_support: int,
    n_query: int,
) -> List[Task]:
    """Deterministically build the full suite from a single integer seed.

    The same seed always yields byte-identical tasks, which is what makes the
    reported numbers reproducible by a third party.
    """
    rng = random.Random(seed)
    tasks: List[Task] = []

    for i in range(n_novel):
        diff = difficulties[i % len(difficulties)]
        alpha = alphabet_types[i % len(alphabet_types)]
        u = generate_universe(rng, diff, alpha, uid=f"novel-{i:03d}-d{diff}-{alpha}")
        tasks.append(make_task(u, rng, n_support, n_query))

    for i in range(n_familiar):
        diff = difficulties[i % len(difficulties)]
        u = generate_familiar_universe(rng, diff, uid=f"familiar-{i:03d}-d{diff}")
        tasks.append(make_task(u, rng, n_support, n_query))

    return tasks


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------


def save_tasks(tasks: Sequence[Task], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "tasks": [t.to_dict() for t in tasks]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_tasks(path: Path) -> List[Task]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [Task.from_dict(d) for d in payload["tasks"]]
