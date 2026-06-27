---
name: "tenant-audit"
description: "モード3: テーマ別ディープダイブ。『1箇所漏れたら全部漏れる』前提で、全データアクセス経路のマルチテナント分離と RAG パイプライン品質を網羅的に潰す。スコープ未確認の経路は Blocker 候補として必ず挙げる。トリガー例『テナント分離監査』『RAG 品質監査』。"
argument-hint: "テーマ(tenant / rag)と対象経路範囲(任意)"
user-invocable: true
disable-model-invocation: false
---

## User Input

```text
$ARGUMENTS
```

# モード3: テーマ別ディープダイブ(テナント分離 / RAG)

**まず `docs/code-review/policy.md` の「共通原則」「正解情報の所在」を読むこと。**

**「1箇所漏れたら全部漏れる」前提で、全データアクセス経路を網羅的に潰す。**

入力: モード1 の項目5(データアクセス経路一覧)を起点にする。無ければ再探索する。
本リポジトリの起点ファイル: `src/raku_rag/core/tenancy.py`, `core/security/acl.py`,
`core/security/token.py`, `providers/vectorstores.py`(ベクトル検索フィルタ),
`observability/audit.py`, `infra/db/migrations/postgres/0001_core_rls.sql`・`0002_*_rls.sql`。

## マルチテナント分離(最優先)

- 全データアクセス経路で `tenant_id` 等のスコープが必ず効いているか
  - SQL の WHERE 句 / RLS(`infra/db/migrations/postgres/*.sql`)/ ORM のスコープ
  - **ベクトル検索のメタデータフィルタ(`src/raku_rag/providers/vectorstores.py` — テナント間 検索リークの有無)**
  - キャッシュ・ファイルストレージ・ログのテナント混在(`observability/audit.py` 等で raw context/PII/トークンを混在出力していないか)
- 認可: ロール × リソースの可否(`core/security/acl.py` は deny-by-default。権限昇格・IDOR の余地)
- **テナント ID の出所(クライアント任せ＝改ざん可能になっていないか。署名付き auth context 由来が必須。リクエストボディ上書きは禁止)**
- レート制限・コスト上限のテナント単位適用

## RAG パイプライン品質

- チャンク分割・埋め込みモデルのバージョン整合(**投入時 ⇔ 検索時** — 埋め込みプロバイダ(offline hashing / OpenAI opt-in)が ingest と query で一致しているか)
- retrieval フィルタにテナントスコープが必須で入っているか(再掲・最重要)
- プロンプトインジェクション対策(取得文書を命令として扱わない設計か)
- 出力の根拠 / 引用、ハルシネーション対策、eval の有無(groundedness / citation)
- 製造オーバーレイの hard rule: 高リスク回答は approved+effective な証拠が無ければ assertion しない / AI 生成物は `draft` 固定 / draft・obsolete は参照専用
- トークン / コスト上限、リトライ・タイムアウト、PII の取り扱い

## 進め方と出力

1. データアクセス経路を1つずつ列挙し、各経路で「テナント分離が効く根拠 `file:line`」を確認
2. スコープが確認できない経路は **Blocker 候補として必ず挙げる**(漏れの疑いは見逃さない)
3. RAG は「投入時」と「検索時」の設定整合を必ず突き合わせる

出力:

| # | 重大度 | カテゴリ(テナント分離/認可/RAG) | 内容 | 該当経路・根拠(file:line) | 影響 | 修正案 |

末尾に「テナント分離が確認できた経路一覧」と「スコープ未確認・要確認の経路」を分けて列挙。
最後にカバレッジ: モード1 の全経路をカバーしたか自己チェックし、未確認を列挙する。
