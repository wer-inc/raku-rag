# 0050 — チャットボット回答品質のGolden Scenario不足(系統 = chatbot / quality-eval)

> Priority: **P1/High** / Status: Resolved / Labels: `chatbot`, `quality`, `eval`, `stg`

## 背景(なぜ今)

stg の `/chatbot` は参照範囲設定後に動作するようになったが、実際の回答内容が薄く、UI smoke だけ
では「業務で使える回答か」「安全に答えないべき時に答えていないか」を判定できないことが分かった。

## どんな課題か

- Playwright はログイン、参照範囲、送信、handoff 表示の確認には使えるが、回答品質の回帰検知には弱い。
- Golden Scenario がないため、薄い回答、引用不足、根拠不足 refusal、draft/obsolete 根拠の扱いを
  継続的に比較できない。
- 現在の stg は hashing embedding / extractive answer 構成で、安全確認にはよいが、売れる品質の
  回答厚みを測るには評価データと本番相当 profile の分離が必要。

## どこで起きたか

- 画面: `/chatbot`
- API: `/v1/chat/sessions`, `/v1/chat/source-exposure-policies`
- コード: `scripts/demo/chatbot_golden_scenarios.py`, `scripts/demo/chatbot_golden_scenarios.json`
- 環境: AWS stg ALB
- run id / ingestion id / correlation id: stg deploy `28429811661`, head `67da27f`
- 再現条件: 承認済み参照範囲で質問送信後、回答が handoff または短い抽出文に留まる
- 2026-06-30 stg scorecard:
  - `tenant_admin` のみ: 17件中5件PASS。回答系12件は全て `insufficient_evidence`。
  - `tenant_admin + sales_demo`: 17件中7件PASS。拒否系5件は全PASS。回答系は検索不可2件、
    検索できるが薄い/事実不足8件。
- 2026-06-30 root cause:
  - CJK bigram tokenizer 導入後も `HashingEmbeddingProvider.model_version` が `hashing-bow-v1`
    のままで、stg 再seedが既存文書を再埋め込みせず、日本語検索改善が反映されなかった可能性が高い。
  - Postgres lexical leg が `to_tsvector` で候補を先に絞っており、in-memory と同じ CJK-aware scorer
    に到達する前に日本語候補を落とし得た。
  - `extractive-mvp` が上位数文だけを返すため、手順・原因対策・しきい値の質問で近接する重要文を
    落としていた。
  - 旧URL同期/デバッグ文書が同じ `manuals` collection に残り、期待文書より上位に出ていた。
  - 削除後の同一checksum再seedが既存成功 ingestion run に当たり、通常文書14件が tombstone から
    復活しない状態になっていた。
- 2026-06-30 final stg scorecard:
  - deploy run: `28436589691`, head `8874795`
  - `tenant_admin + sales_demo`: 17件中17件PASS。回答系12件は全て期待citation/required termsを満たす。
  - `/v1/manufacturing/documents?collection_id=manuals`: 18 live documents。

## 影響

- 営業デモで「動くが価値が伝わらない」状態になりやすい。
- 本番クライアント向けに回答品質の説明責任を果たしにくい。
- 安全 refusal と品質不足の区別が曖昧になり、誤った改善(安全ルール緩和など)につながる恐れがある。

## どう解決すべきか

1. チャットボット用 Golden Scenario JSON を整備し、grounded lookup / high-risk approved /
   troubleshooting / safety refusal / security refusal を分ける。
2. API runner で `answerable`, `ai_action`, citation, required terms, answer length, forbidden terms
   を判定する。
3. Playwright は UI smoke、Golden Scenario は回答品質、既存 eval runner は検索/回答基盤メトリクスに
   役割分担する。
4. stg-smoke と quality/demo profile を分け、回答厚みの確認は本番相当 embedding/LLM profile で行う。
5. deterministic/extractive stg でも、tokenizer 変更時は embedding model version を必ず上げ、
   手順・原因対策系の抽出は最良文書の関連項目をまとめて返す。

## QA checklist

- [x] 再現テストがある。
- [x] 正常系が確認できる。
- [x] 失敗時の表示/応答が確認できる。
- [x] tenant/ACL 境界を越えない。
- [x] security/safety gate を弱めていない。
- [x] Playwright または API smoke で確認できる。
- [x] AWS stg/live smoke が必要な場合は correlation id/run id を保存する。

## 受け入れ条件(DoD)

- `scripts/demo/chatbot_golden_scorecard.sh` で local/stg のチャット品質を同じシナリオで測れる。
- 薄い回答、引用不足、期待事実不足、安全 refusal 失敗が個別に失敗理由として出る。
- デモ用の承認済み文書と expected terms/citations を更新する運用がドキュメント化されている。
- 既存の安全ルール、ACL、監査要件を弱めていない。
- stg deterministic profile で 17/17 PASS を確認済み。

## スコープ外

- draft/obsolete/high-risk の安全ルール緩和。
- Playwright だけで回答品質を判定すること。
- 本番相当LLM/profileへの切替や有料provider評価の自動実行。

## 参照

- `docs/production-readiness/chatbot-golden-scenarios.md`
- `scripts/demo/chatbot_golden_scenarios.json`
- `scripts/demo/chatbot_golden_scenarios.py`
- `docs/production-readiness/eval-plan.md`
