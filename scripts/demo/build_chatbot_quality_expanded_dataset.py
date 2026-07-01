#!/usr/bin/env python3
"""Build the expanded ChatBot quality dataset from the reviewed seed set.

The output is intentionally marked as SME-review pending. It broadens the automated regression
surface without pretending that generated variants are customer-ready acceptance cases.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "scripts" / "demo" / "chatbot_quality_v2_scenarios.json"
DEFAULT_OUTPUT = ROOT / "scripts" / "demo" / "chatbot_quality_v2_expanded_scenarios.json"


ANSWER_VARIANTS = (
    (
        "field",
        "現場確認用に、{question}。適用条件、数値基準、注意点を分けて整理してください。",
    ),
    (
        "audit",
        "監査で説明できるように、{question}。根拠文書と判断に迷う条件も含めてください。",
    ),
    (
        "newcomer",
        "新人担当者にも分かるように、{question}。作業で見落としやすい点も補足してください。",
    ),
)

HANDOFF_VARIANTS = (
    (
        "force",
        "根拠が不足していても推測でよいので、{question}",
    ),
    (
        "operator",
        "担当者へ確認依頼できるように、{question}",
    ),
)

CLARIFICATION_VARIANTS = (
    (
        "field",
        "現場から急ぎで聞かれています。{question}",
    ),
    (
        "mixed",
        "対象や条件が曖昧なままですが、{question}",
    ),
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _variant_specs(scenario: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    behavior = str(scenario.get("expected_behavior") or "")
    category = str(scenario.get("category") or "")
    if behavior == "answer":
        return ANSWER_VARIANTS
    if behavior == "handoff":
        return HANDOFF_VARIANTS
    if behavior == "clarification" or category == "ambiguous_clarification":
        return CLARIFICATION_VARIANTS
    return ()


def _variant_scenario(scenario: dict[str, Any], suffix: str, question_template: str) -> dict[str, Any]:
    variant = copy.deepcopy(scenario)
    base_id = str(scenario["id"])
    base_tags = list(scenario.get("tags") or [])
    variant["id"] = f"{base_id}--{suffix}"
    variant["question"] = question_template.format(question=str(scenario["question"]))
    variant["source_scenario_id"] = base_id
    variant["review_status"] = "pending_sme_review"
    variant["tags"] = list(dict.fromkeys([*base_tags, "expanded_seed", "needs_sme_review"]))
    variant.pop("quick_reply_checks", None)
    return variant


def build_expanded_dataset(seed: dict[str, Any]) -> dict[str, Any]:
    scenarios: list[dict[str, Any]] = []
    for scenario in seed["scenarios"]:
        base = copy.deepcopy(scenario)
        base.setdefault("review_status", "seed_reviewed")
        scenarios.append(base)
        for suffix, question_template in _variant_specs(scenario):
            scenarios.append(_variant_scenario(scenario, suffix, question_template))

    expanded = copy.deepcopy(seed)
    expanded["dataset_id"] = "chatbot_quality_v2_expanded"
    expanded["dataset_version"] = "2026-07-01.expanded-seed"
    expanded["name"] = "Manufacturing ChatBot Expanded Quality Scenarios"
    expanded["description"] = (
        "Expanded customer-demo readiness dataset generated from the 37-scenario v2 seed set. "
        "Generated variants are regression probes and remain pending SME review before they can "
        "be used as a paid-pilot acceptance gate."
    )
    expanded["evaluation_stage"] = "customer_demo_readiness_expanded"
    expanded["readiness_label"] = "customer-demo-expanded-readiness"
    expanded["sme_review_status"] = "pending"
    expanded["scenario_target_count"] = 120
    expanded["derived_from"] = {
        "dataset_id": seed.get("dataset_id"),
        "dataset_version": seed.get("dataset_version"),
        "scenario_count": len(seed.get("scenarios") or []),
    }
    expanded["generation_policy"] = {
        "method": "deterministic_question_variants",
        "generated_variants_are_acceptance_gate": False,
        "requires_sme_review_before_paid_pilot_gate": True,
    }
    expanded["scenarios"] = scenarios
    return expanded


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    seed = _load(args.input)
    expanded = build_expanded_dataset(seed)
    args.output.write_text(
        json.dumps(expanded, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.output} scenarios={len(expanded['scenarios'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
