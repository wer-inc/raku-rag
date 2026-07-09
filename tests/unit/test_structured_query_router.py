from __future__ import annotations

import unittest

from raku_rag.domain.models import IdentityClaims, ScopeType, SubjectType
from raku_rag.services.structured_tables import STRUCTURED_TABLE_MANIFESTS_KEY
from raku_rag.services.structured_query import ReadOnlySqlTool, classify_structured_query
from tests.helpers import claims, fresh

T = "tenant_a"


class TestStructuredQueryRouter(unittest.TestCase):
    def test_aggregate_query_requires_structured_tool(self) -> None:
        decision = classify_structured_query("what is the average defect count by month?")
        self.assertEqual(decision.route, "refused_structured_tool_required")
        self.assertEqual(decision.reason, "aggregation")

    def test_plain_policy_query_stays_on_rag_route(self) -> None:
        decision = classify_structured_query("what is the torque spec for pump P-12?")
        self.assertEqual(decision.route, "rag")

    def test_document_ids_and_single_document_totals_stay_on_rag_route(self) -> None:
        queries = (
            "What caused the temperature sensor failure in trouble report TR-2024-017?",
            "When was invoice INV-2024-05 settled?",
            "What is the total of the estimate for the May 2024 plumbing job?",
        )
        for query in queries:
            with self.subTest(query=query):
                self.assertEqual(classify_structured_query(query).route, "rag")

    def test_period_filter_requires_period_language_not_document_id(self) -> None:
        decision = classify_structured_query("show defect incidents from 2024-01")
        self.assertEqual(decision.route, "refused_structured_tool_required")
        self.assertEqual(decision.reason, "period_filter")

    def test_spec_style_assignments_stay_on_rag_route(self) -> None:
        # "n=125" / "Ac=3" quote sampling-plan parameters; they are not comparison filters. The live
        # AQL demo query was mis-routed to the structured tool and answered from an unrelated table.
        queries = (
            "出荷検査の抜取は AQL 1.0 で n=125、合格判定個数 Ac=3 でよいか。"
            "軸受ハウジング A-200 のロット 1201〜3200 個の判定基準を教えて",
            "出荷検査の抜取検査のAQLはいくつですか?",
        )
        for query in queries:
            with self.subTest(query=query):
                self.assertEqual(classify_structured_query(query).route, "rag")

    def test_real_comparisons_and_counts_still_route_to_the_tool(self) -> None:
        for query, reason in (
            ("show parts where temperature > 100", "numeric_comparison"),
            ("不良率 5 以上の設備", "numeric_comparison_ja"),
            ("直近1ヶ月の不具合は何件?", "aggregation_ja"),
        ):
            with self.subTest(query=query):
                decision = classify_structured_query(query)
                self.assertEqual(decision.route, "refused_structured_tool_required")
                self.assertEqual(decision.reason, reason)

    def test_answer_routes_structured_query_away_from_vector_answering(self) -> None:
        sys = fresh()
        sys.ingest_text(
            tenant_id=T,
            collection_id="c",
            document_id="d1",
            text="Defect count in January was 12. Defect count in February was 18.",
        )
        sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")

        ans = sys.answer(claims(T, "alice"), "what is the total defect count by month?")

        self.assertEqual(ans.status, "insufficient_evidence")
        self.assertEqual(ans.route, "structured_tool")
        self.assertIsNone(ans.text)
        self.assertEqual(ans.used_chunks, ())

    def test_csv_manifest_answers_aggregate_with_cell_citations(self) -> None:
        sys = fresh()
        csv_body = b"month,defect count\nJan 2024,12\nFeb 2024,18\n"
        job = sys.ingestion.ingest(
            tenant_id=T,
            collection_id="metrics",
            source_id="quality-csv",
            document_id="defects",
            raw=csv_body,
            content_type="text/csv",
        )
        self.assertEqual(job.status, "succeeded", job.failure_reason)
        sys.grant(T, ScopeType.COLLECTION, "metrics", SubjectType.USER, "alice")

        doc = sys.registry.get(T, "defects")
        self.assertIsNotNone(doc)
        self.assertEqual(len(doc.metadata[STRUCTURED_TABLE_MANIFESTS_KEY]), 1)

        ans = sys.answer(
            claims(T, "alice"),
            "what is the total defect count by month?",
            collection_id="metrics",
        )

        self.assertEqual(ans.status, "ok")
        self.assertEqual(ans.route, "structured_tool")
        self.assertIn("Jan 2024=12", ans.text or "")
        self.assertIn("Feb 2024=18", ans.text or "")
        self.assertEqual(ans.citations[0].kind, "spreadsheet")
        self.assertEqual(ans.citations[0].sheet_name, "sheet1")
        self.assertEqual(ans.citations[0].cell_range, "sheet1!R2C2")

    def test_csv_manifest_total_without_grouping_sums_numeric_column(self) -> None:
        sys = fresh()
        sys.ingestion.ingest(
            tenant_id=T,
            collection_id="metrics",
            source_id="quality-csv",
            document_id="defects",
            raw=b"month,defect count\nJan 2024,12\nFeb 2024,18\n",
            content_type="text/csv",
        )
        sys.grant(T, ScopeType.COLLECTION, "metrics", SubjectType.USER, "alice")

        ans = sys.answer(
            claims(T, "alice"),
            "what is the total defect count?",
            collection_id="metrics",
        )

        self.assertEqual(ans.status, "ok")
        self.assertEqual(ans.route, "structured_tool")
        self.assertEqual(ans.text, "Total defect count: 30")

    def test_tool_refuses_numeric_filter_over_unrelated_table(self) -> None:
        # Fabrication guard: a comparison query must not be answered from a table none of whose
        # columns the query references (the tool used to fall back to an arbitrary numeric column
        # and cite an unrelated spreadsheet as evidence).
        sys = fresh()
        sys.ingestion.ingest(
            tenant_id=T,
            collection_id="hr",
            source_id="skills-csv",
            document_id="skills",
            raw=b"skill,years\nwelding,12\ninspection,3\n",
            content_type="text/csv",
        )
        sys.grant(T, ScopeType.COLLECTION, "hr", SubjectType.USER, "alice")

        ans = sys.answer(
            claims(T, "alice"),
            "show parts where temperature > 5",
            collection_id="hr",
        )

        self.assertEqual(ans.status, "insufficient_evidence")
        self.assertEqual(ans.route, "structured_tool")
        self.assertIsNone(ans.text)
        self.assertEqual(ans.citations, ())

    def test_structured_tool_enforces_acl(self) -> None:
        sys = fresh()
        sys.ingestion.ingest(
            tenant_id=T,
            collection_id="metrics",
            source_id="quality-csv",
            document_id="defects",
            raw=b"month,defect count\nJan 2024,12\n",
            content_type="text/csv",
        )

        ans = sys.answer(
            claims(T, "alice"),
            "what is the total defect count by month?",
            collection_id="metrics",
        )

        self.assertEqual(ans.status, "insufficient_evidence")
        self.assertEqual(ans.citations, ())


