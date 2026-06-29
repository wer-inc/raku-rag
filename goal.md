# 1. まず結論：このChatBotの定義

## 作りたいもの

**既存RAGシステムを根拠エンジンとして呼び出しながら、お客さんと複数ターン会話し、必要な情報を聞き取り、回答・案内・手続き・人間への引き継ぎまで行う対話型ChatBot。**

## 作ってはいけないもの

```text
ユーザー: 解約方法を教えて
Bot: 解約方法はこちらです。
終了
```

これはただのFAQ Botです。

## 作るべきもの

```text
ユーザー: 解約したいです

Bot:
承知しました。解約についてご案内します。
まず、ご契約を確認するため、登録メールアドレスを教えてください。

ユーザー:
xxx@example.com

Bot:
ありがとうございます。次に、会社名または契約者名を教えてください。

ユーザー:
ABC株式会社です

Bot:
確認しました。現在のご契約では、解約は月末扱いになります。
月途中でも日割り返金はありません。
この内容で解約申請を進めますか？

ユーザー:
はい

Bot:
承知しました。解約申請を受け付けました。
受付番号は C-12345 です。
```

つまり、必要なのは **RAG Bot** ではなく、より正確には **RAG連携型の業務対話エージェント** です。

---

# 2. 全体アーキテクチャ要件

## 推奨構成

```text
[Customer]
    ↓
[Chat UI]
    ↓
[Chat API / WebSocket / SSE]
    ↓
[Conversation Orchestrator]
    ├─ Session Manager
    ├─ Intent Classifier
    ├─ Scenario Engine
    ├─ Slot Filling
    ├─ RAG Connector
    ├─ Business API Connector
    ├─ Guardrail Engine
    ├─ Human Handoff Engine
    └─ Logging / Evaluation
    ↓
[Response Generator]
    ↓
[Customer]
```

裏側：

```text
[Existing RAG System]
    ├─ Search / Retrieve API
    ├─ Generate API
    ├─ Citation / Source API
    └─ Feedback API

[Data Stores]
    ├─ chat_sessions
    ├─ chat_messages
    ├─ conversation_states
    ├─ scenarios
    ├─ handoffs
    ├─ tickets
    ├─ rag_logs
    ├─ evaluations
    └─ audit_logs
```

AWS構成としては、認証に Amazon Cognito、ログに CloudWatch Logs、監査に CloudTrail、秘密情報管理に Secrets Manager、非同期処理に SQS、ワークフロー制御に Step Functions などを組み合わせるのが自然です。Cognito User Pool はWeb/モバイルアプリの認証・認可用ユーザーディレクトリとして使え、Secrets Manager はDB認証情報・OAuthトークン・APIキーなどの管理、取得、ローテーションに使えます。([AWS ドキュメント][2])

---

# 3. スコープ整理

## 今回作るもの

| 領域       | 作る内容                  |
| -------- | --------------------- |
| Chat UI  | お客さんが会話する画面           |
| Chat API | フロントからメッセージを受けるAPI    |
| 会話制御     | 何を聞くか、次に何をするかを判断      |
| 状態管理     | 会話途中の情報を保持            |
| 既存RAG連携  | RAG APIを呼び出して回答・根拠を取得 |
| シナリオ管理   | 問い合わせ別の会話フロー          |
| スロット収集   | 必要情報の聞き取り             |
| ガードレール   | 答えてはいけない内容を制御         |
| ハンドオフ    | 人間・チケット・担当部署へ引き継ぎ     |
| 履歴管理     | 会話、回答、根拠、判断ログを保存      |
| 管理画面     | 履歴、シナリオ、評価、転送状況を確認    |
| 分析       | 解決率、転送率、未回答、顧客満足度など   |

## 今回作らない、または既存RAG側の責任にするもの

| 領域          | 理由                            |
| ----------- | ----------------------------- |
| ナレッジ登録処理    | 既存RAGにある前提                    |
| embedding生成 | 既存RAGにある前提                    |
| ベクトル検索基盤    | 既存RAGにある前提                    |
| 文書チャンク管理    | 既存RAGにある前提                    |
| RAG精度改善     | 既存RAG側。ただしChatBotからフィードバックは送る |
| ナレッジ承認フロー   | 既存RAGにあれば流用。なければ後続で検討         |

ただし、ChatBot側でも **どのRAG回答を使ったか、どの根拠を表示したか、信頼度がどうだったか** は必ず記録します。

---

# 4. 既存RAG連携要件

ここが最重要です。

## 4.1 RAG API接続方式

既存RAGとは、最低限以下のどれかで接続できる必要があります。

