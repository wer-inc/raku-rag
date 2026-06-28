# 0014 — 「承認ルール」画面が編集不能＋GET/PUT エンドポイント未実装(系統 ③)

> Priority: **P2 / Medium** / Status: Open / Labels: `frontend`, `backend`, `settings`, `approval`, `gap`

## 背景(なぜ今)

ナビ「承認ルール」(`/reviews/settings`)は、名前上は承認ワークフローを**設定**する画面。manifest も
`approval_rules / required_reviewers / state_transitions / delegation_policy / audit_requirements` を
扱う管理面として定義(`specs/full-saas/screens.manifest.json:278`)。だが実体は**読み取り専用＋保存されない
textarea**で、肝心の API も未実装。「設定できる」という誤った約束になっている。

## 現状(根拠)

- `ApprovalWorkflowBody`(`apps/web/app/components/FullSaasScreen.tsx:4074-4099`):
  - `manufacturingGovernanceStatus` を GET し、真偽 3 行(AI 出力は常にドラフト / レビュー担当必須 /
    高リスクは承認済み引用必須)を **read-only** で表示(`:4087-4089`)。値は `governance_status` が
    リテラル `True` を返すだけ(`manufacturing/api/policy.py:177-180`)。
  - 唯一の「編集」要素=「設計メモ」`<textarea>` はローカル `useState('memo')` に紐づくだけで
    **保存ボタンも PUT も無い**(`:4093-4094`)。入力はリロード/遷移で破棄。既定値が英語のプレースホルダ
    "Review flow is controlled by governance status."(`:4075`)で UI 言語と不一致。
- **API 不在**:`GET/PUT /v1/manufacturing/approval-workflow` は manifest で `status:"missing"`
  (`screens.manifest.json:281-282`)、`specs/full-saas/gaps.md:22-23` にも未実装として記載。
  `api-client.ts` に `manufacturingApprovalWorkflow` 系の関数も無し(client では `GET /policy/data-use` のみ、
  PUT は未配線)。
- RBAC 齟齬:manifest は当画面を `tenant_admin` 限定とするが nav-rbac は reviewer に開放(→[0011](0011-rbac-reviewer-cannot-approve.md))。

## 提案作業(何をどう対応)

**Option A(暫定・最小, 数時間):誤解の解消**
- textarea を `disabled`/read-only にし、「この画面は現状の承認ポリシーの**表示のみ**。ルールは
  ガバナンス設定で中央管理(編集は今後対応)」のバナーを出す。英語初期値を撤去。
- これで「保存したのに消える」サイレントデータロスを止める。

**Option B(本筋・推奨):実際に編集可能にする**
1. **バックエンド**:`GET/PUT /v1/manufacturing/approval-workflow` を実装。返す/受ける構造は manifest の
   `approval_rules / required_reviewers / state_transitions / delegation_policy / audit_requirements`
   (`screens.manifest.json:278`)。PUT は **opt-in/version-bump/監査**を `update_data_use_policy`
   (`manufacturing/api/policy.py:123-134`)と同パターンで(変更は `policy.setting.change` 等で audit)。
   - 初期スコープとして、既にある**データソース信頼/承認ポリシー**(`config.approval_policy`:
     `trusted→approved+imported` / 既定 `review_required→pending_review`、
     `src/raku_rag/services/datasource_sync.py`、メモリ `datasource-trust-policy-review`)を
     この画面で参照・編集できるようにすると整合が良い(「同期文書を自動承認するソース」の管理 UI)。
2. **client**:`manufacturingGetApprovalWorkflow` / `manufacturingUpdateApprovalWorkflow` を `api-client.ts` に追加。
3. **UI**:read-only 3 行を「編集フォーム」に置換(既定承認ポリシー、必須レビューア数/グループ、自動承認ソース等)。
   manifest が宣言する `saving / validation_error` 状態を実装。memo textarea は廃止 or 永続化フィールド化。

## 受け入れ条件(DoD)

- [ ] (A 採用時)保存できない UI に「保存できない」ことが明示され、入力が消えて誤解させない。
- [ ] (B 採用時)承認ポリシーを編集→保存→再読込で反映、変更が監査ログに残る。
- [ ] 画面の RBAC が manifest と一致(→[0011](0011-rbac-reviewer-cannot-approve.md))。
- [ ] 英語プレースホルダ等の言語不一致が無い。

## スコープ外

- フル DMS / 電子署名 / 任意ロールバック(002 で out-of-scope)。

## 参照

- `apps/web/app/components/FullSaasScreen.tsx:4074-4099`, `apps/web/lib/api-client.ts:437`
- `src/raku_rag/manufacturing/api/policy.py:118-187`, `src/raku_rag/services/datasource_sync.py`(approval_policy)
- `specs/full-saas/screens.manifest.json:273-285`, `specs/full-saas/gaps.md:22-23`
