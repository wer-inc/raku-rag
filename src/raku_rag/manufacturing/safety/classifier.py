"""T016 — RuleHighRiskClassifier (FR-MFG-015, research R2; contracts/mfg-interfaces.md §3).

3-stage cascade with OR-logic and fail-safe ("迷えば high-risk"):

  (1) METADATA — any candidate document carrying a safety/quality/equipment-operation classification
      tag, hazard_tags, or a process_id/equipment_id that anchors physical work => high-risk.
  (2) RULE + KEYWORD — the query (and the optional structured ``intent_hint``) matches a labeled
      dangerous-intent keyword set (stop/disassemble/electrocution/high-temp/pressure/chemical/heavy/
      safety-device/quality-judgement/shipment/customer-impact/corrective).
  (3) LLM (ambiguous only) — only when stages (1)+(2) found nothing AND the query is too short / vague
      to rule danger out do we consult the reused 001 ``LLMProvider``. If it cannot confidently rule
      danger out, we FAIL SAFE to high-risk.

Any stage hitting => ``is_high_risk=True`` (OR). Ambiguous => ``True`` (fail-safe). The returned
``HighRiskClassification`` carries ``reason_codes`` (the labels that fired) and the
``classification_source`` of the FIRST stage that fired (metadata > rule/keyword > llm), so audit /
telemetry can attribute the decision (FR-MFG-021).

stdlib only; mirrors the existing services/* style. No new security mechanism — this only LABELS the
query; the SafetyGate (§4) is what enforces the approved-citation requirement on a high-risk answer.
"""

from __future__ import annotations

import json
from typing import Callable, Mapping, Sequence

from raku_rag.interfaces.base import LLMProvider
from raku_rag.manufacturing.domain.metadata import ManufacturingDocumentMetadata
from raku_rag.manufacturing.domain.safety import ClassificationSource, HighRiskClassification