| 接続方式        | 内容                              |
| ----------- | ------------------------------- |
| REST API    | 最も扱いやすい                         |
| GraphQL API | 複数情報をまとめて取得しやすい                 |
| gRPC        | 高速だが実装がやや重い                     |
| SDK         | 既存RAGの専用SDKをChatBot backendから呼ぶ |
| 内部HTTP      | 同一VPCまたはPrivateLink経由           |
| Queue連携     | 非同期処理向き。ただし会話応答には遅い             |

MVPでは **REST API** が一番よいです。

---

## 4.2 RAGリクエスト要件

ChatBotからRAGへ渡すべき情報です。

```json
{
  "tenant_id": "tenant_001",
  "user_id": "user_001",
  "session_id": "sess_001",
  "message_id": "msg_001",
  "query": "解約したいです",
  "conversation_summary": "ユーザーは契約解約を希望している",
  "conversation_history": [
    {
      "role": "user",
      "content": "解約したいです"
    }
  ],
  "intent": "cancel_subscription",
  "scenario_id": "scenario_cancel_v1",
  "channel": "web_chat",
  "language": "ja",
  "filters": {
    "category": ["contract", "cancel"],
    "product_id": "prod_001",
    "customer_type": "business",
    "effective_date": "2026-06-28"
  },
  "top_k": 5,
  "need_citations": true,
  "need_confidence": true,
  "response_mode": "answer_with_sources"
}
```

## 4.3 RAGレスポンス要件

RAGからは、最低限これを返してほしいです。

```json
{
  "answer": "解約は管理画面の契約設定から申請できます。月途中の解約でも当月分は日割り返金されません。",
  "sources": [
    {
      "source_id": "doc_123",
      "chunk_id": "chunk_456",
      "title": "契約・解約ポリシー",
      "url": "https://example.com/policy",
      "page": 3,
      "snippet": "月途中の解約であっても、当月分の利用料金は返金されません。",
      "score": 0.91,
      "document_version": "2026-05-01"
    }
  ],
  "confidence": 0.88,
  "answerable": true,
  "needs_clarification": false,
  "clarification_question": null,
  "risk_flags": [],
  "suggested_next_actions": [
    "confirm_cancel_policy",
    "ask_final_confirmation"
  ],
  "trace_id": "rag_trace_001",
  "latency_ms": 1230
}
```

## 4.4 RAGが返すべき判定

| 判定                     | 必須度 | 内容              |
| ---------------------- | --: | --------------- |
| answerable             |  必須 | 回答可能か           |
| confidence             |  必須 | 信頼度             |
| sources                |  必須 | 根拠文書            |
| no_answer_reason       |  必須 | 回答不可理由          |
| needs_clarification    |  必須 | 追加質問が必要か        |
| clarification_question |  推奨 | RAG側が提案する聞き返し   |
| risk_flags             |  必須 | 法務、返金、契約、個人情報など |
| source_version         |  必須 | 文書バージョン         |
| trace_id               |  必須 | 調査用ID           |
| latency_ms             |  必須 | 遅延計測            |

Amazon Bedrock Knowledge Bases の `RetrieveAndGenerate` は、ナレッジベースを検索し、取得結果と指定モデルを使って回答を生成し、レスポンスでは関連するソースのみを引用するAPIとして提供されています。既存RAGがBedrockでなくても、ChatBot側のRAG連携APIはこれに近い入出力にしておくと後で差し替えやすいです。([AWS ドキュメント][3])

---

# 5. ChatBot会話制御要件

## 5.1 会話状態管理

複数回やり取りするには、毎ターン以下を保存します。

```json
{
  "session_id": "sess_001",
  "current_intent": "cancel_subscription",
  "current_scenario_id": "scenario_cancel_v1",
  "current_step": "verify_customer",
  "collected_slots": {
    "email": "xxx@example.com",
    "company_name": null,
    "contract_id": null,
    "cancel_reason": null
  },
  "missing_slots": [
    "company_name",
    "contract_id"
  ],
  "last_rag_sources": [
    "doc_123"
  ],
  "handoff_required": false,
  "status": "in_progress"
}
```

これがないと、Botは毎回「その場の質問に答えるだけ」になります。

---

## 5.2 意図判定

ユーザー発話から問い合わせ種別を判定します。

| intent              | 例        |
| ------------------- | -------- |
| faq_general         | 一般FAQ    |
| pricing_question    | 料金問い合わせ  |
| cancel_subscription | 解約       |
| login_issue         | ログインできない |
| billing_issue       | 請求       |
| contract_change     | 契約変更     |
| product_trouble     | 不具合      |
| complaint           | クレーム     |
| request_human       | 人間希望     |
| sales_consultation  | 導入相談     |
| unknown             | 不明       |

