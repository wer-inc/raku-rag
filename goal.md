次は **「MVP完成スプリント」** に入るのがいいです。
今の状態はもう「機能を広げる段階」ではなく、**最初の実演フローを企業ユーザーが触れる品質まで閉じ切る段階**です。

結論はこれです。

```text
次にやること:
MVP実演フローを100%通すための UAT / UX / hardening に集中する。

まだやらないこと:
新業界追加、課金、API/Webhook、外部連携大量追加、Dagster、Full SaaS化。
```

---

# 今やるべき優先順位

## P0. MVP実演フローを固定する

まず、MVPで見せる流れを1本に固定してください。

おすすめはこれです。

```text
1. 管理者がPDF / Excelをアップロード
2. 取込が完了する
3. 文書承認キューで approved にする
4. 現場ユーザーが質問する
5. AIが根拠付き回答を返す
6. 引用元を確認する
7. 危険作業質問では回答を保留する
8. 点検チェックリスト draft を作る
9. reviewer が承認 / 却下する
10. 監査ログとダッシュボードに反映される
```

この10ステップが通れば、**かなり売れるデモ**になります。

---

# P1. まず足りない可能性が高い画面を閉じる

現状を見る限り、機能はかなりできています。
次に優先すべき画面はこの順です。

## 1. 引用ビューア

citation 表示はできているとのことですが、企業ユーザーは **引用元を実際に開いて確認できるか** を見ます。

完結条件:

```text
- PDFの該当ページを開ける
- Excelの該当シート / セル範囲を開ける
- Wordの該当見出し / 段落を開ける
- approval_status / effective_date / obsolete warning が見える
- 「この引用は正しい / 間違い」をフィードバックできる
```

citation のテキスト表示だけだと、まだ弱いです。
ここは最優先で磨いてください。

---

## 2. 文書承認キュー

文書承認の状態遷移はできているようなので、次は **画面として業務に使えるか** です。

完結条件:

```text
- 取り込まれた文書が pending_review になる
- 管理者が metadata / parse結果 / 公開範囲を確認できる
- approved / rejected / obsolete にできる
- approved だけが正式根拠になる
- 変更が audit log に残る
```

AIドラフトのレビューと、取り込み文書の承認は分けてください。
ここが混ざると、企業ユーザーは混乱します。

---

## 3. ロール別ナビ

今のUIが全部入りなら、実運用では重いです。

最低限この分け方にしてください。

```text
一般ユーザー:
- 質問する
- 回答履歴
- 自分のドラフト

承認者:
- レビューキュー
- 文書承認キュー
- 承認履歴

ナレッジ管理者:
- ソース
- ドキュメント
- 取込ラン
- ナレッジ改善
- 検索診断

管理者 / 情シス:
- ユーザー
- ロール
- 監査ログ
- プロバイダ
- ログ・プライバシー
```

一般ユーザーに Retrieval、Provider、API、課金、監査ログを見せる必要はありません。

---

## 4. ナレッジ改善キュー

フィードバックや低評価があるなら、それを改善作業に繋げる画面が必要です。

完結条件:

```text
- 低評価回答が一覧化される
- 未回答質問が一覧化される
- 根拠不足質問が一覧化される
- 古い文書しかヒットしなかった質問が分かる
- 担当者を割り当てられる
- 文書追加 / FAQ化 / metadata修正 / 再評価に進める
```

これは「運用で精度を上げられるRAG」としてかなり重要です。

---

## 5. PoC効果レポート

運用ダッシュボードやKPIがあるなら、次は **営業・PoC報告で使える1画面** にしてください。

表示すべきもの:

```text
- 質問数
- 根拠付き回答率
- 根拠不足率
- 低評価率
- 未回答質問数
- よく参照された文書
- high-risk query 数
- gate block 数
- draft 生成数
- review 完了数
```

顧客に見せる時は、細かい技術KPIより、

```text
現場の自己解決が増えた
危険な断定回答を止めた
足りない文書が見つかった
```

が伝わる方が強いです。

---

# P2. 次にやるべきテスト

今からやるべきは、単体テストではなく **業務フローUAT** です。

## 製造業MVP UAT

最低限この5本でよいです。

```text
MFG-01:
E-142の確認手順を根拠付きで回答できる

MFG-02:
安全カバーを外したまま動かしてよいか？に断定回答しない

MFG-03:
寸法不良の過去事例を、暫定対策 / 恒久対策に分けて一覧化できる

MFG-04:
月次点検チェックリスト draft を作れる

MFG-05:
obsolete 文書を正式根拠にしない
```

## 横断UAT

```text
X-01:
他テナント文書が検索・回答・引用に出ない

X-02:
ACL外文書がrerank/LLM contextに入らない

X-03:
tombstone文書が再検索されない

X-04:
no-train default が有効

X-05:
raw retrieved context が trace に保存されない
```

この10本が通れば、MVPとしてかなり強いです。

---

# P3. 次にやらない方がいいもの

今はまだやらない方がいいです。

```text
- 不動産 / 投資信託のフル実装
- 全外部連携
- API / Webhook公開画面
- 利用・課金画面
- 高度なRetrieval設定UI
- Dagster
- OpenSearch
- Bedrock本番Providerの細かい最適化
- SSO本番連携
```

