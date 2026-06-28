# NNNN — 課題タイトル(系統 = area / theme)

> Priority: **P?/Low|Medium|High|P0** / Status: Open / Labels: `area`, `theme`

## 背景(なぜ今)

この課題が見つかった経緯を書く。

## どんな課題か

- ユーザーまたは運用上、何が困るのか。
- 期待挙動と実際の挙動の差分。
- 関連する副次課題があれば明記する。

## どこで起きたか

- 画面:
- API:
- コード:
- 環境:
- run id / ingestion id / correlation id:
- 再現条件:

## 影響

- 営業デモへの影響。
- 本番クライアントへの影響。
- セキュリティ、監査、データ品質、UX への影響。

## どう解決すべきか

1. 実装方針。
2. UI/UX 方針。
3. テスト方針。
4. 移行や運用上の注意。

## QA checklist

- [ ] 再現テストがある。
- [ ] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- 課題の根本原因が解消されている。
- regression test が追加または更新されている。
- 本番想定の UX として説明可能である。
- 既存の安全ルール、ACL、監査要件を弱めていない。

## スコープ外

- 今回やらないこと。
- 安易な bypass、demo-only flag、security/safety の緩和。

## 参照

- 関連 spec / docs / PR / runbook / trace。