要件：

```text
- 毎ターンintentを判定する
- 会話途中でintentが変わった場合に検知する
- 複数intentが含まれる場合は優先度を決める
- 高リスクintentは人間転送候補にする
- unknownが続く場合は聞き返しまたは人間転送する
```

---

## 5.3 シナリオ管理

問い合わせ種別ごとに、会話フローを定義します。

例：解約シナリオ

```yaml
scenario_id: scenario_cancel_v1
intent: cancel_subscription
steps:
  - id: identify_customer
    required_slots:
      - email
      - company_name
  - id: explain_policy
    use_rag: true
    rag_filters:
      category: contract_cancel
  - id: confirm_final
    required_slots:
      - final_confirmation
  - id: create_ticket
    action: create_cancel_ticket
  - id: complete
    message: 解約申請を受け付けました。
handoff_conditions:
  - refund_request
  - legal_claim
  - angry_customer
  - customer_requests_human
```

要件：

```text
- シナリオはバージョン管理する
- 公開中 / 下書き / 停止中を管理する
- シナリオごとに開始条件を持つ
- ステップごとに必要スロットを定義する
- ステップごとにRAGを使うか定義する
- ステップごとに業務APIを使うか定義する
- ステップごとに人間転送条件を定義する
- 過去の会話がどのシナリオバージョンで処理されたか記録する
```

---

## 5.4 スロット収集

Botが最後まで進めるには、必要情報を順番に集めます。

例：導入相談

```text
- 会社名
- 担当者名
- メールアドレス
- 問い合わせチャネル
- 月間問い合わせ件数
- 現在の課題
- 希望機能
- 導入希望時期
```

要件：

```text
- 必須スロットを定義できる
- 任意スロットを定義できる
- ユーザー発話から複数スロットを一度に抽出できる
- 足りないスロットだけ質問する
- 入力形式を検証する
- 間違いを訂正できる
- ユーザーが話題を変えた場合にシナリオ変更できる
- 入力したくない場合はスキップまたは人間転送できる
```

---

## 5.5 聞き返し

Botは不明な時に自然に聞き返します。

| 状況      | Botの動き                       |
| ------- | ---------------------------- |
| 意図が不明   | 「どの内容についてのご相談でしょうか？」         |
| 情報不足    | 「契約確認のため、登録メールアドレスを教えてください」  |
| 曖昧      | 「料金プランについてですか？請求金額についてですか？」  |
| RAG根拠不足 | 「確認できる情報が不足しているため、担当者に確認します」 |
| 入力形式エラー | 「メールアドレスの形式で入力してください」        |
| 同じ失敗が続く | 人間へ転送                        |

---

# 6. 応答生成要件

## 6.1 応答方針

Botの回答は、以下のルールにします。

```text
- 根拠がある内容だけ回答する
- 根拠が弱い場合は断定しない
- ユーザーの目的に合わせて次の質問をする
- 長すぎる回答を避ける
- 1回の発話で質問を詰め込みすぎない
- 手続き系では最後に確認を取る
- 完了時には受付番号や次のアクションを提示する
- 高リスク領域では人間へ渡す
```

## 6.2 回答形式

ChatBotは、回答本文だけでなく、UIで使いやすい構造化レスポンスを返すべきです。

```json
{
  "message": "解約は管理画面の契約設定から申請できます。月途中の解約でも当月分は日割り返金されません。この内容で手続きを進めますか？",
  "message_type": "normal",
  "quick_replies": [
    {
      "label": "進める",
      "value": "yes"
    },
    {
      "label": "人間に相談する",
      "value": "handoff"
    }
  ],
  "sources": [
    {
      "title": "契約・解約ポリシー",
      "url": "https://example.com/policy",
      "page": 3
    }
  ],
  "state": {
    "current_step": "confirm_final",
    "status": "waiting_user"
  }
}
```

## 6.3 UIに表示するべき情報

| 表示要素    | 必須度 | 内容            |
| ------- | --: | ------------- |
| Bot回答   |  必須 | 本文            |
| 根拠リンク   |  必須 | 参照元           |
| クイック返信  |  推奨 | はい/いいえ/人に相談   |
| 入力フォーム  |  推奨 | メール、電話番号、日時など |
| 処理中表示   |  必須 | Botが考えている間    |
| エラー表示   |  必須 | 失敗時           |
| 人間転送ボタン |  必須 | いつでも人に渡せる     |
| 会話終了ボタン |  推奨 | 解決済みにできる      |
| フィードバック |  推奨 | 役に立った/立たない    |