理由は、MVP実演フローがまだ100%閉じていないからです。

まずは、

```text
アップロード
承認
質問
引用確認
安全ゲート
ドラフト
レビュー
監査
KPI
```

を1本で通すべきです。

---

# 次に Spec Kit に渡す prompt

以下をそのまま渡してください。

```text
MVP Completion Sprint の tasks を作成・整理してください。

目的:
現在のMVP縦切りは約7割完了している。
次は機能拡張ではなく、最初の企業向け実演フローを100%通すために、UI/UX、UAT、hardening、acceptance を完結させる。

重要:
- 新しい業界機能は追加しないでください。
- 010 / 003 / 006 の本格実装には進まないでください。
- 課金、API/Webhook、外部連携大量追加、Dagster、OpenSearch は対象外です。
- 既存のMVP機能を企業ユーザーが使える品質にすることに集中してください。
- 実装対象は製造業MVP + 001基盤の横断hard gatesです。

MVP実演フロー:
1. 管理者がPDF / Excelをアップロードする
2. 取込が完了する
3. 文書承認キューで approved にする
4. 現場ユーザーが質問する
5. AIが根拠付き回答を返す
6. 引用元を確認する
7. 危険作業質問では回答を保留する
8. 点検チェックリスト draft を作る
9. reviewer が承認 / 却下する
10. 監査ログとダッシュボードに反映される

優先実装項目:

P0-1 Citation Viewer
- PDFページを表示
- Excel sheet / cell_range を表示
- Word heading / paragraph を表示
- approval_status / effective_date / obsolete warning を表示
- citation feedback を付けられる

P0-2 Document Approval Queue
- 取り込み済み文書を pending_review として表示
- metadata / parse結果 / 公開範囲 / approval_status を確認できる
- approved / rejected / obsolete に変更できる
- approved 文書だけ正式根拠にできる
- 変更を audit log に残す

P0-3 Role-based Navigation
- 一般ユーザーには質問・履歴・自分のdraftだけ表示
- 承認者にはレビューキューと文書承認キューを表示
- ナレッジ管理者にはソース、ドキュメント、取込、改善、検索診断を表示
- 情シス/管理者にはユーザー、ロール、監査、プロバイダ、ログ設定を表示
- 権限のない画面はUIにもAPIにも出さない

P0-4 Knowledge Improvement Queue
- 未回答質問
- 低評価回答
- 根拠不足回答
- obsolete文書のみヒットした質問
- 頻出質問
- 担当者割当
- 文書追加 / FAQ化 / metadata修正 / 再評価への導線

P0-5 PoC Effect Report
- 質問数
- 根拠付き回答率
- 根拠不足率
- 低評価率
- 未回答質問数
- よく参照された文書
- high-risk query数
- gate block数
- draft生成数
- review完了数

P0-6 UAT Fixtures and Scenario Scripts
- 製造業サンプル文書
- PDFマニュアル
- Excel点検表
- trouble report
- obsolete文書
- high-risk質問
- ACL外文書
- UAT実行手順

P0-7 MVP Hard Gate Tests
- tenant leakage = 0
- ACL leakage = 0
- denied document not sent to rerank
- denied document not sent to LLM context
- approved document citation required for high-risk
- obsolete/draft not used as formal evidence
- DraftArtifact not auto-approved
- no-train default active
- raw retrieved context not stored by default
- audit event recorded

Acceptance Criteria:
- MVP実演フロー10ステップが通る
- Citation Viewerで根拠を実際に確認できる
- approved / draft / obsolete の扱いがUIとAPIで一致している
- high-risk質問で断定回答しない
- DraftArtifactが自動approvedにならない
- 監査ログに重要イベントが残る
- PoC Effect Reportに主要KPIが出る
- 一般ユーザーに管理者画面が出ない
- UATシナリオが再現可能である

Out of scope:
- 新業界の本格実装
- 課金
- API/Webhook画面
- 全外部連携
- Dagster
- OpenSearch
- real Bedrock最適化
- SSO本番連携
- 高度なRetrieval設定UI

出力:
1. MVP Completion Sprint tasks
2. 画面別タスク
3. API別タスク
4. UATシナリオ
5. Hard gate tests
6. Acceptance checklist
7. 実装前blocker
8. 実装順序
```

---

# 実装順序はこれ

MVP Completion Sprint の実装順序はこうです。

```text
1. Citation Viewer
2. Document Approval Queue
3. Role-based Navigation
4. UAT Fixtures
5. MVP Hard Gate Tests
6. Knowledge Improvement Queue
7. PoC Effect Report
8. 最終UAT
```

順番としては、**Citation Viewer が最初**です。
根拠付き回答がすでにあるなら、次にユーザーが欲しいのは「根拠を本当に確認できること」です。

---

# 今の判断

今の完成度なら、次にやるべきはこれです。

```text
MVP Completion Sprint
```

もう少し具体的に言うと、

```text
機能を増やすのではなく、
今ある縦切りを企業のPoCで見せられる状態にする
```

です。

ここを通せば、Full SaaSではなくても **PoCで売れるプロダクト** になります。
