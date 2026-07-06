"""ADR 018 extraction-quality metadata contract."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import Chunk, Modality
from raku_rag.services.ingestion_quality import (
    EXTRACTION_QUALITY_SCHEMA_VERSION,
    EXTRACTION_QUALITY_SCHEMA_VERSION_KEY,
    EXTRACTION_QUALITY_STATUS_KEY,
    HIGH_RISK_CITATION_ELIGIBLE_KEY,
    QUALITY_STATUS_ACCEPTED,
    QUALITY_STATUS_ACCEPTED_WITH_WARNINGS,
    QUALITY_STATUS_DRAFT_VISUAL,
    QUALITY_STATUS_REVIEW_REQUIRED,
    REASON_CID_ARTIFACTS,
    REASON_EMPTY_EXTRACTION,
    REASON_MINOR_MOJIBAKE,
    REASON_MOJIBAKE_SUSPECTED,
    RETRIEVAL_ELIGIBLE_KEY,
    accepted_quality_metadata,
    accepted_with_warnings_quality_metadata,
    classify_text_extraction_quality,
    extraction_review_items,
    is_high_risk_citation_quality_eligible,
    is_retrieval_eligible,
    quality_metadata_from_ocr_metadata,
    review_required_quality_metadata,
)


class IngestionQualityMetadataTest(unittest.TestCase):
    def test_accepted_metadata_is_retrieval_and_citation_eligible(self) -> None:
        metadata = accepted_quality_metadata()

        self.assertEqual(
            metadata[EXTRACTION_QUALITY_SCHEMA_VERSION_KEY], EXTRACTION_QUALITY_SCHEMA_VERSION
        )
        self.assertEqual(metadata[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_ACCEPTED)
        self.assertTrue(metadata[RETRIEVAL_ELIGIBLE_KEY])
        self.assertTrue(metadata[HIGH_RISK_CITATION_ELIGIBLE_KEY])
        self.assertTrue(is_retrieval_eligible(metadata))
        self.assertTrue(is_high_risk_citation_quality_eligible(metadata))

    def test_review_required_metadata_is_not_retrievable(self) -> None:
        metadata = review_required_quality_metadata(reasons=("low_ocr_confidence",))

        self.assertEqual(metadata[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_REVIEW_REQUIRED)
        self.assertFalse(metadata[RETRIEVAL_ELIGIBLE_KEY])
        self.assertFalse(metadata[HIGH_RISK_CITATION_ELIGIBLE_KEY])
        self.assertFalse(is_retrieval_eligible(metadata))
        self.assertFalse(is_high_risk_citation_quality_eligible(metadata))

    def test_explicit_retrieval_false_wins_over_missing_status(self) -> None:
        self.assertFalse(is_retrieval_eligible({RETRIEVAL_ELIGIBLE_KEY: "false"}))

    def test_low_ocr_quality_maps_to_review_required(self) -> None:
        metadata = quality_metadata_from_ocr_metadata({"ocr_quality_review_required": True})

        self.assertEqual(metadata[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_REVIEW_REQUIRED)
        self.assertFalse(is_retrieval_eligible(metadata))

    def test_accepted_with_warnings_is_retrievable_but_not_high_risk(self) -> None:
        metadata = accepted_with_warnings_quality_metadata(reasons=(REASON_MINOR_MOJIBAKE,))

        self.assertEqual(
            metadata[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_ACCEPTED_WITH_WARNINGS
        )
        self.assertTrue(is_retrieval_eligible(metadata))
        self.assertFalse(is_high_risk_citation_quality_eligible(metadata))


class StructuredChunkHighRiskAnchorTraceTest(unittest.TestCase):
    """§11.4 — a structured-pipeline chunk with no anchor or no provider/version trace is not
    high-risk evidence-grade. Legacy (pre-ADR-018) content, which never sets parser_contract_version,
    must be unaffected — this is the scoping guard that keeps the check additive."""

    def test_structured_chunk_missing_anchor_is_not_high_risk_eligible(self) -> None:
        metadata = accepted_quality_metadata()
        metadata.update(
            {
                "parser_contract_version": "v1",
                "embedding_model_version": "v",
                "parsed_chunk_kind": "text_chunk",
                # no anchor_type / cell_sheet
            }
        )
        self.assertTrue(is_retrieval_eligible(metadata))
        self.assertFalse(is_high_risk_citation_quality_eligible(metadata))

    def test_structured_chunk_missing_provider_trace_is_not_high_risk_eligible(self) -> None:
        metadata = accepted_quality_metadata()
        metadata.update({"parser_contract_version": "v1", "anchor_type": "page_bbox"})
        # embedding_model_version / parsed_chunk_kind missing.
        self.assertFalse(is_high_risk_citation_quality_eligible(metadata))

    def test_structured_chunk_with_anchor_and_trace_is_eligible(self) -> None:
        metadata = accepted_quality_metadata()
        metadata.update(
            {
                "parser_contract_version": "v1",
                "anchor_type": "page_bbox",
                "embedding_model_version": "v",
                "parsed_chunk_kind": "text_chunk",
            }
        )
        self.assertTrue(is_high_risk_citation_quality_eligible(metadata))

    def test_spreadsheet_anchor_via_cell_sheet_counts(self) -> None:
        metadata = accepted_quality_metadata()
        metadata.update(
            {
                "parser_contract_version": "v1",
                "cell_sheet": "Sheet1",
                "embedding_model_version": "v",
                "parsed_chunk_kind": "spreadsheet_cell",
            }
        )
        self.assertTrue(is_high_risk_citation_quality_eligible(metadata))

    def test_legacy_content_with_no_parser_contract_version_is_unaffected(self) -> None:
        # Pre-ADR-018 content: has quality metadata but never sets parser_contract_version at all.
        metadata = accepted_quality_metadata()
        self.assertTrue(is_high_risk_citation_quality_eligible(metadata))


class ClassifyTextExtractionQualityTest(unittest.TestCase):
    def test_clean_text_is_accepted(self) -> None:
        metadata = classify_text_extraction_quality("作業前に主電源を停止すること。", raw_size=64)
        self.assertEqual(metadata[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_ACCEPTED)
        self.assertTrue(is_retrieval_eligible(metadata))

    def test_empty_yield_on_nontrivial_input_is_review_required(self) -> None:
        metadata = classify_text_extraction_quality("   ", raw_size=4096)
        self.assertEqual(metadata[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_REVIEW_REQUIRED)
        self.assertIn(REASON_EMPTY_EXTRACTION, metadata["extraction_quality_reasons"])

    def test_empty_yield_on_empty_input_is_accepted(self) -> None:
        # An genuinely empty/short source is not a broken extraction.
        metadata = classify_text_extraction_quality("", raw_size=10)
        self.assertEqual(metadata[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_ACCEPTED)

    def test_cid_artifacts_are_review_required(self) -> None:
        metadata = classify_text_extraction_quality("(cid:12)(cid:34) 手順", raw_size=64)
        self.assertEqual(metadata[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_REVIEW_REQUIRED)
        self.assertIn(REASON_CID_ARTIFACTS, metadata["extraction_quality_reasons"])

    def test_heavy_mojibake_is_review_required(self) -> None:
        metadata = classify_text_extraction_quality("正常" + "�" * 20, raw_size=64)
        self.assertEqual(metadata[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_REVIEW_REQUIRED)
        self.assertIn(REASON_MOJIBAKE_SUSPECTED, metadata["extraction_quality_reasons"])

    def test_trace_mojibake_is_accepted_with_warnings(self) -> None:
        clean = "作業標準書の手順です。" * 20
        metadata = classify_text_extraction_quality(clean + "�", raw_size=1024)
        self.assertEqual(
            metadata[EXTRACTION_QUALITY_STATUS_KEY], QUALITY_STATUS_ACCEPTED_WITH_WARNINGS
        )
        self.assertTrue(is_retrieval_eligible(metadata))
        self.assertFalse(is_high_risk_citation_quality_eligible(metadata))


class ExtractionReviewQueueTest(unittest.TestCase):
    def _chunk(self, chunk_id: str, quality: dict) -> Chunk:
        return Chunk(
            tenant_id="t",
            chunk_id=chunk_id,
            document_id=chunk_id.split(":")[0],
            collection_id="c",
            text="x",
            position=0,
            token_count=1,
            heading_path=(),
            modality=Modality.TEXT,
            embedding_model_version="v",
            metadata=quality,
        )

    def test_only_quarantined_chunks_surface_in_the_queue(self) -> None:
        items = [
            (self._chunk("acc:0", accepted_quality_metadata()), None),
            (
                self._chunk(
                    "rev:0", review_required_quality_metadata(reasons=("low_ocr_confidence",))
                ),
                None,
            ),
            (
                self._chunk(
                    "vis:0",
                    review_required_quality_metadata(status=QUALITY_STATUS_DRAFT_VISUAL),
                ),
                None,
            ),
            (self._chunk("warn:0", accepted_with_warnings_quality_metadata()), None),
        ]

        queue = extraction_review_items(items)
        surfaced = {(item.document_id, item.status) for item in queue}
        self.assertEqual(
            surfaced,
            {("rev", QUALITY_STATUS_REVIEW_REQUIRED), ("vis", QUALITY_STATUS_DRAFT_VISUAL)},
        )
        review = next(item for item in queue if item.document_id == "rev")
        self.assertIn("low_ocr_confidence", review.reasons)

    def test_tenant_filter(self) -> None:
        chunk = self._chunk("rev:0", review_required_quality_metadata())
        self.assertEqual(len(extraction_review_items([chunk], tenant_id="t")), 1)
        self.assertEqual(len(extraction_review_items([chunk], tenant_id="other")), 0)

    def test_review_item_carries_page_anchor_and_suggested_action(self) -> None:
        # §12.1 — the review item exposes enough to locate + triage the extraction.
        quality = review_required_quality_metadata(reasons=("mojibake_suspected",))
        quality.update({"anchor_type": "page_bbox", "page_number": 4, "bbox": [1, 2, 3, 4]})
        chunk = self._chunk("rev:0", quality)
        chunk = Chunk(**{**chunk.__dict__, "text": "ポンプ " + "�" * 30})
        item = extraction_review_items([chunk])[0]
        self.assertEqual(item.page_no, 4)
        self.assertEqual(item.anchor_type, "page_bbox")
        self.assertEqual(item.bbox, (1.0, 2.0, 3.0, 4.0))
        self.assertTrue(item.text_snippet.startswith("ポンプ"))
        # mojibake is a provider problem -> suggest a reprocess with a different provider.
        self.assertEqual(item.suggested_action, "reprocess")

    def test_draft_visual_suggests_approve(self) -> None:
        chunk = self._chunk(
            "vis:0", review_required_quality_metadata(status=QUALITY_STATUS_DRAFT_VISUAL)
        )
        self.assertEqual(extraction_review_items([chunk])[0].suggested_action, "approve")

    def test_review_item_surfaces_route_trace(self) -> None:
        # §6.3 / §12.1 — the persisted route_trace reaches the reviewer.
        quality = review_required_quality_metadata(reasons=("low_ocr_confidence",))
        quality["route_trace"] = [
            {"stage": "preflight", "result": "scanned_japanese", "signals": ["no_text_layer"]},
            {"stage": "extract", "provider": "docling", "result": "partial"},
        ]
        item = extraction_review_items([self._chunk("rev:0", quality)])[0]
        self.assertEqual(len(item.route_trace), 2)
        self.assertEqual(item.route_trace[0]["stage"], "preflight")
        self.assertEqual(item.route_trace[-1]["provider"], "docling")

    def test_extraction_review_queue_prefers_efficient_store_method(self) -> None:
        from raku_rag.services.ingestion_quality import extraction_review_queue

        rev = self._chunk("rev:0", review_required_quality_metadata(reasons=("x",)))

        class _EfficientStore:
            def list_extraction_review_chunks(self):
                return (rev,)

            def iter_items(self):  # must NOT be used when the efficient method exists
                raise AssertionError("iter_items should not be called")

        q = extraction_review_queue(_EfficientStore(), tenant_id="t")
        self.assertEqual([it.document_id for it in q], ["rev"])

    def test_extraction_review_queue_falls_back_to_iter_items(self) -> None:
        from raku_rag.services.ingestion_quality import extraction_review_queue

        rev = self._chunk("rev:0", review_required_quality_metadata())
        acc = self._chunk("acc:0", accepted_quality_metadata())

        class _InMemStore:
            def iter_items(self):
                return ((acc, None), (rev, None))

        q = extraction_review_queue(_InMemStore())
        self.assertEqual([it.document_id for it in q], ["rev"])

    def test_extraction_quality_stats_counts_and_quarantine_rate(self) -> None:
        from raku_rag.services.ingestion_quality import extraction_quality_stats

        rev = self._chunk("rev:0", review_required_quality_metadata(reasons=("x",)))
        acc1 = self._chunk("a:0", accepted_quality_metadata())
        acc2 = self._chunk("a:1", accepted_quality_metadata())

        class _InMemStore:
            def iter_items(self):
                return ((acc1, None), (acc2, None), (rev, None))

        stats = extraction_quality_stats(_InMemStore())
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["quarantined"], 1)
        self.assertAlmostEqual(stats["quarantine_rate"], 1 / 3)
        self.assertEqual(stats["by_status"]["review_required"], 1)
        self.assertEqual(stats["by_status"]["accepted"], 2)
        # §18: per-status rates + quality-reason counts
        self.assertAlmostEqual(stats["rates"]["accepted"], 2 / 3)
        self.assertEqual(stats["by_reason"].get("x"), 1)

    def test_stats_provider_distribution_and_fallback_rate(self) -> None:
        # §18.1 — from the persisted route_trace: which provider won, and how often a fallback ran.
        from raku_rag.services.ingestion_quality import extraction_quality_stats

        def with_route(cid, steps):
            meta = accepted_quality_metadata()
            meta["route_trace"] = steps
            return self._chunk(cid, meta)

        native = with_route(
            "a:0", [{"stage": "extract", "provider": "docling", "result": "accepted"}]
        )
        fell_back = with_route(
            "b:0",
            [
                {"stage": "extract", "provider": "docling", "result": "partial"},
                {"stage": "fallback", "provider": "rapidocr", "result": "accepted"},
            ],
        )

        class _InMemStore:
            def iter_items(self):
                return ((native, None), (fell_back, None))

        stats = extraction_quality_stats(_InMemStore())
        self.assertEqual(stats["by_provider"], {"docling": 1, "rapidocr": 2 - 1})
        self.assertAlmostEqual(stats["fallback_rate"], 1 / 2)

    def test_stats_provider_failure_rate(self) -> None:
        # §18.1 — distinct from fallback_rate: a hard provider_error reason, not a successful fallback.
        from raku_rag.services.ingestion_quality import extraction_quality_stats

        failed = self._chunk("a:0", review_required_quality_metadata(reasons=("provider_error",)))
        ok = self._chunk("b:0", accepted_quality_metadata())

        class _InMemStore:
            def iter_items(self):
                return ((failed, None), (ok, None))

        stats = extraction_quality_stats(_InMemStore())
        self.assertAlmostEqual(stats["provider_failure_rate"], 1 / 2)

    def test_latency_cost_stats_dedupe_percentiles_and_cost(self) -> None:
        # §18.3 — measured latency (per stage, p50/p95) + config cost, deduped by document.
        from raku_rag.services.ingestion_quality import extraction_latency_cost_stats

        def doc_chunk(cid, doc, route):
            meta = accepted_quality_metadata()
            meta["route_trace"] = route
            return Chunk(**{**self._chunk(cid, meta).__dict__, "document_id": doc})

        rt_a = [
            {"stage": "extract", "provider": "docling", "latency_ms": 100.0},
            {"stage": "ocr", "provider": "rapidocr", "latency_ms": 200.0},
        ]
        rt_b = [{"stage": "extract", "provider": "docling", "latency_ms": 150.0}]

        class _InMemStore:
            def iter_items(self):
                # doc A has two chunks — its route_trace must be counted once.
                return (
                    (doc_chunk("a:0", "A", rt_a), None),
                    (doc_chunk("a:1", "A", rt_a), None),
                    (doc_chunk("b:0", "B", rt_b), None),
                )

        stats = extraction_latency_cost_stats(
            _InMemStore(), cost_model={"rapidocr": 0.002, "docling": 0.0}
        )
        self.assertEqual(stats["documents"], 2)
        self.assertEqual(stats["latency_ms_by_stage"]["extract"]["p50"], 125.0)
        self.assertEqual(stats["latency_ms_by_stage"]["extract"]["count"], 2)
        self.assertEqual(stats["latency_ms_by_stage"]["ocr"]["p50"], 200.0)
        self.assertEqual(stats["provider_calls"], {"docling": 2, "rapidocr": 1})
        self.assertAlmostEqual(stats["total_cost"], 0.002)
        self.assertAlmostEqual(stats["cost_per_document"], 0.001)

    def test_latency_cost_stats_pages_processed_and_route_distribution(self) -> None:
        # §18.1/§18.2/§18.3 — page-level stats persisted by _page_route_metadata, document-deduped.
        from raku_rag.services.ingestion_quality import extraction_latency_cost_stats

        def doc_chunk(cid, doc, *, page_count, route_dist, extra=None):
            meta = accepted_quality_metadata()
            meta["page_count"] = page_count
            meta["page_route_distribution"] = route_dist
            meta.update(extra or {})
            return Chunk(**{**self._chunk(cid, meta).__dict__, "document_id": doc})

        class _InMemStore:
            def iter_items(self):
                return (
                    # doc A: 2 chunks, same document-level page stats — must be counted ONCE.
                    (
                        doc_chunk(
                            "a:0",
                            "A",
                            page_count=3,
                            route_dist={"clean_digital_text": 2, "scanned": 1},
                            extra={"seal_detected_pages": 1},
                        ),
                        None,
                    ),
                    (
                        doc_chunk(
                            "a:1",
                            "A",
                            page_count=3,
                            route_dist={"clean_digital_text": 2, "scanned": 1},
                            extra={"seal_detected_pages": 1},
                        ),
                        None,
                    ),
                    (
                        doc_chunk(
                            "b:0",
                            "B",
                            page_count=1,
                            route_dist={"drawing_cad": 1},
                            extra={"drawing_like_pages": 1},
                        ),
                        None,
                    ),
                )

        stats = extraction_latency_cost_stats(_InMemStore())
        self.assertEqual(stats["pages_processed"], 4)  # 3 (doc A, once) + 1 (doc B)
        self.assertEqual(
            stats["route_distribution"],
            {"clean_digital_text": 2, "scanned": 1, "drawing_cad": 1},
        )
        self.assertEqual(stats["seal_detected_pages"], 1)
        self.assertEqual(stats["drawing_like_pages"], 1)

    def test_cost_per_page(self) -> None:
        from raku_rag.services.ingestion_quality import extraction_latency_cost_stats

        meta = accepted_quality_metadata()
        meta["page_count"] = 2
        meta["route_trace"] = [{"stage": "extract", "provider": "google_docai"}]
        chunk = self._chunk("a:0", meta)

        class _InMemStore:
            def iter_items(self):
                return ((chunk, None),)

        stats = extraction_latency_cost_stats(_InMemStore(), cost_model={"google_docai": 0.01})
        self.assertAlmostEqual(stats["cost_per_page"], 0.01 / 2)


class ReviewOverturnStatsTest(unittest.TestCase):
    class _Event:
        def __init__(self, *, tenant_id, action, decision, chunk_id):
            self.tenant_id = tenant_id
            self.action = action
            self.decision = decision
            self.chunk_ids = (chunk_id,)
            self.resource_id = chunk_id

    def test_approve_then_reject_is_an_overturn(self) -> None:
        from raku_rag.services.ingestion_quality import review_overturn_stats

        events = [
            self._Event(
                tenant_id="t",
                action="extraction_review.approve",
                decision="manual_approved",
                chunk_id="c1",
            ),
            self._Event(
                tenant_id="t", action="extraction_review.reject", decision="rejected", chunk_id="c1"
            ),
        ]
        stats = review_overturn_stats(events, tenant_id="t")
        self.assertEqual(stats["reviewed_multiple_times"], 1)
        self.assertEqual(stats["overturned"], 1)
        self.assertEqual(stats["review_overturn_rate"], 1.0)

    def test_single_review_is_not_counted_as_reviewed_multiple_times(self) -> None:
        from raku_rag.services.ingestion_quality import review_overturn_stats

        events = [
            self._Event(
                tenant_id="t",
                action="extraction_review.approve",
                decision="manual_approved",
                chunk_id="c1",
            )
        ]
        stats = review_overturn_stats(events, tenant_id="t")
        self.assertEqual(stats["reviewed_multiple_times"], 0)
        self.assertEqual(stats["review_overturn_rate"], 0.0)

    def test_escalate_then_approve_is_not_an_overturn(self) -> None:
        # Two review actions on the same chunk, but never both manual_approved AND rejected.
        from raku_rag.services.ingestion_quality import review_overturn_stats

        events = [
            self._Event(
                tenant_id="t",
                action="extraction_review.escalate",
                decision="review_required",
                chunk_id="c1",
            ),
            self._Event(
                tenant_id="t",
                action="extraction_review.approve",
                decision="manual_approved",
                chunk_id="c1",
            ),
        ]
        stats = review_overturn_stats(events, tenant_id="t")
        self.assertEqual(stats["reviewed_multiple_times"], 1)
        self.assertEqual(stats["overturned"], 0)

    def test_other_tenants_and_non_review_events_are_ignored(self) -> None:
        from raku_rag.services.ingestion_quality import review_overturn_stats

        events = [
            self._Event(
                tenant_id="other",
                action="extraction_review.approve",
                decision="manual_approved",
                chunk_id="c1",
            ),
            self._Event(
                tenant_id="other",
                action="extraction_review.reject",
                decision="rejected",
                chunk_id="c1",
            ),
            self._Event(tenant_id="t", action="answer", decision="ok", chunk_id="c2"),
        ]
        stats = review_overturn_stats(events, tenant_id="t")
        self.assertEqual(stats["reviewed_multiple_times"], 0)


class AnswerCitationQualitySignalsTest(unittest.TestCase):
    class _Cite:
        def __init__(self, metadata):
            self.metadata = metadata

    def test_projects_status_distribution_and_review_approved_usage(self) -> None:
        from raku_rag.services.ingestion_quality import (
            QUALITY_STATUS_MANUAL_APPROVED,
            answer_citation_quality_signals,
        )

        cites = [
            self._Cite(accepted_quality_metadata(status=QUALITY_STATUS_MANUAL_APPROVED)),
            self._Cite(accepted_quality_metadata()),
            self._Cite(accepted_with_warnings_quality_metadata()),
        ]
        s = answer_citation_quality_signals(cites, is_high_risk=True)
        self.assertEqual(s["citations_total"], 3)
        self.assertEqual(s["review_approved_chunk_usage"], 1)
        self.assertAlmostEqual(s["review_approved_usage_rate"], 1 / 3)
        # §11.4: manual_approved + accepted are high-risk eligible; accepted_with_warnings is not.
        self.assertEqual(s["high_risk_citation_eligible"], 2)
        self.assertEqual(s["by_status"]["accepted_with_warnings"], 1)

    def test_high_risk_block_only_counts_invalid_citation_reason(self) -> None:
        from raku_rag.services.ingestion_quality import answer_citation_quality_signals

        blocked = answer_citation_quality_signals(
            [], is_high_risk=True, blocked=True, block_reason="APPROVED_CITATION_MISSING"
        )
        self.assertEqual(blocked["high_risk_blocked_invalid_citation"], 1)
        # A different block reason (or a non-high-risk answer) is not an invalid-citation block.
        other = answer_citation_quality_signals(
            [], is_high_risk=True, blocked=True, block_reason="INSUFFICIENT_EVIDENCE"
        )
        self.assertEqual(other["high_risk_blocked_invalid_citation"], 0)
        not_hr = answer_citation_quality_signals(
            [], is_high_risk=False, blocked=True, block_reason="APPROVED_CITATION_MISSING"
        )
        self.assertEqual(not_hr["high_risk_blocked_invalid_citation"], 0)

    def test_aggregate_rolls_up_many_answers(self) -> None:
        from raku_rag.services.ingestion_quality import (
            aggregate_answer_quality_signals,
            answer_citation_quality_signals,
        )

        a = answer_citation_quality_signals([self._Cite(accepted_quality_metadata())])
        b = answer_citation_quality_signals(
            [], is_high_risk=True, blocked=True, block_reason="APPROVED_CITATION_MISSING"
        )
        rolled = aggregate_answer_quality_signals([a, b])
        self.assertEqual(rolled["answers"], 2)
        self.assertEqual(rolled["citations_total"], 1)
        self.assertEqual(rolled["high_risk_blocked_invalid_citation"], 1)


if __name__ == "__main__":
    unittest.main()