---

# 7. 人間ハンドオフ要件

これは必須です。AIで無理に完結させない設計にします。

## 7.1 ハンドオフ条件

| 条件      | 内容                            |
| ------- | ----------------------------- |
| ユーザーが希望 | 「人につないで」「担当者に聞きたい」            |
| RAG根拠不足 | answerable=false、confidence低い |
| 高リスク    | 返金、契約変更、法務、個人情報、クレーム          |
| 感情悪化    | 怒り、不満、強い困惑                    |
| 連続失敗    | 2〜3回聞き返しても解決しない               |
| 業務API失敗 | 顧客情報取得、チケット作成に失敗              |
| 権限不足    | Botが処理できない操作                  |
| 本人確認失敗  | 認証できない                        |
| VIP顧客   | 優先対応が必要                       |
| システム障害  | RAG/API/DBの障害                 |

## 7.2 ハンドオフ方式

| 方式               | 内容                         |
| ---------------- | -------------------------- |
| チケット作成           | Zendesk、Freshdesk、独自チケットなど |
| メール通知            | 担当者へ会話要約を送る                |
| Slack通知          | 社内チャンネルへ通知                 |
| 有人チャット           | オペレーターがその場で引き継ぐ            |
| 折り返し予約           | 電話・メールで折り返す                |
| Amazon Connect連携 | 将来的に電話対応と統合                |

## 7.3 引き継ぎ時に渡す情報

```text
- session_id
- user_id
- 顧客名
- メールアドレス
- 会社名
- 問い合わせ分類
- 会話要約
- 会話全文
- 収集済みスロット
- 未確認項目
- RAGが参照した根拠
- RAG confidence
- 転送理由
- 推奨対応
- 優先度
```

## 7.4 ユーザー向け表示

```text
担当者に引き継ぎます。
ここまでの内容は担当者に共有されるため、同じ説明を繰り返す必要はありません。
```

これ、大事です。
お客さんが二度説明するのは地味にかなりストレスです。

---

# 8. 管理画面要件

## 8.1 会話履歴管理

| 機能      | 内容                           |
| ------- | ---------------------------- |
| 会話一覧    | 日時、ユーザー、問い合わせ種別、結果           |
| 会話詳細    | 全メッセージ、Bot応答、根拠、状態           |
| 検索      | session_id、メール、会社名、intent、日付 |
| フィルタ    | 解決済み、未解決、転送済み、低評価            |
| 会話要約    | 自動要約                         |
| RAG根拠表示 | 参照文書、chunk、score             |
| スロット表示  | 収集済み情報                       |
| ハンドオフ履歴 | 転送先、理由、担当者                   |
| エクスポート  | CSV、JSON                     |

## 8.2 シナリオ管理

| 機能        | 内容              |
| --------- | --------------- |
| シナリオ一覧    | intent別         |
| シナリオ作成    | ステップ、分岐、条件      |
| スロット定義    | 必須/任意、型、検証ルール   |
| RAGフィルタ設定 | カテゴリ、製品、顧客種別    |
| ハンドオフ条件   | 条件と転送先          |
| 公開管理      | 下書き、レビュー中、公開、停止 |
| バージョン管理   | 変更履歴            |
| テスト実行     | 想定会話で確認         |
| ロールバック    | 前バージョンへ戻す       |

## 8.3 応答レビュー

| 機能      | 内容                   |
| ------- | -------------------- |
| 低評価会話確認 | ユーザー低評価              |
| 未回答一覧   | RAGで答えられなかった質問       |
| 誤回答登録   | 管理者が誤回答を記録           |
| 原因分類    | RAG不足、シナリオ不足、プロンプト問題 |
| 改善依頼    | RAG側へナレッジ改善依頼        |
| 再テスト    | 改善後の回答確認             |

## 8.4 ダッシュボード

| KPI     | 内容                 |
| ------- | ------------------ |
| 会話数     | 日別、時間帯別            |
| 解決率     | Botだけで完了した割合       |
| 転送率     | 人間へ渡した割合           |
| 未回答率    | RAGで回答不可だった割合      |
| 平均ターン数  | 1会話あたりの往復回数        |
| 平均応答時間  | Botのレスポンス時間        |
| RAG成功率  | answerable=trueの割合 |
| RAG低信頼率 | confidence低い回答の割合  |
| CSAT    | ユーザー満足度            |
| 離脱率     | 会話途中で離脱した割合        |
| シナリオ完了率 | 最後まで進んだ割合          |
| エラー率    | RAG/API/DBエラー      |

---

