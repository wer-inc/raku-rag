# 0071 — 根拠文書レビューが vectorize / index 完了前の文書を区別できない(系統 = product / safety / ingestion)

> Priority: **P1 / High** / Status: Implemented locally / Labels: `product`, `safety`, `ingestion`, `approval`, `document-review`

## 実装結果(2026-07-04)

- `ManufacturingSystem` の document projection に processing / index / chunk / approval readiness を追加した。
- `approved` への transition は index成功 + chunk_count > 0 を server-side で必須化した。
- source単位 batch approval API を追加し、ready でない文書・ACL不可視文書・terminal 文書は skip するようにした。
- `/reviews/documents` はソース単位 Inbox になり、準備中・問題あり・承認可能を user-facing label で表示する。

残る確認: stg/live の実データで PDF 非同期 ingest の queued → succeeded 遷移を smoke する。

## 背景(なぜ今)

「根拠文書レビューに出ている文書は vectorize 済みか」を確認したところ、通常の text / CSV / DOCX /
image 取込は成功後に Document/Chunk が作られ、metadata が付く。一方、PDF など非同期処理では API が
queued/running の `Document` stub を先に registry に作成し、その時点で manufacturing metadata も付与する。

根拠文書レビュー画面は registry の文書一覧を表示しており、index / embedding の完了状態を主表示していないため、
reviewer が「処理済みの文書」と「まだ vectorize/index 中の文書」を区別できない可能性がある。

## どんな課題か

- 期待挙動: 根拠文書レビューで承認できるのは、parse → chunk → embed → index が成功し、本文/チャンクを確認できる文書。
- 実際の懸念: PDF など非同期文書は `_upsert_pending_document_stub(...)` で review queue に現れる可能性があり、
  chunk_count=0 / index未完了のまま承認操作できる余地がある。
- 承認は metadata transition なので、現在の文書承認 API は「index済みか」「chunkを確認可能か」を必須条件にしていない。

## どこで起きたか

- 画面: `/reviews/documents` の根拠文書レビュー
- API: `GET /v1/manufacturing/documents`
- API: `POST /v1/manufacturing/documents/:documentId/approval`
- コード:
  - `src/raku_rag/production.py` — PDF path が `_upsert_pending_document_stub(...)` を作成して queued run を返す。
  - `src/raku_rag/manufacturing/app.py` — `list_documents(...)` は registry 文書を列挙し、index status を返さない。
  - `apps/web/app/components/FullSaasScreen.tsx` — `DocumentApprovalQueueBody` は文書状態と承認ボタン中心で、
    parse/embed/index 完了を承認条件にしていない。
- 環境: local code review。live/stg reproduction は未実施。
- run id / ingestion id / correlation id: なし。
- 再現条件:
  1. PDF など非同期 ingest 対象を `review_required` で登録する。
  2. worker が index 完了する前に `/reviews/documents` を開く。
  3. 当該文書が承認可能に見えるか、また approval API が通るか確認する。

## 影響

- 営業デモへの影響: レビュー画面で `0チャンク` や未処理文書が承認可能に見えると、正式根拠化の説明が崩れる。
- 本番クライアントへの影響: reviewer が本文を確認できないまま承認し、後からindexされた内容が正式根拠化される可能性がある。
- セキュリティ/安全: high-risk answer の approved citation gate は chunk が無い間は満たせないが、index完了後に
  reviewer未確認の内容が approved として使われるリスクがある。
- データ品質: parse失敗、chunk欠落、embedding失敗を承認前に検知できない。
- UX: reviewer が「処理中」「確認可能」「承認可能」の違いを判断できない。

## どう解決すべきか

1. 実装方針:
   - document review projection に `parse_status` / `chunk_status` / `embedding_status` / `index_status` /
     `chunk_count` / `ingestion_run_id` を含める。
   - approval transition は、少なくとも `approved` へ進める前に index成功 + chunk_count > 0 を確認する。
   - 例外的に empty document を承認する必要がある場合は、専用理由と reviewer/admin gate を別にする。
2. UI/UX 方針:
   - `/reviews/documents` では `処理中` / `確認待ち` / `承認可能` / `処理失敗` を明確に分ける。
   - index未完了の行は承認ボタンを出さず、`処理状態を見る` / `再試行` を次アクションにする。
   - 承認前に本文/チャンクプレビューを確認できるようにする。
3. テスト方針:
   - queued/running PDF stub が承認不可であることを API test で固定する。
   - succeeded + chunk_count > 0 の陽性対照を追加する。
   - UI smoke で処理中行に承認ボタンが出ないことを確認する。
4. 移行や運用上の注意:
   - 既に approved だが chunk_count=0 / index status不明の文書を棚卸しする。
   - source sync status の projection と document review projection を揃える。

## QA checklist

- [x] 再現テストがある。
- [x] 正常系が確認できる。
- [x] 失敗時の表示/応答が確認できる。
- [x] tenant/ACL 境界を越えない。
- [x] security/safety gate を弱めていない。
- [x] API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- index未完了 / chunk_count=0 の文書は `approved` にできない。
- reviewer が処理状態と本文/チャンクプレビューを承認前に確認できる。
- parse/embed/index 失敗文書は承認ではなく再試行/除外の導線になる。
- source単位 bulk approval でも未index文書は既定除外される。
- 既存の安全ルール、ACL、監査要件を弱めていない。

## スコープ外

- full DMS / e-signature / 多段承認。
- vectorize 前の文書を高リスク回答に使えるようにする緩和。
- trusted datasource policy の自動拡大。

## 参照

- `src/raku_rag/production.py` (`ingest_document`, `_upsert_pending_document_stub`)
- `src/raku_rag/manufacturing/app.py` (`list_documents`, `get_document_detail`)
- `apps/web/app/components/FullSaasScreen.tsx` (`DocumentApprovalQueueBody`)
- [0070-source-level-document-review-drilldown-and-bulk-approval.md](0070-source-level-document-review-drilldown-and-bulk-approval.md)
