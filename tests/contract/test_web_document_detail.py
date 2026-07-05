"""0085 — document-detail is a readable admin summary, not a raw-JSON metadata editor.

apps/web has no TS unit runner, so pin the DocumentDetailBody invariants as source markers (same style
as test_web_upload_reconcile.py). The footgun raw-JSON metadata editor (dummy `{"owner":"ops"}` default
that clobbered real governance metadata on save) is gone; real approval/source come from the document
summary; the internal processing JSON is collapsed behind a developer toggle; delete is confirm-guarded.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FULL_SAAS = ROOT / "apps/web/app/components/FullSaasScreen.tsx"


class WebDocumentDetailContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = FULL_SAAS.read_text(encoding="utf-8")

    def test_raw_json_metadata_editor_is_removed(self) -> None:
        # The raw-JSON editor + its save call must be gone; governance edits belong to /reviews + ingest.
        for gone in (
            "メタデータを保存",
            'aria-label="メタデータ"',
            "manufacturingUpdateDocumentMetadata",
        ):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, self.src)

    def test_shows_real_values_not_hardcoded_placeholders(self) -> None:
        # 利用状態/ソース are the document summary's real values, not the old hardcoded placeholders.
        self.assertIn("citeApproval(summary?.approval_status)", self.src)
        self.assertIn("summary?.source_id", self.src)
        self.assertIn("ingestStatusLabel(proc.status)", self.src)
        self.assertNotIn('["ソース", "取り込みソース"]', self.src)

    def test_processing_json_is_collapsed_behind_a_developer_toggle(self) -> None:
        self.assertIn("処理メタデータ(開発者向け)を表示", self.src)
        self.assertIn("doc-processing-details", self.src)

    def test_delete_is_confirm_guarded(self) -> None:
        self.assertIn("setConfirmingDelete(true)", self.src)
        self.assertIn("この操作は取り消せません", self.src)


if __name__ == "__main__":
    unittest.main()