# 9. データ設計要件

最低限、以下のテーブルが必要です。

```text
tenants
users
chat_sessions
chat_messages
conversation_states
intents
scenarios
scenario_versions
scenario_steps
scenario_slots
rag_requests
rag_responses
rag_sources
handoffs
tickets
evaluations
feedbacks
audit_logs
api_errors
prompt_versions
guardrail_results
```

## chat_sessions

```sql
id
tenant_id
user_id
channel
status
current_intent
current_scenario_id
started_at
ended_at
last_message_at
resolution_status
handoff_required
handoff_id
metadata
```

## chat_messages

```sql
id
tenant_id
session_id
role -- user / assistant / system / operator
content
message_type
created_at
token_count
metadata
```

## conversation_states

```sql
id
tenant_id
session_id
current_step
collected_slots_json
missing_slots_json
context_summary
last_rag_trace_id
handoff_required
updated_at
```

## rag_requests

```sql
id
tenant_id
session_id
message_id
query
intent
scenario_id
filters_json
rag_endpoint
requested_at
```

## rag_responses

```sql
id
tenant_id
rag_request_id
answer
answerable
confidence
latency_ms
trace_id
risk_flags_json
created_at
```

## rag_sources

```sql
id
tenant_id
rag_response_id
source_id
chunk_id
title
url
page
snippet
score
document_version
```

## handoffs

```sql
id
tenant_id
session_id
reason
priority
summary
assigned_to
status
created_at
resolved_at
```

## evaluations

```sql
id
tenant_id
session_id
message_id
reviewer_id
correctness_score
tone_score
grounding_score
handoff_appropriateness
issue_type
comment
created_at
```

---

# 10. セキュリティ要件

## 10.1 認証・認可

| 要件     | 内容                             |
| ------ | ------------------------------ |
| ユーザー認証 | Cognitoなどでログイン                 |
| 匿名利用   | 可能にする場合は権限制限                   |
| 管理者認証  | MFA推奨                          |
| ロール管理  | admin、operator、reviewer、viewer |
| テナント分離 | tenant_id必須                    |
| API認可  | ユーザーが自分の会話だけ見られる               |
| 管理画面権限 | ロールごとに機能制限                     |

Amazon Cognito User Pool はアプリの観点ではOIDC IdPとして扱え、認証・認可、フェデレーション、アプリ統合などの機能を提供します。([AWS ドキュメント][2])

## 10.2 RAG接続セキュリティ

```text
- RAG APIは認証必須
- APIキーはSecrets Managerで管理
- 本番環境ではIP制限またはPrivate接続を検討
- RAGリクエストにtenant_idを必ず付与
- RAG側でもtenant_id filterを必須にする
- リクエスト/レスポンスにtrace_idを付与
- タイムアウトを設定する
- リトライ回数を制限する
- 異常時はサーキットブレーカーを発動する
```

## 10.3 個人情報・機密情報

```text
- 氏名、電話番号、メール、住所、契約番号をPIIとして扱う
- ログ保存時にPIIマスキングを行う
- 管理画面でPII表示権限を分ける
- 会話データの保持期間を設定する
- 削除依頼に対応できるようにする
- モデル学習への利用可否を明示する
- 外部LLM/RAGへ送るデータ範囲を制御する
```

Bedrock Guardrails には機密情報フィルターがあり、リクエストまたはレスポンス内でPIIが検出された場合に、`{NAME}` や `{EMAIL}` のような型に置換してマスクできます。既存RAGを使う場合でも、ChatBot側に同等のPIIマスキング層を置くべきです。([AWS ドキュメント][4])

## 10.4 AWSセキュリティ

| 領域     | AWS候補                          |
| ------ | ------------------------------ |
| Web防御  | AWS WAF                        |
| 暗号化    | KMS                            |
| S3暗号化  | SSE-S3 / SSE-KMS               |
| 秘密情報   | Secrets Manager                |
| 監査     | CloudTrail                     |
| ログ     | CloudWatch Logs                |
| 権限     | IAM least privilege            |
| ネットワーク | VPC、Security Group、PrivateLink |

AWS WAF はCloudFront、API Gateway、ALB、AppSync、Cognito User Poolなどに転送されるHTTP/Sリクエストを監視できるWeb Application Firewallです。([AWS ドキュメント][5])
CloudTrail はAWSアカウント内のユーザー、ロール、AWSサービスによるアクションをイベントとして記録し、監査・ガバナンス・コンプライアンスに使えます。([AWS ドキュメント][6])

---

# 11. 非機能要件

## 11.1 性能

