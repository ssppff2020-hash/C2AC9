"""
SynthRule — unit tests.

Run with:  python -m pytest tests -q      (or)   python tests/test_synthrule.py

These tests exist because a benchmark whose ground truth is wrong produces
confident nonsense. The correctness of the oracle is the load-bearing
assumption of every number the suite reports, so it is tested directly rather
than assumed.

Author: Songpengfei
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from synthrule.agents import AlignAgent, IdentityAgent, OracleAgent, RandomAgent  # noqa: E402
from synthrule.generator import (  # noqa: E402
    Task,
    build_task_set,
    is_positionally_learnable,
    make_task,
    probe_inputs,
    probes_for_universe,
    validate_universe,
)
from synthrule.prompts import build_phase_a, build_phase_b, build_phase_c, build_phase_d  # noqa: E402
from synthrule.scoring import levenshtein, parse_answer, score_answer  # noqa: E402
from synthrule.universe import Rule, Universe, apply_rules  # noqa: E402


# --------------------------------------------------------------------------
# Rule execution
# --------------------------------------------------------------------------


def test_primitives():
    assert Rule("substitute", a="A", b="B").apply(["A", "C", "A"]) == ["B", "C", "B"]
    assert Rule("duplicate", a="A").apply(["A", "C"]) == ["A", "A", "C"]
    assert Rule("delete", a="A").apply(["A", "C", "A"]) == ["C"]
    assert Rule("reverse").apply(["A", "B", "C"]) == ["C", "B", "A"]
    assert Rule("reverse_if", a="A").apply(["A", "B"]) == ["B", "A"]
    assert Rule("reverse_if", a="Z").apply(["A", "B"]) == ["A", "B"]
    assert Rule("rotate_if_longer", n=2).apply(["A", "B", "C"]) == ["B", "C", "A"]
    assert Rule("rotate_if_longer", n=3).apply(["A", "B", "C"]) == ["A", "B", "C"]


def test_swap_is_simultaneous():
    """A sequential two-pass swap would return the input unchanged. This is
    the single easiest way to get silent, wrong ground truth."""
    assert Rule("swap", a="A", b="B").apply(["A", "B"]) == ["B", "A"]
    assert Rule("swap", a="A", b="B").apply(["A", "B", "A"]) == ["B", "A", "B"]


def test_apply_does_not_mutate():
    seq = ["A", "B", "C"]
    apply_rules(seq, [Rule("reverse"), Rule("delete", a="A")])
    assert seq == ["A", "B", "C"]


def test_rules_compose_in_order():
    rules = [Rule("substitute", a="A", b="B"), Rule("delete", a="B")]
    assert apply_rules(["A", "C"], rules) == ["C"]
    # Reversed order must differ -- otherwise order is not being honoured.
    assert apply_rules(["A", "C"], list(reversed(rules))) == ["B", "C"]


def test_symbols_are_units_not_characters():
    """Pseudoword alphabets must never be split into letters."""
    u = Universe(uid="t", symbols=["qa", "zo"], rules=[Rule("reverse")])
    assert u.apply(["qa", "zo"]) == ["zo", "qa"]


def _expect_value_error(fn, label):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError(f"{label} should have raised ValueError")


def test_invalid_rule_rejected():
    _expect_value_error(lambda: Rule("nonsense"), "unknown kind")
    _expect_value_error(lambda: Rule("substitute", a="A"), "substitute without b")
    _expect_value_error(lambda: Rule("delete"), "delete without a")
    _expect_value_error(lambda: Rule("rotate_if_longer"), "rotate without n")
    _expect_value_error(lambda: Rule("swap", a="A", b="A"), "swap with identical symbols")


# --------------------------------------------------------------------------
# Generator / validity gate
# --------------------------------------------------------------------------


def test_generated_universes_are_valid():
    rng = random.Random(7)
    tasks = build_task_set(
        seed=7,
        n_novel=8,
        n_familiar=3,
        difficulties=(1, 2, 3, 4),
        alphabet_types=("pseudoword", "glyph", "latin"),
        n_support=6,
        n_query=20,
    )
    assert len(tasks) == 11
    for t in tasks:
        assert validate_universe(t.universe, probes_for_universe(t.universe))
        assert len(t.universe.rules) == t.universe.difficulty


def test_identity_universe_is_rejected():
    """reverse; reverse carries no learnable signal and must not be admitted."""
    u = Universe(uid="x", symbols=["A", "B", "C"], rules=[Rule("reverse"), Rule("reverse")])
    assert not validate_universe(u, [["A", "B"], ["C", "A", "B"]])


def test_unobservable_rule_is_rejected():
    """A rule that never fires leaves no trace in the evidence."""
    # 'delete Z' cannot fire: Z is never in a sequence built from {A, B, C}.
    u = Universe(
        uid="y",
        symbols=["A", "B", "C"],
        rules=[Rule("delete", a="Z"), Rule("substitute", a="A", b="B")],
    )
    assert not validate_universe(u, [["A", "C"], ["A", "A", "C"]])


def test_positional_shortcut_is_detected():
    """A universe built only from substitution rules IS positional: the map
    fitted on some examples predicts the rest. This is the shortcut the gate
    exists to catch."""
    u = Universe(uid="pos", symbols=["A", "B", "C"], rules=[Rule("substitute", a="A", b="B")])
    probes = [["A", "C"], ["C", "A"], ["A", "A", "C"], ["B", "C", "A"], ["A", "B", "C"]]
    assert is_positionally_learnable(u, probes)


def test_generated_universes_defeat_the_positional_shortcut():
    """Every admitted universe must be non-positional, at every difficulty --
    otherwise a shallow pattern-completer can post a high score and the suite
    would be measuring pattern completion rather than rule induction."""
    tasks = build_task_set(
        seed=11, n_novel=12, n_familiar=4, difficulties=(1, 2, 3, 4),
        alphabet_types=("pseudoword", "glyph", "latin"), n_support=6, n_query=20,
    )
    for t in tasks:
        assert not is_positionally_learnable(t.universe, probes_for_universe(t.universe)), (
            f"{t.universe.uid} is solvable by a position-wise map: "
            f"{[r.describe() for r in t.universe.rules]}"
        )


def test_seed_is_deterministic():
    def build():
        return [
            (t.universe.uid, [r.signature() for r in t.universe.rules], t.support)
            for t in build_task_set(
                seed=99, n_novel=4, n_familiar=1, difficulties=(2,),
                alphabet_types=("pseudoword",), n_support=6, n_query=20,
            )
        ]

    assert build() == build()


def test_support_and_query_are_disjoint():
    rng = random.Random(3)
    tasks = build_task_set(
        seed=3, n_novel=3, n_familiar=0, difficulties=(2,),
        alphabet_types=("pseudoword",), n_support=6, n_query=20,
    )
    for t in tasks:
        s = {tuple(i) for i, _ in t.support}
        q = {tuple(i) for i, _ in t.query}
        assert not (s & q), "a query input appeared in the support set"


def _recompute(seq, rules):
    """A second, deliberately naive implementation of the rule semantics.

    Written out longhand from the English rule descriptions rather than by
    calling Rule.apply, so that the two implementations can disagree. If they
    ever do, the ground truth is wrong and every number the benchmark reports
    is wrong -- which is exactly why this test exists.
    """
    cur = list(seq)
    for r in rules:
        if r.kind == "substitute":
            cur = [r.b if x == r.a else x for x in cur]
        elif r.kind == "duplicate":
            nxt = []
            for x in cur:
                nxt.append(x)
                if x == r.a:
                    nxt.append(x)
            cur = nxt
        elif r.kind == "delete":
            cur = [x for x in cur if x != r.a]
        elif r.kind == "reverse":
            cur = list(reversed(cur))
        elif r.kind == "reverse_if":
            if r.a in cur:
                cur = list(reversed(cur))
        elif r.kind == "rotate_if_longer":
            if len(cur) > r.n:
                cur = cur[1:] + cur[:1]
        elif r.kind == "swap":
            cur = [r.b if x == r.a else (r.a if x == r.b else x) for x in cur]
        else:
            raise AssertionError(f"unhandled kind in this test: {r.kind}")
    return cur


def test_ground_truth_matches_independent_recomputation():
    """Re-derive every gold label from the rule list, independently of the
    path that produced it. Run across every alphabet and difficulty tier so
    all seven primitive kinds are exercised."""
    tasks = build_task_set(
        seed=5, n_novel=12, n_familiar=4, difficulties=(1, 2, 3, 4),
        alphabet_types=("glyph", "pseudoword", "latin"), n_support=6, n_query=20,
    )
    kinds_seen = set()
    for t in tasks:
        kinds_seen |= {r.kind for r in t.universe.rules}
        for inp, gold in t.support + t.query:
            manual = _recompute(inp, t.universe.rules)
            assert manual == gold, (t.universe.uid, inp, manual, gold)
    missing = {"substitute", "duplicate", "delete", "reverse",
               "reverse_if", "rotate_if_longer", "swap"} - kinds_seen
    assert not missing, f"these rule kinds were never exercised: {sorted(missing)}"


# --------------------------------------------------------------------------
# Parsing / scoring
# --------------------------------------------------------------------------


def test_parse_standard_forms():
    syms = ["qa", "zo", "mv"]
    assert parse_answer("blah\nANSWER: [qa, zo]", syms) == ["qa", "zo"]
    assert parse_answer("ANSWER: [qa,zo,mv]", syms) == ["qa", "zo", "mv"]
    assert parse_answer("ANSWER: [zo mv]", syms) == ["zo", "mv"]
    assert parse_answer("ANSWER: [qazomv]", syms) == ["qa", "zo", "mv"]
    assert parse_answer("ANSWER: []", syms) == []


def test_parse_takes_last_answer_line():
    """A model that revises itself must be scored on its final answer."""
    syms = ["qa", "zo"]
    text = "ANSWER: [qa]\nWait, that is wrong.\nANSWER: [zo]"
    assert parse_answer(text, syms) == ["zo"]


def test_parse_rejects_garbage():
    assert parse_answer("I do not know.", ["qa", "zo"]) is None
    assert parse_answer("", ["qa", "zo"]) is None
    assert parse_answer("ANSWER: [xx, yy]", ["qa", "zo"]) is None


def test_scoring():
    assert score_answer(["qa", "zo"], ["qa", "zo"]).exact == 1
    s = score_answer(["qa", "zo"], ["qa", "mv"])
    assert s.exact == 0 and abs(s.partial - 0.5) < 1e-9
    assert score_answer(None, ["qa"]).exact == 0
    assert score_answer(None, ["qa"]).parsed is False


def test_levenshtein():
    assert levenshtein([], []) == 0
    assert levenshtein(["a"], []) == 1
    assert levenshtein(["a", "b"], ["a", "c"]) == 1
    assert levenshtein(["a", "b", "c"], ["a", "c"]) == 1


# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------


def _toy_task() -> Task:
    u = Universe(
        uid="toy",
        symbols=["qa", "zo", "mv"],
        rules=[Rule("reverse"), Rule("substitute", a="qa", b="zo")],
        alphabet_type="pseudoword",
    )
    return make_task(u, random.Random(1), n_support=3, n_query=8)


def test_phase_prompts_leak_and_withhold_correctly():
    t = _toy_task()

    a = build_phase_a(t, 1, 3, t.query[0][0])
    assert "NOT given any solved examples" in a.user
    assert t.query[0][1] and " -> " not in a.user.split("Question")[0]

    b = build_phase_b(t, 1, 3, t.query[0][0])
    assert "Solved examples" in b.user
    assert "Reverse the entire sequence" not in b.user, "Phase B must not state the rules"

    d = build_phase_d(t, 1, 3, t.query[0][0])
    assert "Reverse the entire sequence" in d.user, "Phase D must state the rules"

    c = build_phase_c(t, 2, 3, t.query[1][0], [(t.query[0][0], "[x]", t.query[0][1])])
    assert "Your attempts so far" in c.user
    assert "Correct answer" in c.user


def test_phase_b_never_contains_a_query_answer():
    """The whole measurement collapses if a gold query label leaks into the
    prompt. Check every phase that must stay silent."""
    t = _toy_task()
    from synthrule.prompts import fmt_seq

    golds = {fmt_seq(g) for _, g in t.query}
    for builder in (build_phase_a, build_phase_b, build_phase_d):
        text = " ".join(
            builder(t, i + 1, len(t.query), inp).user
            for i, (inp, _) in enumerate(t.query)
        )
        leaked = [
            g for g in golds
            if g in text and g not in {fmt_seq(i) for i, _ in t.query}
        ]
        assert not leaked, f"{builder.__name__} leaked gold outputs: {leaked[:3]}"


# --------------------------------------------------------------------------
# Agents
# --------------------------------------------------------------------------


def test_oracle_is_perfect_and_baselines_are_not():
    from synthrule.agents import ItemContext

    t = _toy_task()
    oracle, identity, align, rnd = OracleAgent(), IdentityAgent(), AlignAgent(), RandomAgent(0)

    def ctx(inp, gold):
        return ItemContext(symbols=t.universe.symbols, inp=inp, gold=gold, support=t.support)

    hits = 0
    for inp, gold in t.query:
        raw = oracle.answer(None, ctx(inp, gold)).text  # type: ignore[arg-type]
        assert score_answer(parse_answer(raw, t.universe.symbols), gold).exact == 1
        for agent in (identity, align, rnd):
            raw = agent.answer(None, ctx(inp, gold)).text  # type: ignore[arg-type]
            scored = score_answer(parse_answer(raw, t.universe.symbols), gold)
            assert scored.parsed
            hits += scored.exact
    assert hits < len(t.query) * 3, "a baseline is scoring suspiciously well on this puzzle"


def test_align_agent_cache_is_content_keyed():
    """Regression test: the cache must key on support content, not id()."""
    from synthrule.agents import ItemContext

    agent = AlignAgent()
    c1 = ItemContext(symbols=["A", "B"], inp=["A"], gold=["B"], support=[(["A"], ["B"])])
    c2 = ItemContext(symbols=["A", "B"], inp=["A"], gold=["A"], support=[(["A"], ["A"])])
    assert agent.answer(None, c1).text != agent.answer(None, c2).text  # type: ignore[arg-type]


def test_reply_truncation_flag():
    """`truncated` is what keeps 'the model failed' distinct from 'we cut the
    model off'. Getting this wrong produced a fabricated floor effect in our
    own first pilot, so it is pinned by a test."""
    from synthrule.agents import Reply

    assert Reply("x", stop_reason="max_tokens").truncated is True
    assert Reply("x", stop_reason="end_turn").truncated is False
    # A truncated reply that still emitted text is still flagged -- the answer
    # may be complete by luck, but the run should record that it was cut off.
    assert Reply("ANSWER: [a]", stop_reason="max_tokens").truncated is True


def test_truncated_responses_are_counted_in_summary():
    """A run whose responses were cut off must say so in its own summary."""
    from synthrule.runner import ItemResult, _proportion

    def mk(truncated: bool, exact: int, parsed: bool) -> ItemResult:
        return ItemResult(
            agent="llm", task_uid="t", phase="B", difficulty=1,
            alphabet_type="pseudoword", familiar=False, index=0,
            inp=["a"], gold=["b"], predicted=["b"] if parsed else None, raw="",
            exact=exact, partial=float(exact), parsed=parsed, latency_s=0.0,
            truncated=truncated,
        )

    stats = _proportion([mk(True, 0, False), mk(True, 0, False), mk(False, 1, True)])
    assert stats["truncated"] == 2
    assert stats["unparsed"] == 2
    assert stats["correct"] == 1
    assert stats["n"] == 3


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)
