# 0000 — 背景: データ運用標準化指針への採用度(調査結果)

> Status: Context（背景・判断材料） / 種別: 分析メモ
> 目的: 外部の「データ運用標準化指針(メダリオン / セマンティックレイヤー / オントロジー / MCP)」に対し、
> 本プロジェクトが現状どこまで採用しているかを実コードで突き合わせた結果。**[0005 Stop-Line](0005-non-goals-stop-line.md) の根拠。**

## 前提(重要)

当該指針は**定量(構造化)データのガバナンス指針**であり、指針自身が末尾で「定性(非構造化)データは
別途 RAG 戦略を策定」と切り出している。raku-rag は**まさにその RAG(定性)側のプロダクト**。
したがって指針の大半(メダリオン / dbt・Cube / Graph DB)は本来スコープ外で、比較の半分は
カテゴリ違い。ただし指針の**横断原則**(意味の層 / AI は契約経由 / 定量・定性分離)は対応する。

## 採用度サマリ

| 指針の層 | 採用度 | 根拠(file:line) |
|---|---|---|
| **定量/定性の分離**(指針の要石) | **◎ 全面採用・コードで強制** | `goal.md:165-173` ルーティング表 +「RAG で DB の代わりを作らない」。`services/structured_query.py` が集計/ランキング/最新値/数値/期間クエリを検索前に分類し、ツール未配線なら拒否(`refused_structured_tool_required`)。`services/answer.py:127` で retrieval 前に配線、`app.py:97`・`production.py:182` で structured tool 実装済み |
| **MCP = AI は定義ツール経由のみ / 生 SQL 禁止** | **○ 思想は採用・MCP プロトコル未採用** | LLM に生 SQL を書かせず `TableManifestStructuredTool` + `services`/`interfaces` 契約経由。プロダクトとして MCP サーバは未公開 |
| **オントロジー(層4)** | **△ ドメイン限定で部分採用・Graph DB ではない** | 製造ナレッジグラフ `TroubleCase↔FailureMode↔Countermeasure↔Document`(`manufacturing/domain/entities.py:177-301`、`manufacturing/knowledge/trouble_cases.py:63-75` の `InMemoryTroubleCaseStore`、`persistence/manufacturing_models.py` の多対多 join)。in-memory + RDB join、Protege/Neo4j/RDF 不使用、製造のみ |
| **セマンティックレイヤー(層2: 計算ロジック中央集権)** | **△ 形だけ部分採用・dbt/Cube ではない** | `industry/framework.py:326` の `KPIDefinition`(`formula`/`event_sources`/`aggregation_window`/`target_value` を industry profile に集約)。ただし `formula` は現状プレースホルダ(`"count_or_ratio_from_audit"`, 約 :1595)。governed metric store は無し |
| **メダリオン(層1: Bronze/Silver/Gold)** | **✗ 未採用** | grep ヒット 0。RAG 取込パイプライン(parse→chunk→embed→index + tombstone/ACL)は別形状。集計テーブル指向のデータ層ではない |
| **MCP 統合アクセス層(層3)** | **✗ プロトコル未採用** | 上記同様 |
| **意味の定義は人間主導 / データリテラシー** | **○ 別ドメインで対応物あり** | 安全境界は常に人間(ドラフト承認・高リスク主張・ハードゲート設計)= `CLAUDE.md` Loop Engineering |

## 用語の混同に注意

本リポジトリで「セマンティック」はほぼ**セマンティック埋め込み**(hashing 埋め込みの対義)を指し、指針の
「セマンティックレイヤー(dbt/Cube)」とは別物。真の "semantic layer" 言及は `goal.md:173` の1箇所のみで、
**外部の連携先(ルーティング目標)**として参照されているだけで未実装。

## raku-rag 独自の「意味の層」(定性側)

指針が最も恐れる「AI がもっともらしいが誤った主張をする」問題を、raku-rag は定性側で解いている:
`services/groundedness.py` の2段ゲート(根拠不足なら断る)+ 引用必須 + 承認状態 + 製造安全オーバーレイ
(高リスクは承認済み引用が無ければ言わない)。指針の定量側「セマンティックレイヤー/MCP 契約」に対応する、
**非構造化データ版の意味統制層**。

## 結論

指針の**最も知的な核(定量/定性の分離・RAG で DB を偽装しない・厳密値は定義済みツールへ)は raku-rag が
むしろ厳格にコードで強制して全面採用**。残る具体スタック(メダリオン / dbt・Cube / Graph DB / MCP)は、
RAG プロダクトという性質上スコープ外か、将来の統合先として参照のみ。→ **いま作り込むべきではない
([0005](0005-non-goals-stop-line.md))。** もし正式採用する場合の自然な接続点も同 issue に記載。