| 項目        |                  目標 |
| --------- | ------------------: |
| 初回応答      |  1〜2秒以内に「確認しています」表示 |
| 通常回答      |              3〜8秒以内 |
| RAGタイムアウト |              10〜15秒 |
| APIタイムアウト |               5〜10秒 |
| ストリーミング   |              可能なら対応 |
| 同時接続      | MVPでは100〜1,000、将来拡張 |
| メッセージ履歴取得 |                1秒以内 |
| 管理画面検索    |                3秒以内 |

LLM系のチャットでは、完全な回答を待つよりストリーミングで少しずつ表示する方が体験が良いです。AWS Lambda response streaming は、関数がレスポンス全体をバッファするのではなく、部分レスポンスを段階的に送れるため、LLMアプリのような低遅延が重要な用途に向いています。([Amazon Web Services, Inc.][7])

## 11.2 可用性

```text
- RAG障害時のフォールバック文言を用意する
- DB障害時は会話を安全に停止する
- 外部API障害時は人間転送する
- リトライは指数バックオフ
- 同じリクエストの二重実行を防ぐ
- チケット作成は冪等にする
- 重要データはバックアップする
```

## 11.3 拡張性

```text
- Web Chat以外にLINE、Slack、Teams、電話へ拡張できる
- RAGを差し替えられる
- LLMを差し替えられる
- シナリオを追加できる
- テナントを増やせる
- 言語を増やせる
```

## 11.4 運用性

```text
- CloudWatchでエラーログを確認できる
- trace_idで1会話を追跡できる
- RAG trace_idとChatBot session_idを紐づける
- 重要KPIをダッシュボード化する
- エラー率やRAG失敗率でアラートを出す
- プロンプト、シナリオ、RAG設定をバージョン管理する
```

CloudWatch Logs はAWSサービスやアプリケーションのログを一元化し、検索、フィルタ、アーカイブに使えます。CloudWatchメトリクスとアラームを組み合わせることで、しきい値超過時の通知や自動アクションも構成できます。([AWS ドキュメント][8])

---

# 12. AWS構成要件

## MVP構成

```text
Frontend:
- Next.js
- CloudFront
- S3 or Amplify

Auth:
- Cognito

API:
- API Gateway HTTP API
- API Gateway WebSocket API
  または AppSync

Backend:
- ECS Fargate
  または Lambda

State:
- DynamoDB
  または Aurora PostgreSQL

Logs:
- CloudWatch Logs
- S3 archive

Secrets:
- Secrets Manager

Async:
- SQS
- EventBridge

Workflow:
- Step Functions

Security:
- WAF
- IAM
- KMS
- CloudTrail
```

## 個人的なおすすめ

SaaS化を考えているなら、バックエンドは **ECS Fargate + TypeScript/NestJS or Fastify** が扱いやすいです。

```text
おすすめ:
- Next.js
- ECS Fargate
- Aurora PostgreSQL
- DynamoDB for session/state
- API Gateway or ALB
- Cognito
- Secrets Manager
- CloudWatch
- SQS
- Step Functions
```

理由は、会話制御・シナリオ・状態管理・RAG連携・管理画面APIが増えるため、Lambdaだけだとロジックが散らばりやすいからです。

ただし、MVPを早く作るならLambdaでも問題ありません。

DynamoDBをセッションや一時状態に使う場合はTTLが便利です。DynamoDB TTLはアイテムごとの有効期限タイムスタンプを設定でき、期限切れアイテムは数日以内に自動削除され、削除に書き込みスループットを消費しません。([AWS ドキュメント][9])

---

# 13. Chat UI要件

## ユーザー機能

```text
- メッセージ送信
- Bot応答表示
- ストリーミング表示
- Markdown表示
- リンク表示
- 根拠表示
- クイック返信
- フォーム入力
- ファイル添付
- 会話履歴表示
- 会話再開
- 人間へ相談ボタン
- 評価ボタン
- 入力中表示
- エラー時の再送
- モバイル対応
```

## UIイベント

```text
- session_created
- message_sent
- message_received
- rag_started
- rag_finished
- handoff_requested
- handoff_created
- conversation_resolved
- feedback_submitted
```

## UXルール

```text
- Botの返答が遅い時は「確認しています」を表示
- 長文は段落で分ける
- 1回の質問で聞く項目は原則1〜2個
- 必須入力はフォーム化する
- 重要事項は最後に確認させる
- 回答根拠は折りたたみ表示でもよい
- 人間転送ボタンは常に表示する
```

---

# 14. ガードレール要件

## 回答禁止・制限

