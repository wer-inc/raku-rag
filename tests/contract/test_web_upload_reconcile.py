"""Contract for pruning stale local upload records against the server list (/files ghost fix).

apps/web keeps an optimistic localStorage record per upload so a just-uploaded file shows immediately.
When a document is later deleted/purged server-side (e.g. a deploy-time demo re-seed), that local record
must not linger forever as a phantom "レビュー待ち" row. This pins, at source level (apps/web has no TS
unit runner), that the file browser reconciles local records against an authoritative server response —
and only on success, never on a fetch error. Same marker style as test_web_back_navigation.py.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPLOADS = ROOT / "apps/web/lib/uploads.ts"
FULL_SAAS = ROOT / "apps/web/app/components/FullSaasScreen.tsx"


class WebUploadReconcileContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.uploads = UPLOADS.read_text(encoding="utf-8")
        cls.full_saas = FULL_SAAS.read_text(encoding="utf-8")

    def test_uploads_exposes_reconcile_with_a_grace_window(self) -> None:
        for marker in (
            "export function reconcileIngestedDocs",
            "RECONCILE_GRACE_MS",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.uploads)

    def test_file_browser_reconciles_local_records_against_server(self) -> None:
        # Imported and invoked with the server document ids.
        for marker in (
            "reconcileIngestedDocs",
            "setLocalDocs(reconcileIngestedDocs(serverDocuments.map((doc) => doc.document_id)))",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.full_saas)

    def test_reconcile_runs_only_after_a_successful_fetch(self) -> None:
        # The reconcile line must sit in the try, AFTER setApiDocs, so a failed fetch (the catch) never
        # prunes local records — you cannot tell an empty tenant from an unreachable API.
        body = self.full_saas
        set_api = body.index("setApiDocs(serverDocuments)")
        reconcile = body.index("setLocalDocs(reconcileIngestedDocs(")
        catch = body.index("} catch (err) {", set_api)
        self.assertLess(set_api, reconcile)
        self.assertLess(reconcile, catch)

    def test_upload_cta_is_always_actionable(self) -> None:
        # No file selected -> the primary button opens the file picker instead of sitting as a dead
        # grey disabled button ("押しても何も起きない"); once files are chosen it becomes the ingest
        # action. It only disables mid-upload (double-submit guard) or on a real block.
        for marker in (
            "ref={fileInputRef}",
            "else fileInputRef.current?.click();",
            "if (files.length > 0) void onUpload();",
            '"📎 ファイルを選択"',
            "⬆ アップロード取込 (${files.length}件)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.full_saas)


if __name__ == "__main__":
    unittest.main()
