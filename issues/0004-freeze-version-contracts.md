# 0004 — 契約 v1 凍結 + バージョニング(耐力壁 D)

> Priority: **P2** / Status: Proposed / Labels: `foundation`, `contracts`, `api`, `compatibility`

## 背景(なぜ今)

企業が連携を始めた後、契約(API / インターフェース / ツール I/O)の破壊的変更は
**顧客調整付きの移行**になる。多テナント前に v1 を固め、破壊的変更にバージョン規律を敷くと安い。

## 現状(根拠)

- バックエンド継ぎ目は `src/raku_rag/interfaces/base.py`(Parser/Chunker/EmbeddingProvider/VectorStore)
  と `interfaces/visual.py` に抽象化済み。
- API 契約(openapi)は維持されている(直近コミット `2d4061a` で openapi/CORS/env を同期)。
- structured-tool の I/O 契約は `services/structured_query.py` / `services/structured_tables.py` に存在。
- 002 のコントラクト群: `specs/002-manufacturing-field-knowledge-rag/contracts/`(mfg-openapi.md, mfg-interfaces.md)。

## ギャップ

契約は在るが、**「v1 として凍結し、破壊的変更を検出/バージョニングする規律」が明示されていない**。
継ぎ目を後から気軽に変えると、外部連携・既存テナント・SDK が壊れる。

## 提案作業

1. **v1 の境界を確定** — 外部に露出する契約(public API、SDK が依存する型、structured-tool I/O、
   webhook/イベント形)を列挙し「v1 凍結」とマーク。内部実装の継ぎ目(差し替え自由)と明確に分離。
2. **破壊的変更の検出** — openapi/型の差分を CI で検査し、後方非互換変更を **明示的な version bump
   なしには通さない**(`boundary-audit` skill の観点を CI 化)。
3. **バージョニング方針** — 追加は非破壊、破壊は v2 並走 + 廃止期限。`docs/` に1枚で明文化。

## 受け入れ条件(Definition of Done)

- [ ] 「v1 凍結対象 = 外部契約」と「自由に変えてよい内部継ぎ目」の一覧が `docs/` にある。
- [ ] openapi/公開型の後方非互換変更を CI が検出して落とす(version bump 必須)。
- [ ] バージョニング/廃止方針が明文化され、レビュー観点に入っている。

## スコープ外

- GraphQL/gRPC など新トランスポートの導入。
- SDK の多言語展開(別 issue)。

## 参照

- コード: `src/raku_rag/interfaces/base.py`, `services/structured_query.py`, `services/structured_tables.py`
- 契約: `specs/002-manufacturing-field-knowledge-rag/contracts/`、直近コミット `2d4061a`
- skill: `.claude/skills/boundary-audit/SKILL.md`(モード2)