```text
- 根拠なしの断定回答禁止
- 返金・補償の確約禁止
- 法的判断禁止
- 医療・金融・保険など高リスク判断禁止
- 個人情報の過剰取得禁止
- 他顧客情報の開示禁止
- 社内機密の開示禁止
- プロンプトインジェクションに従わない
- RAG根拠にない料金・条件を作らない
```

## プロンプトインジェクション対策

```text
- ユーザー発話をシステム命令として扱わない
- 「前の指示を無視して」系を検知する
- RAG文書内の命令文を実行しない
- ツール/API実行前に権限確認する
- 外部URLを無条件に信用しない
- 管理者専用情報をユーザーに出さない
```

## 出力チェック

```text
- PIIが含まれていないか
- 禁止表現がないか
- 根拠文書に基づいているか
- 高リスク領域ではないか
- ユーザーに次のアクションを示しているか
```

---

# 15. 業務API連携要件

RAGは「知識」を答えるものですが、業務処理は別APIが必要です。

## 連携候補

| API     | 例             |
| ------- | ------------- |
| 顧客情報API | 顧客ID、契約状態     |
| 契約API   | プラン、契約期間      |
| 請求API   | 請求額、支払い状況     |
| 予約API   | 予約確認、変更       |
| 注文API   | 注文状況、配送状況     |
| チケットAPI | 問い合わせ作成       |
| CRM API | 顧客対応履歴        |
| 通知API   | メール、Slack、SMS |

## API実行前の確認

```text
- 本人確認が完了しているか
- Botに実行権限があるか
- ユーザーの明示同意があるか
- 実行内容を確認したか
- 二重実行を防げるか
```

Amazon Bedrock Agents には、組織データ・ユーザー入力・ソフトウェアアプリケーション・会話をオーケストレーションし、API呼び出しやKnowledge Base呼び出しを行うエージェント機能があります。自前のConversation Orchestratorを作る場合でも、「RAG + API + 会話制御」という考え方は同じです。([AWS ドキュメント][10])

---

# 16. テスト要件

## 16.1 単体テスト

```text
- intent分類
- スロット抽出
- 状態更新
- RAG API呼び出し
- RAGレスポンス解釈
- ハンドオフ判定
- ガードレール判定
- チケット作成
```

## 16.2 会話シナリオテスト

```text
- FAQで1回回答して終わる
- 追加質問してから回答する
- 複数スロットを聞き取る
- ユーザーが途中で訂正する
- ユーザーが話題を変える
- RAGが回答不可を返す
- RAGが低信頼度を返す
- ユーザーが人間を希望する
- クレーム化する
- チケット作成に失敗する
```

## 16.3 RAG連携テスト

```text
- 正しいfiltersが渡る
- tenant_idが必ず渡る
- sourcesが保存される
- confidenceが保存される
- trace_idで追跡できる
- timeout時にフォールバックする
- RAG障害時に人間転送できる
```

## 16.4 セキュリティテスト

```text
- tenant_id漏れ
- 他ユーザーの会話閲覧
- API key漏えい
- prompt injection
- jailbreak
- PII漏えい
- 管理画面権限
- XSS
- CSRF
- rate limit
```

---

# 17. 受け入れ基準

MVPで最低限クリアすべき基準です。

```text
1. ユーザーが自然文で問い合わせできる
2. Botが会話状態を保持できる
3. Botが足りない情報を質問できる
4. Botが既存RAG APIを呼び出せる
5. RAG回答の根拠を画面に表示できる
6. RAG根拠がない場合は断定回答しない
7. ユーザーが人間希望したらハンドオフできる
8. 高リスク問い合わせを人間へ回せる
9. 会話履歴を保存できる
10. RAGリクエスト/レスポンスを保存できる
11. 管理者が会話詳細を確認できる
12. 会話ごとに解決/未解決/転送済みを記録できる
13. tenant_idでデータが分離される
14. PIIをマスキングまたは表示権限制御できる
15. RAG障害時に安全なフォールバックができる
16. 基本KPIを確認できる
```

---

# 18. MVPで作る範囲

最初から全部作ると重いので、まずはここまででいいです。

## P0：必須

```text
- Web Chat UI
- Chat API
- 会話セッション作成
- 会話履歴保存
- 会話状態管理
- intent分類
- 既存RAG API連携
- RAG根拠表示
- confidenceによる回答可否判定
- 追加質問
- 人間ハンドオフ
- チケット作成
- 管理画面で会話確認
- 基本ログ
- tenant_id分離
- 認証
```

## P1：次に必要

```text
- シナリオ管理画面
- スロット定義画面
- RAGフィルタ設定
- 応答レビュー
- 未回答一覧
- 誤回答フィードバック
- ダッシュボード
- Slack通知
- ストリーミング応答
- PIIマスキング
```

