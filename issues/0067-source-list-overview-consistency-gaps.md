# 0067 — 外部接続一覧 / 追加フローの overview 一貫性ギャップ(source-list / onboarding)

> Priority: **P2/Medium** / Status: Fixed in working tree / Labels: `source-list`, `frontend-api`, `ux`, `qa`

## 背景(なぜ今)

`/sources/list` の frontend / API / backend / UIUX 改善レビュー中に、一覧用 overview API と追加フローの表示・状態遷移に一部ズレが見つかった。

## どんな課題か

- overview API は `credential_status` をトップレベルから読むが、Datasource repository は `config.credential_status` として公開しているため、一覧の認証状態が実データと一致しない。
- 追加画面は「保存 → 接続テスト → 同期開始」までは支援するが、「プレビュー → マッピング確認 → 同期開始」は詳細画面側に分離しており、追加フロー内で完結しない。
- Google OAuth の再接続時に接続テスト成功状態が明示的にリセットされないため、認可先変更後に古いテスト成功表示が残る可能性がある。

## どこで起きたか

- 画面: `/sources/list`, `/sources/new`
- API: `GET /v1/admin/datasources/overview`, `POST /v1/admin/sources/{source_id}/test-connection`, `POST /v1/admin/sources/{source_id}/preview`
- コード:
  - `apps/answer-service/server.py:_datasource_overview_rows`
  - `src/raku_rag/persistence/datasources.py:DataSourceRecord.to_public_dict`
  - `apps/web/app/components/FullSaasScreen.tsx:AddSourceBody`
  - `apps/web/app/components/FullSaasScreen.tsx:SourcePreviewPanel`
- 環境: local review
- run id / ingestion id / correlation id: n/a
- 再現条件: 認証情報付き datasource を登録し、`/sources/list` の認証表示を見る。新規 datasource 登録後にプレビューせず同期開始まで進める。

## 影響

- 営業デモへの影響: 認証済み接続が「認証: 種別設定」に見えるなど、運用状態の信頼感が落ちる。
- 本番クライアントへの影響: 初回設定時にプレビュー確認を飛ばして同期でき、マッピング品質の事前確認導線が弱い。
- セキュリティ、監査、データ品質、UX への影響: raw credential は漏れていないが、credential status の表示が不正確。プレビュー未統合はデータ品質 QA の抜けにつながる。

## どう解決すべきか

1. overview backend で `credential_status` を `source.credential_status || config.credential_status || (config.credential_ref ? "configured" : "missing")` のように安全に投影する。
2. 追加画面に接続テスト成功後の「プレビュー」ステップを入れ、既存 `SourcePreviewPanel` のロジックを再利用または共通化する。
3. OAuth 接続 ID が変わった時点で `connectionTest` を idle に戻し、同期ボタンを再テストまで無効化する。
4. API e2e / frontend unit または Playwright smoke で、認証済み表示・プレビュー後同期・OAuth 再接続時の状態リセットを確認する。

## QA checklist

- [x] 再現テストがある。
- [x] 正常系が確認できる。
- [x] 失敗時の表示/応答が確認できる。
- [x] tenant/ACL 境界を越えない。
- [x] security/safety gate を弱めていない。
- [x] API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- 認証済み datasource が overview 一覧で正しく「設定済み」と表示される。
- 新規追加フローで、接続テスト後に同期前プレビューとマッピング確認ができる。
- OAuth 再接続後は古い接続テスト成功状態で同期できない。
- regression test が追加または更新されている。
- 既存の安全ルール、ACL、監査要件を弱めていない。

## スコープ外

- 新しい外部 connector の追加。
- raw credential / refresh token の画面表示。
- demo-only bypass や security/safety gate の緩和。

## 参照

- `apps/answer-service/server.py`
- `src/raku_rag/persistence/datasources.py`
- `apps/web/app/components/FullSaasScreen.tsx`
- `packages/shared/src/dto/admin-settings.ts`
- 修正検証:
  - `PYTHONPATH=src python3 -m unittest tests.unit.test_datasource_overview -v`
  - `npm run typecheck --workspace @raku-rag/web`
  - `npm run test:api -- admin-settings.e2e-spec.ts`
  - `scripts/gate.sh a`
