# 0005 — Non-Goals / Stop-Line(いまやらないこと)

> Status: Proposed(方針) / Labels: `scope`, `non-goals`
> 目的: 早期安定化を守るため、**CTO として「いまは No」と言う線**を明文化する。
> 根拠は [0000 採用度分析](0000-context-data-governance-adoption.md)。

## 原則

柔軟なデータ基盤の核心(継ぎ目 + 無停止 reindex + 定量/定性ルーター)は**既にある**
([README](README.md))。いま新しい抽象/バックエンドを足すと、硬くすべき表面積が増えて安定化が遅れる。
**供給管理されたペース(~1–2h/日、`docs/loop-engineering.md`)で「多数企業導入」を成立させる唯一の道は、
スコープを不可逆な core(0001–0004)に絞ること。** 制約自体がこの結論を後押しする。

## いまは作らない(Stop-Line)

| 項目 | なぜ今やらないか | 解禁条件 |
|---|---|---|
| **Graph DB / 汎用オントロジー基盤** | 製造の in-memory グラフ(`manufacturing/knowledge/trouble_cases.py`)で需要は満たせている | 複数顧客が横断調査(系統を跨ぐ関係辿り)を要求したとき |
| **dbt / Cube をインフラ採用** | `structured_tool` の継ぎ目(`services/structured_query.py`)で後から非破壊に差せる | 有償顧客が重い BI/集計を要求したとき。既存ルーターの裏へ差す |
| **MCP 公開** | プロダクト要件ではない。薄いアダプタで後付け可能 | 顧客/パートナーが MCP 経由のツール利用を要求したとき |
| **メダリオン(Bronze/Silver/Gold)** | これは raku-rag 本体でなく**上流データ基盤**の話 | 別プロジェクトとして扱う(本体スコープ外) |
| **新しい汎用 VLM 基盤 / 画像理解バックエンドの過剰抽象** | PDF/画像の production ingestion は現行スコープに入った。一方で、新しい VLM 基盤・Graph 的な画像知識基盤・別プロトコル層まで広げると安定化が遅れる | 顧客要件として既存 provider seam で足りない視覚推論が明確になったとき |
| **製造以外の新業種** | 多テナント core が「実バックエンドで緑」になる前に増やすと検証負債が増える | 0001 完了後 |
| **新しい抽象レイヤ全般** | 継ぎ目は十分。抽象追加 = 安定化の遅延 | core 安定化(完了定義)達成後 |

## 「いまやらない」≠「設計を閉ざす」— 将来の自然な接続点

正式採用する場合、既に `goal.md` が示す差込口を使う(非破壊):

1. `TableManifestStructuredTool`(現状は決定論的な表クエリ)を**実 dbt/Cube セマンティックレイヤーに
   差し替え/前段化** → 指針の層2を本物にする。
2. その structured tool を **MCP ツールとして公開** → 層3(MCP 契約)を満たす。
   `services/answer.py` の routing はそのまま使える。
3. 製造ナレッジグラフを **Graph DB に外出し** → 層4(横断調査)を一般化。

いずれも**既存の継ぎ目の裏側の差し替え**であり、core を作り直さない。だから今は急がない。

## 守るべき不変則(広げない代わりに徹底する)

- 新コードを**具体ストア/具体埋め込みモデルに直結させない**(必ず `interfaces/base.py` 経由)。
- 定量クエリは**必ず**ルーター(`services/structured_query.py`)を通す(RAG に DB を偽装させない)。
- 新データ経路は**必ず** tenant scope を構造で強制(0002)。

## 参照

- [README](README.md) / [0000](0000-context-data-governance-adoption.md)
- `docs/loop-engineering.md`, `goal.md:165-173`