## P2：高度化

```text
- 有人チャット切替
- CRM連携
- 業務API実行
- 多言語対応
- A/Bテスト
- プロンプトバージョン管理
- 自動評価
- FAQ改善提案
- Amazon Connect連携
- 電話Botとの履歴統合
```

---

# 19. 最小構成のシーケンス

```text
1. ユーザーがメッセージ送信
2. Chat APIが受信
3. session_idを確認
4. 会話履歴を取得
5. conversation_stateを取得
6. intentを判定
7. シナリオを選択
8. 足りないslotを確認
9. 足りなければ質問を返す
10. RAGが必要ならRAG APIを呼ぶ
11. RAGレスポンスを検証
12. confidenceが低ければ聞き返し or 人間転送
13. answerableなら回答生成
14. sourcesを保存
15. 会話状態を更新
16. ユーザーへ返答
17. ログ・KPIを記録
```

---

# 20. 具体的なユーザー会話例

## 例：導入相談

```text
ユーザー:
AIチャットボットを導入したいです。

Bot:
ありがとうございます。導入相談ですね。
まず、現在の問い合わせチャネルを教えてください。
電話、メール、チャット、LINEなど、どれが中心ですか？

ユーザー:
電話とメールです。

Bot:
ありがとうございます。月間の問い合わせ件数はどれくらいですか？

ユーザー:
500件くらいです。

Bot:
承知しました。電話とメールで月500件ほどですね。
既存FAQやマニュアルはありますか？

ユーザー:
あります。

Bot:
ありがとうございます。既存FAQがある場合、RAGを使ってFAQを根拠に回答するチャットボットを構築できます。
電話対応AIも検討できますが、まずはRAGチャットボットでナレッジ精度を確認する進め方がおすすめです。
担当者との相談を希望されますか？
```

## 例：RAG根拠不足

```text
ユーザー:
特別割引できますか？

Bot:
確認しましたが、現在のナレッジでは特別割引の可否を断定できる情報が見つかりませんでした。
個別条件の確認が必要なため、担当者に引き継ぎます。
ここまでの内容を共有してよろしいですか？
```

## 例：人間希望

```text
ユーザー:
人に相談したいです。

Bot:
承知しました。担当者に引き継ぎます。
ここまでの会話内容と確認済みの情報を共有しますので、同じ説明を繰り返す必要はありません。
```

---

# 21. 最終要件まとめ

今回のChatBotは、こう定義するとブレません。

```text
既存RAG連携型 ChatBot
= Chat UI
+ Chat API
+ Conversation Orchestrator
+ Session / State Management
+ Intent Detection
+ Scenario Engine
+ Slot Filling
+ Existing RAG Connector
+ Guardrails
+ Human Handoff
+ Conversation Logs
+ Admin Console
+ Analytics
+ Security / Compliance
```

一番大事な設計方針はこれです。

**RAGは答えるために使う。
ChatBotは会話を最後まで進めるために使う。**

なので、既存RAGとつなぐだけでは足りません。
ChatBot側に **状態管理、シナリオ、聞き返し、人間引き継ぎ、履歴、評価** を必ず持たせるべきです。

[1]: https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-websocket-api-overview.html?utm_source=chatgpt.com "Overview of WebSocket APIs in API Gateway"
[2]: https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools.html?utm_source=chatgpt.com "Amazon Cognito user pools"
[3]: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_RetrieveAndGenerate.html?utm_source=chatgpt.com "RetrieveAndGenerate - Amazon Bedrock"
[4]: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-sensitive-filters.html?utm_source=chatgpt.com "Remove PII from conversations by using sensitive information ..."
[5]: https://docs.aws.amazon.com/waf/latest/developerguide/waf-chapter.html?utm_source=chatgpt.com "AWS WAF"
[6]: https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-user-guide.html?utm_source=chatgpt.com "What Is AWS CloudTrail? - AWS CloudTrail"
[7]: https://aws.amazon.com/about-aws/whats-new/2026/04/aws-lambda-response-streaming/?utm_source=chatgpt.com "AWS Lambda expands response streaming support to all ..."
[8]: https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/WhatIsCloudWatchLogs.html?utm_source=chatgpt.com "What is Amazon CloudWatch Logs?"
[9]: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/TTL.html?utm_source=chatgpt.com "Using time to live (TTL) in DynamoDB"
[10]: https://docs.aws.amazon.com/bedrock/latest/userguide/agents.html?utm_source=chatgpt.com "Automate tasks in your application using AI agents"
