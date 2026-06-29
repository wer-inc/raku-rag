# 0035 — PR #16 CI lint / secret-scan regression(系統 = QA / security)

> Priority: **P2/Medium** / Status: Addressed in PR #16 / Labels: `ci`, `security`, `qa`

## 背景(なぜ今)

PR #16 を `develop` に merge 可能にするため branch を最新 `develop` に載せ直した後、
GitHub Actions run `28347570764` で Python lint と Secret scan が失敗した。ruff 修正後に
CI と同じ unpinned `black` 最新版でも複数ファイルの formatting drift が検出される状態だった。

## どんな課題か

- `src/raku_rag/services/retrieval.py` に `RetrievalService.is_visible` が 2 回定義され、
  ruff `F811` で Python lint が失敗した。
- `apps/api/test/chat.e2e-spec.ts` の e2e 用ダミー secret 値が allowlist されておらず、
  detect-secrets が本物の secret 候補として検出した。
- CI がインストールする `black` 最新版では、既存の Python ファイル 14 件が再整形対象になった。
- 期待挙動は、CI が本物の品質/漏洩リスクだけを検知し、テスト専用 dummy 値や重複定義で
  merge がブロックされないこと。

## どこで起きたか

- 画面: GitHub PR #16 checks
- API: なし
- コード:
  - `src/raku_rag/services/retrieval.py`
  - `apps/api/test/chat.e2e-spec.ts`
  - CI `black --check src tests workers` が指摘した Python files
- 環境: GitHub Actions
- run id / ingestion id / correlation id: run `28347570764`, Python job `83973924449`
- 再現条件: PR #16 head を push して Python lint / Secret scan workflow を実行する。

## 影響

- 営業デモへの影響: なし。ただし CI が赤いままだと demo/prod-readiness PR を merge できない。
- 本番クライアントへの影響: なし。ただし `is_visible` 重複はコードレビュー上の安全性説明を曖昧にする。
- セキュリティ、監査、データ品質、UX への影響: Secret scan の false positive が残ると、
  本物の secret 検出とノイズの区別がしづらくなる。

## どう解決すべきか

1. 実装方針: 実行時に有効だった後方の `is_visible` を残し、前方の重複定義を削除する。
2. UI/UX 方針: UI 変更なし。
3. テスト方針: ruff / black / secret scan / separation / Tier A gate を再実行する。
4. 移行や運用上の注意: test-only dummy secret には inline allowlist comment を残す。

## QA checklist

- [x] 再現テストがある。
- [x] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [x] tenant/ACL 境界を越えない。
- [x] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- 課題の根本原因が解消されている。
- regression test が追加または更新されている。
- 本番想定の UX として説明可能である。
- 既存の安全ルール、ACL、監査要件を弱めていない。

## スコープ外

- detect-secrets baseline の緩和。
- ACL / citation revalidation の仕様変更。
- demo-only flag や security/safety gate の bypass。

## 参照

- PR #16
- GitHub Actions run `28347570764`
- Python job `83973924449`
