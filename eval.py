"""Evaluation harness for the Pet Care Advisor.

Runs the advisor on a fixed set of scenarios and scores each on:
  - groundedness  — at least one expected source was retrieved
  - on_topic      — advisor returned a real answer (not the low-confidence refusal)
                    when we expected it to, and refused when we expected refusal
  - critic_pass   — the self-critic accepted the draft
  - keyword_check — answer contains expected keywords (when applicable)

Run:
    python eval.py
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field

from rag import PetCareAdvisor

# Delay between scenarios to stay under free-tier rate limits (5 req/min on
# gemini-2.5-flash; each scenario costs up to 2 generative calls).
INTER_SCENARIO_DELAY_S = 14


@dataclass
class Scenario:
    name: str
    question: str
    expect_refusal: bool = False         # True for out-of-scope / low-confidence cases
    expected_sources: list[str] = field(default_factory=list)
    expected_keywords: list[str] = field(default_factory=list)
    require_vet_redirect: bool = False   # safety scenarios must mention vet


SCENARIOS: list[Scenario] = [
    Scenario(
        name="husky_exercise",
        question="How long should I walk a Husky?",
        expected_sources=["dogs_exercise"],
        expected_keywords=["90", "120", "high-energy"],
    ),
    Scenario(
        name="kitten_feeding",
        question="How many times a day should I feed a 3-month-old kitten?",
        expected_sources=["kittens"],
        expected_keywords=["3", "4"],
    ),
    Scenario(
        name="puppy_exercise_rule",
        question="How much exercise does a 4-month-old puppy need?",
        expected_sources=["puppies", "dogs_exercise"],
        expected_keywords=["5 minutes", "month"],
    ),
    Scenario(
        name="chocolate_emergency",
        question="My dog ate chocolate, what should I do?",
        expected_sources=["safety_emergencies", "dogs_feeding"],
        require_vet_redirect=True,
    ),
    Scenario(
        name="off_topic_refusal",
        question="What is the capital of France?",
        expect_refusal=True,
    ),
    Scenario(
        name="long_haired_cat_grooming",
        question="How often should I brush a Maine Coon?",
        expected_sources=["grooming", "cats_care"],
        expected_keywords=["3", "5"],
    ),
]


REFUSAL_MARKERS = ("don't have reliable information", "consult a licensed veterinarian", "I don't have")
VET_MARKERS = ("vet", "veterinarian", "poison")


def score_scenario(s: Scenario, result: dict) -> dict:
    answer = result["answer"].lower()
    sources = result["sources"]
    low_conf = result["low_confidence"]
    critic_pass = result["critique_passed"]

    checks = {}

    # 1. Refusal expectation
    if s.expect_refusal:
        checks["refusal_correct"] = low_conf or any(m.lower() in answer for m in REFUSAL_MARKERS)
    else:
        checks["refusal_correct"] = not low_conf

    # 2. Groundedness — expected sources retrieved
    if s.expected_sources:
        checks["groundedness"] = any(src in sources for src in s.expected_sources)
    else:
        checks["groundedness"] = True  # N/A for refusal scenarios

    # 3. Keyword presence
    if s.expected_keywords:
        checks["keywords"] = all(kw.lower() in answer for kw in s.expected_keywords)
    else:
        checks["keywords"] = True

    # 4. Vet redirect for safety
    if s.require_vet_redirect:
        checks["vet_redirect"] = any(m in answer for m in VET_MARKERS)
    else:
        checks["vet_redirect"] = True

    # 5. Critic
    checks["critic_pass"] = critic_pass

    checks["overall_pass"] = all(checks.values())
    return checks


def main() -> int:
    print("=" * 70)
    print("PawPal+ Pet Care Advisor — Evaluation Harness")
    print("=" * 70)

    advisor = PetCareAdvisor()
    print(f"\nLoaded advisor. Running {len(SCENARIOS)} scenarios...\n")

    results = []
    for i, s in enumerate(SCENARIOS):
        if i > 0:
            time.sleep(INTER_SCENARIO_DELAY_S)
        print(f"--- {s.name} ---")
        print(f"Q: {s.question}")
        result = advisor.ask(s.question)
        checks = score_scenario(s, result)
        results.append((s, result, checks))

        verdict = "PASS" if checks["overall_pass"] else "FAIL"
        print(f"Verdict: {verdict}")
        print(f"  Refusal correct: {checks['refusal_correct']}")
        print(f"  Groundedness:    {checks['groundedness']}")
        print(f"  Keywords:        {checks['keywords']}")
        print(f"  Vet redirect:    {checks['vet_redirect']}")
        print(f"  Critic pass:     {checks['critic_pass']}")
        print(f"  Sources:         {result['sources']}")
        print(f"  Answer (truncated): {result['answer'][:160]}...")
        print()

    # Summary
    passed = sum(1 for _, _, c in results if c["overall_pass"])
    total = len(results)

    print("=" * 70)
    print(f"SUMMARY: {passed}/{total} scenarios passed")
    print("=" * 70)

    # Per-check pass rates
    check_keys = ["refusal_correct", "groundedness", "keywords", "vet_redirect", "critic_pass"]
    for key in check_keys:
        rate = sum(1 for _, _, c in results if c[key]) / total
        print(f"  {key:18s} {rate * 100:5.1f}%  ({sum(1 for _, _, c in results if c[key])}/{total})")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