# --- (2) labeled dangerous-intent keyword sets -----------------------------------------------------
# reason_code -> tuple of substrings (lower-cased) that, if present in the query/intent_hint, mark
# that danger class. Both English (field tools localize) and Japanese surface forms are covered so a
# bilingual field worker's question is caught. A single hit => high-risk (FR-MFG-015 recall on danger).
_INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "equipment_stop": (
        "stop the",
        "stop line",
        "stop machine",
        "shut down",
        "shutdown",
        "halt",
        "停止",
        "止め",
        "non-stop",
        "clear a jam",
        "clear the jam",
    ),
    "disassembly": (
        "disassemble",
        "dismantle",
        "take apart",
        "remove the guard",
        "removing any guard",
        "remove guard",
        "分解",
        "取り外",
        "取外",
    ),
    "electric_shock": (
        "electrocut",
        "electric shock",
        "live wire",
        "energized",
        "electrical panel",
        "electric panel",
        "energized panel",
        "400v",
        "200v",
        "高電圧",
        "感電",
        "通電",
        "充電部",
        "voltage panel",
        "v panel",
    ),
    "high_temp": (
        "hot",
        "furnace",
        "high temp",
        "high-temp",
        "molten",
        "burn",
        "高温",
        "やけど",
        "炉",
    ),
    "pressure": (
        "pressure",
        "hydraulic",
        "pneumatic",
        "accumulator",
        "compressed",
        "高圧",
        "圧力",
        "蓄圧",
    ),
    "chemical": (
        "chemical",
        "solvent",
        "acid",
        "corros",
        "toxic",
        "spill",
        "薬品",
        "化学",
        "溶剤",
        "腐食",
    ),
    "heavy_object": (
        "heavy",
        "crane",
        "hoist",
        "lift the",
        "lifting",
        "die with the crane",
        "重量物",
        "吊り",
        "玉掛",
        "クレーン",
    ),
    "safety_device": (
        "safety interlock",
        "interlock",
        "light curtain",
        "bypass the safety",
        "bypass safety",
        "guard",
        "emergency stop",
        "e-stop",
        "安全装置",
        "インターロック",
        "ライトカーテン",
        "非常停止",
        "bypass",
    ),
    "quality_judgment": (
        "judge this",
        "quality pass",
        "quality judgement",
        "quality judgment",
        "defect",
        "out of spec",
        "tolerance",
        "合否",
        "良否",
        "品質判定",
        "規格外",
        "不良",
    ),
    "shipment_decision": (
        "ship this",
        "ship the",
        "shipment",
        "deviation",
        "release to customer",
        "出荷",
        "客先",
        "deviate",
    ),
    "customer_impact": (
        "customer impact",
        "customer complaint",
        "recall",
        "顧客影響",
        "クレーム",
        "リコール",
    ),
    "corrective_action": (
        "corrective action",
        "corrective",
        "after the safety incident",
        "incident",
        "root cause",
        "是正",
        "再発防止",
        "対策",
        "事故後",
    ),
    # Hands-on physical intervention / cover-or-guard bypass / manual machine operation. These catch
    # genuinely dangerous, IMPERATIVE field actions phrased WITHOUT an explicit hazard word (e.g. "open
    # the inner housing", "reach into the moving rollers ... by hand", "run the cycle without the
    # cover", "restart the cycle manually"), which the labeled classes above otherwise miss — a recall
    # hole that let such a query fall through to is_high_risk=False (FR-MFG-015 「迷えば high-risk」).
    # Phrased as concrete physical-action substrings (not bare verbs) so informational/locational
    # queries ("where is ... located inside building") stay non-high-risk. NOTE: this widens recall for
    # KNOWN danger phrasings only; full semantic recall on novel phrasings still needs a production
    # danger-classification LLM (the MVP ExtractiveLLMProvider has none) — see GAP-S1.
    "physical_intervention": (
        "reach into",
        "reach in to",
        "by hand",
        "bare hand",
        "with bare hands",
        "manually",
        "inner housing",
        "open the housing",
        "open the inner",
        "remove the cover",
        "without the cover",
        "without cover",
        "without the guard",
        "without a guard",
        "moving roller",
        "moving part",
        "while running",
        "while in motion",
        "in motion",
        "clear the blockage",
        "run the cycle",
        "restart the cycle",
        "start the cycle",
        "run the machine",
        "start the machine",
        "手で",
        "素手",
        "手動",
        "カバーを外",
        "ガードを外",
        "稼働中",
        "可動部",
        "回転中",
    ),
}

# Metadata category fields whose mere presence (non-empty) implies physical / safety / quality work.
_HIGH_RISK_METADATA_FIELDS: tuple[str, ...] = (
    "safety_category",
    "quality_category",
    "equipment_operation_category",
    "process_id",
    "equipment_id",
)

# A query shorter than this many content tokens is treated as too terse to rule danger out.
_AMBIGUOUS_MIN_TOKENS = 3
_SEMANTIC_CONFIDENCE_THRESHOLD = 0.80

SemanticDangerClassifier = Callable[
    [str, Sequence[ManufacturingDocumentMetadata], str | None],
    Mapping[str, object] | HighRiskClassification | None,
]


class LLMSemanticDangerClassifier:
    """Production semantic danger classifier over the configured LLM provider.

    The LLM is asked for a small JSON verdict. Parsing errors, provider errors, ambiguity, and low
    confidence are handled by ``RuleHighRiskClassifier`` as high-risk.
    """

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    def __call__(
        self,
        query: str,
        candidate_metadata: Sequence[ManufacturingDocumentMetadata],
        intent_hint: str | None = None,
    ) -> Mapping[str, object] | None:
        meta_summary = [
            {
                "safety_category": getattr(meta, "safety_category", None),
                "quality_category": getattr(meta, "quality_category", None),
                "equipment_id": getattr(meta, "equipment_id", None),
                "hazard_tags": list(getattr(meta, "hazard_tags", ()) or ()),
            }
            for meta in candidate_metadata
            if meta is not None
        ]
        prompt = (
            "Classify whether this manufacturing field request is dangerous/high-risk. "
            "Return ONLY JSON with keys is_high_risk:boolean|null, confidence:number 0..1, "
            "reason_codes:string[]. Treat ambiguous or hands-on equipment work as high-risk.\n"
            f"Query: {query}\nIntent hint: {intent_hint or ''}\nMetadata: {json.dumps(meta_summary, ensure_ascii=False)}"
        )
        raw = self._llm.generate(prompt, ())
        return json.loads(raw)