class TestReadOnlySqlToolBoundary(unittest.TestCase):
    def setUp(self) -> None:
        self.calls = []

        def executor(sql, params, timeout, limit):
            self.calls.append((sql, params, timeout, limit))
            return [{"tenant_id": params["tenant_id"], "count": 1}]

        self.tool = ReadOnlySqlTool({"defects": executor}, timeout_seconds=1.5, row_limit=10)
        self.principal = IdentityClaims(tenant_id=T, user_id="alice", groups=(), roles=())

    def test_executes_allowlisted_select_with_tenant_scope(self) -> None:
        rows = self.tool.execute(
            principal=self.principal,
            datasource_id="defects",
            sql="SELECT count(*) FROM defects WHERE tenant_id = :tenant_id",
            trusted_template_id="defect-count-v1",
        )

        self.assertEqual(rows, [{"tenant_id": T, "count": 1}])
        self.assertEqual(self.calls[0][1]["tenant_id"], T)
        self.assertEqual(self.calls[0][2], 1.5)
        self.assertEqual(self.calls[0][3], 10)

    def test_blocks_unallowlisted_mutating_or_unscoped_sql(self) -> None:
        with self.assertRaises(PermissionError):
            self.tool.execute(
                principal=self.principal,
                datasource_id="unknown",
                sql="SELECT * FROM defects WHERE tenant_id = :tenant_id",
                trusted_template_id="x",
            )
        with self.assertRaises(PermissionError):
            self.tool.execute(
                principal=self.principal,
                datasource_id="defects",
                sql="DELETE FROM defects WHERE tenant_id = :tenant_id",
                trusted_template_id="x",
            )
        with self.assertRaises(PermissionError):
            self.tool.execute(
                principal=self.principal,
                datasource_id="defects",
                sql="SELECT * FROM defects",
                trusted_template_id="x",
            )
        with self.assertRaises(PermissionError):
            self.tool.execute(
                principal=self.principal,
                datasource_id="defects",
                sql="SELECT * FROM defects WHERE tenant_id = :tenant_id",
            )


if __name__ == "__main__":
    unittest.main()
