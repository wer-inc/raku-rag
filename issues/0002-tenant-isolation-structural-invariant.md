# 0002 — テナント分離を「規律」から「構造的不変条件」へ(耐力壁 A)

> Priority: **P1** / Status: Proposed / Labels: `foundation`, `security`, `multi-tenant`, `irreversible`

## 背景(なぜ今)

マルチテナント RAG の存在リスクは**クロステナント漏れ**(「1箇所漏れたら全部漏れる」=
`tenant-audit` skill の前提)。多数テナントが乗った後に分離モデルを変えるのは極めて高価かつ危険。
**いま、漏れが構造的に起き得ない形にしておく**のが最も安い。

## 現状(根拠)— 他社平均より良い

- 全永続化メソッドが `tenant_id` で絞っている:
  `persistence/datasources.py:130,152`(`WHERE tenant_id = %s`)、
  `persistence/manufacturing_governance.py:68,94`、in-memory も `if t == tenant_id`
  (`persistence/oauth_connection.py:101`, `control_plane.py:206`)。
- 明示ガード `enforce_same_tenant(principal, resource_tenant_id=...)`(`persistence/manufacturing_audit.py:85`)。
- 検索は principal のテナントで scope(`services/retrieval.py:78,223`)。
- Postgres RLS + 専用セキュリティテスト(`tests/security/test_tenant_isolation.py`,
  `tests/security/test_rls_pgvector.py`)。
- ACL deny-by-default pre-filter / tombstone(`CLAUDE.md` 001 base platform)。

## ギャップ

今は **「アプリ層 pre-filter が境界」+ 規律 + テスト**。すなわち**新しいデータ経路を後から足した人が
`WHERE tenant_id` を1つ忘れたら漏れる**(規律依存)。境界が "破れない構造" になっていない。

## 提案作業

1. **RLS を "真の床" に(defense-in-depth)** — アプリ pre-filter は速度のための上段に格下げし、
   **DB の RLS を最終かつ非バイパスの境界**として全テナント所有テーブルに強制。
   接続ロールが `tenant_id` を必ず session 変数で持つ運用に統一。
2. **未スコープ経路の機械検出ゲート** — 新規/既存の永続化クエリが tenant scope を欠く場合に CI で落とす
   仕組み(静的 lint or リポジトリ層の型/ラッパ強制 = 「scope を渡さないとクエリできない」API 形)。
3. **負の証明テスト** — テナント B のリソースを A の principal で要求したら**必ず空/拒否**を、
   全リソース種別(document/chunk/citation/draft/audit/datasource/eval)で網羅(0001 soak と連動)。

## 受け入れ条件(Definition of Done)

- [ ] 全テナント所有テーブルに RLS が有効で、アプリ pre-filter を外しても漏れない(RLS 単体で守れる)。
- [ ] tenant scope を欠く永続化クエリを足すと CI が落ちる(意図的に注入したテストで確認)。
- [ ] 全リソース種別でクロステナント負の証明テストが緑(0001 の soak に内包)。

## スコープ外

- 認証/トークン発行の作り直し(別領域。本 issue は**データ境界**のみ)。
- フィールドレベル暗号化・テナント別 KMS(将来。まず漏れない構造)。

## 参照

- skill: `.claude/skills/tenant-audit/SKILL.md`(モード3)
- コード: `services/retrieval.py`, `persistence/*.py`, `tests/security/test_tenant_isolation.py`, `test_rls_pgvector.py`