class RuleHighRiskClassifier:
    """Concrete 3-stage cascade classifier (structurally satisfies interfaces.HighRiskClassifier).

    Not a top-level subclass of the ABC on purpose: ``interfaces`` imports the domain value objects,
    so subclassing would be a needless coupling. ``classify`` matches the ABC signature.
    """

    def __init__(
        self,
        llm: LLMProvider | None = None,
        *,
        semantic_classifier: SemanticDangerClassifier | None = None,
        semantic_confidence_threshold: float = _SEMANTIC_CONFIDENCE_THRESHOLD,
    ) -> None:
        # The 001 LLMProvider is only consulted for stage (3) (ambiguous tie-break). Optional so the
        # classifier degrades safely (no LLM => ambiguous still fails safe to high-risk).
        self._llm = llm
        self._semantic_classifier = semantic_classifier
        self._semantic_confidence_threshold = semantic_confidence_threshold

    def classify(
        self,
        query: str,
        candidate_metadata: Sequence[ManufacturingDocumentMetadata],
        intent_hint: str | None = None,
        extra_keywords: "Mapping[str, tuple[str, ...]] | None" = None,
    ) -> HighRiskClassification:
        reason_codes: list[str] = []
        first_source: ClassificationSource | None = None

        # --- (1) METADATA stage --------------------------------------------------------------------
        meta_codes = self._metadata_reason_codes(candidate_metadata)
        if meta_codes:
            first_source = ClassificationSource.METADATA
            reason_codes.extend(meta_codes)

        # --- (2) RULE + KEYWORD stage --------------------------------------------------------------
        haystack = f"{query} {intent_hint or ''}".lower()
        intent_codes = self._intent_reason_codes(haystack, extra_keywords)
        if intent_codes:
            if first_source is None:
                first_source = ClassificationSource.KEYWORD
            for code in intent_codes:
                if code not in reason_codes:
                    reason_codes.append(code)

        if reason_codes:
            return HighRiskClassification(
                is_high_risk=True,
                reason_codes=tuple(reason_codes),
                classification_source=first_source,
            )

        if self._semantic_classifier is not None:
            return self._semantic_decision(query, candidate_metadata, intent_hint)

        # --- (3) AMBIGUOUS tie-break (LLM only here) -----------------------------------------------
        # Nothing concrete fired. If the query is explicitly hinted ambiguous, or is too terse to rule
        # danger out, fail safe to high-risk. We consult the LLM (when present) only as a last attempt
        # to RULE DANGER OUT; if it cannot, we still flag high-risk (FR-MFG-015 「迷えば high-risk」).
        if self._is_ambiguous(query, intent_hint):
            if not self._llm_rules_danger_out(query, candidate_metadata):
                return HighRiskClassification(
                    is_high_risk=True,
                    reason_codes=("ambiguous",),
                    classification_source=(
                        ClassificationSource.LLM
                        if self._llm is not None
                        else ClassificationSource.RULE
                    ),
                )

        # Clearly non-dangerous, well-specified query: not high-risk.
        return HighRiskClassification(
            is_high_risk=False, reason_codes=(), classification_source=None
        )

    # --- stage helpers ----------------------------------------------------------------------------
    def _metadata_reason_codes(
        self, candidate_metadata: Sequence[ManufacturingDocumentMetadata]
    ) -> list[str]:
        codes: list[str] = []
        for meta in candidate_metadata:
            if meta is None:
                continue
            if meta.hazard_tags:
                if "hazard_tag" not in codes:
                    codes.append("hazard_tag")
            for field_name in _HIGH_RISK_METADATA_FIELDS:
                if getattr(meta, field_name, None):
                    code = f"metadata:{field_name}"
                    if code not in codes:
                        codes.append(code)
        return codes

    def _intent_reason_codes(self, haystack: str, extra_keywords=None) -> list[str]:
        codes: list[str] = []
        merged: dict[str, tuple[str, ...]] = dict(_INTENT_KEYWORDS)
        # ★V2 tenant_lexicon: per-tenant vocabulary EXTENDS the built-in danger sets — union only,
        # so detection can be widened for a new industry but never weakened.
        for code, extras in (extra_keywords or {}).items():
            base = merged.get(code, ())
            merged[code] = (*base, *tuple(k.lower() for k in extras if k))
        for code, keywords in merged.items():
            if any(kw in haystack for kw in keywords):
                codes.append(code)
        return codes

    def _is_ambiguous(self, query: str, intent_hint: str | None) -> bool:
        if intent_hint is not None and intent_hint.strip().lower() == "ambiguous":
            return True
        # Too terse to confidently rule danger out (content tokens, stopwords stripped).
        from raku_rag.core.text import content_tokens

        return len(content_tokens(query)) < _AMBIGUOUS_MIN_TOKENS

    def _llm_rules_danger_out(
        self,
        query: str,
        candidate_metadata: Sequence[ManufacturingDocumentMetadata],
    ) -> bool:
        """Best-effort LLM tie-break. Returns True ONLY if the LLM confidently rules danger out.

        Fail-safe: any uncertainty / no LLM / provider error => False (=> caller flags high-risk).
        The MVP ExtractiveLLMProvider has no danger-classification head, so it never confidently
        clears an ambiguous query — preserving the fail-safe default.
        """
        if self._llm is None:
            return False
        try:
            verdict = self._llm.generate(
                "Is this field-work request clearly NON-dangerous? "
                "Answer SAFE only if certain; otherwise say UNSURE. Query: " + query,
                (),
            )
        except Exception:
            return False
        return "safe" in (verdict or "").strip().lower()

    def _semantic_decision(
        self,
        query: str,
        candidate_metadata: Sequence[ManufacturingDocumentMetadata],
        intent_hint: str | None,
    ) -> HighRiskClassification:
        try:
            raw = self._semantic_classifier(query, candidate_metadata, intent_hint)
        except Exception:
            return HighRiskClassification(
                is_high_risk=True,
                reason_codes=("semantic_classifier_error",),
                classification_source=ClassificationSource.LLM,
            )
        if isinstance(raw, HighRiskClassification):
            return raw
        if not isinstance(raw, Mapping):
            return HighRiskClassification(
                is_high_risk=True,
                reason_codes=("semantic_classifier_ambiguous",),
                classification_source=ClassificationSource.LLM,
            )
        value = raw.get("is_high_risk")
        confidence = _float(raw.get("confidence"))
        reason_codes = tuple(str(code) for code in raw.get("reason_codes") or ())
        if value is True:
            return HighRiskClassification(
                is_high_risk=True,
                reason_codes=reason_codes or ("semantic_danger",),
                classification_source=ClassificationSource.LLM,
            )
        if value is False and confidence >= self._semantic_confidence_threshold:
            return HighRiskClassification(
                is_high_risk=False,
                reason_codes=(),
                classification_source=ClassificationSource.LLM,
            )
        return HighRiskClassification(
            is_high_risk=True,
            reason_codes=("semantic_low_confidence",),
            classification_source=ClassificationSource.LLM,
        )


def semantic_danger_classifier_from_settings(
    settings, llm: LLMProvider | None
) -> SemanticDangerClassifier | None:
    profile = str(getattr(settings, "runtime_profile", "deterministic") or "deterministic")
    if profile.strip().lower() != "production" or llm is None:
        return None
    llm_provider = (
        str(getattr(settings, "llm_provider", "") or "").strip().lower().replace("-", "_")
    )
    if llm_provider in {"extractive", "extractive_mvp", "deterministic", "local"}:
        return None
    return LLMSemanticDangerClassifier(llm)


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
