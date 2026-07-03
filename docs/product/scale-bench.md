# 大規模検索ベンチマーク(Wave 1a)— 3,000〜10,000文書での実測

これまで検索品質・レイテンシは 21文書のデモKB(`scripts/demo/`)と 25問の golden corpus で
しか測っていなかった。パイロット初日に露呈する「スケール未実証」リスクを潰すため、
合成日本語製造業コーパス(3,000 / 10,000 文書)で検索品質(recall@k / MRR / nDCG@10)と
負荷特性(p50/p95 × 同時実行 1/4/8)を実測した。**この数値が Wave 1b(RRF融合)/
1c(同義語展開)の優先度を決める**(測ってから直す)。

- ハーネス: `scripts/bench/generate_corpus.py`(決定的シードコーパス生成)+
  `scripts/bench/run_bench.py`(local / stg 2モード)。CI外・手動実行。
- 実行日: 2026-07-03、develop 8718972 上(branch `feat/scale-bench`)。
- 再現: `python3 scripts/bench/run_bench.py --mode local --n-docs 3000`(seed 固定 20260703)。

## 測定条件と正直なスコープ宣言

**local モード = 検索パイプラインの機械特性の測定**。ProductionSystem(実 Postgres+RLS、
`raku_bench` 専用DB)+ デターミニスティック hashing 埋め込み(`hashing-bow-v2`、CJK bigram)。
デプロイ構成と同一の3レグハイブリッド(vector / 識別子メタデータ / lexical)+
ScoreOrderReranker。したがって:

- **識別子スライス・lexical 挙動・レイテンシのスケーリングは本番相当の signal**
  (識別子レグ・lexical レグは埋め込みプロバイダ非依存。SQL/データ転送/Python後段も同一)。
- **paraphrase スライスは「語彙が重なる自然文の順位付け」の測定であり、意味的言い換え耐性
  ではない**。hashing 埋め込みは bag-of-tokens なので、真の意味検索(OpenAI 埋め込み)での
  paraphrase 品質は stg モードでしか測れない。
- **synonym スライスは有効な signal**。クエリ側同義語は文書側表層形と **CJK bigram 重複ゼロ**
  になるよう構築(生成時に assert)しており、「lexical レグ+bigram 埋め込みが同義語を
  取れない」ことをそのまま測る。実埋め込みなら vector レグが部分的に救うはずだが、
  それも stg 実測待ち — 少なくとも**識別子レグ・lexical レグは同義語に対して無力**という
  結論はプロバイダ非依存で成立する。

コーパス: 手順書30% / トラブル事例30% / 点検基準20% / 規程20%。全文書が共有語彙
(設備ファミリ10種 × 部品24種 × 事象16種 + 定型文)を使い、一意トークン
(EQ-XXXX-nnn / E-nnn / PN-nnnnn / SOP・TR・INS・REG 文書番号)を持つ。
評価 200問: identifier 60 / paraphrase 50 / synonym 30 / multi_doc 30 / unanswerable 30(15%)。
paraphrase/synonym の gold は (ファミリ, 部品, 事象) トリプルがコーパス内で一意な文書のみ
(gold の定義が曖昧にならないように)。

## 結果1 — 検索品質(文書単位 rank metrics、concurrency=1 の 200問)

### N=3,000(3,000 chunks)

| スライス | n | recall@5 | recall@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **overall(回答可能170問)** | 170 | **0.635** | 0.747 | 0.530 | 0.581 |
| identifier(識別子指名) | 60 | **0.567** | 0.650 | 0.400 | 0.460 |
| paraphrase(自然文・識別子なし) | 50 | 0.640 | 0.800 | 0.586 | 0.635 |
| synonym(同義語置換) | 30 | **0.400** | 0.600 | 0.226 | 0.313 |
| multi_doc(設備単位2-3文書) | 30 | 1.000 | 1.000 | 1.000 | 1.000 |

### N=10,000(10,000 chunks)

| スライス | n | recall@5 | recall@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **overall(回答可能170問)** | 170 | **0.482** | 0.659 | 0.448 | 0.496 |
| identifier | 60 | **0.417** | 0.617 | 0.372 | 0.428 |
| paraphrase | 50 | 0.500 | 0.740 | 0.449 | 0.514 |
| synonym | 30 | **0.067** | 0.267 | 0.048 | 0.097 |
| multi_doc | 30 | 1.000 | 1.000 | 1.000 | 1.000 |

参考: 同一ハーネスの N=300 パイロットでは identifier recall@5=1.0 / paraphrase 1.0 /
synonym 0.75。ヘッドライン: **identifier は 1.0@300 → 0.57@3,000 → 0.42@10,000 と単調劣化、
synonym は 10,000 文書でほぼ全滅(recall@5 0.067 / MRR 0.048)**。multi_doc だけがスケール不変。

### 回答不能(unanswerable)スライス — スコア分離

| N docs | 回答可能 mean top-1 | 回答不能 mean top-1 | 回答不能 max top-1 |
|---|---|---|---|
| 3,000 | 1.071 | 0.791 | **0.951** |
| 10,000 | 1.081 | 0.859 | **0.946** |

平均では分離するが、**max 0.95 は識別子メタデータ一致スコア帯(1.25)未満というだけで、
lexical 一致帯(0.70-1.20)と完全に重なる** — スコア閾値だけでは「存在しない設備の質問」を
検索段で弾けない(現状は回答段の salient-coverage ゲート頼み。#80 の設計判断どおり)。

## 結果2 — レイテンシ × 同時実行(search のみ、closed-loop、クライアント毎に専用PG接続)

| N docs | conc | p50 (ms) | p95 (ms) | mean (ms) | QPS |
|---|---|---|---|---|---|
| 3,000 | 1 | 561 | 658 | 566 | 1.77 |
| 3,000 | 4 | 1,870 | 2,291 | 1,856 | 2.13 |
| 3,000 | 8 | 3,763 | 4,644 | 3,752 | 2.11 |
| 10,000 | 1 | 1,933 | 2,197 | 1,944 | 0.51 |
| 10,000 | 4 | 6,181 | 7,488 | 6,069 | 0.64 |
| 10,000 | 8 | **12,607** | **15,564** | 12,478 | 0.63 |

**スループットは concurrency に対して飽和する**(3,000文書で ≈2.1 QPS、10,000文書で
≈0.63 QPS が上限)。クライアントを増やしても QPS は伸びず p50/p95 が並列数にほぼ比例して
悪化するだけ — ボトルネックはDBではなく Python 側の全件後処理(GIL 直列化)。
p50 は文書数にほぼ線形(561ms@3k → 1,933ms@10k、3.33倍の文書で3.45倍)。
`Settings.target_p95_latency_ms=2000` は **N=3,000 は4並列で、N=10,000 は1並列(2,197ms)で
既に超過**。

### 根本原因(実装確認済み、file:line)

1. **vector レグが LIMIT なし全件ソート+全件転送** — `persistence/postgres.py:522-553` は
   「SQL LIMIT は ACL 後段フィルタ前に可視チャンクを落とすから」という意図で全行を
   `ORDER BY embedding <=> q` で取得し Python で ACL フィルタする。EXPLAIN で確認:
   **Seq Scan + Sort。0001 マイグレーションの HNSW インデックス
   (`idx_chunks_embedding_hnsw`)は LIMIT の無いこのクエリ形状では使われない**。
   1クエリごとに全チャンク(text 込み)をネットワーク転送する。
2. **lexical レグも全件転送+Python スコアリング** — `persistence/postgres.py:594-637` は
   tenant/live 絞りだけ SQL で行い、全チャンク text + doc metadata を取得して
   `lexical_match_score`(`core/hybrid_retrieval.py:104`)を全件に適用する
   (0008 の GIN tsvector インデックスも「CJK bigram を落とすから」未使用)。
3. つまり **search 1回 = テナント全チャンクの O(N) 転送 × 2 + O(N) Python スコアリング**。
   レイテンシが文書数にほぼ線形(p50 561ms@3k → 1,933ms@10k)なのはこの構造の直接の帰結。

インジェスト(参考): 3,000文書 13.1秒(**229 docs/s**)、10,000文書 41.4秒(**242 docs/s**、
=242 chunks/s、本コーパスは1文書≈1チャンク)。in-process の逐次 ingest_text 経路
(HTTP/ワーカー経路のオーバーヘッドは含まない)。インジェストはスケール非依存で安定 —
問題は検索側のみ。

## 結果3 — スライス別劣化の内訳(なぜ落ちるか)

### identifier(1.0@300 → 0.57@3,000 → 0.42@10,000): フラットスコアの同点問題

識別子メタデータ一致(`METADATA_EXACT_MATCH_SCORE=1.25`、`core/hybrid_retrieval.py:36`)は
**「クエリ内のどれか1つの識別子に一致」で全部同点 1.25** になる。
クエリ「EQ-PRESS-042 のアラーム E-217 は?」に対して:

- gold(両方一致)も、同じ設備の別文書(EQ のみ一致)も、他設備の同一アラーム番号の
  手順書(E-217 のみ一致)も、全部 1.25。
- query-plan boost(`services/retrieval.py:397`、+0.02)も同条件で全員に付く。
- 同点グループ内の順序は **chunk position / chunk_id 順 = 実質恣意**
  (`persistence/postgres.py:582`)。設備あたり文書数×アラーム番号衝突がスケールと共に
  増える(N=3,000 で平均 ~6件の同点)ため、gold が top5 から押し出される。

**両方の識別子に一致する文書を1つ一致より上に置く仕組みが存在しない** — これはまさに
rank fusion(1b)が解く形。

### synonym(0.40@3,000 → 0.067@10,000): 語彙ミスに対して無力(1c の直接根拠)

クエリ側「オーバーヒート」は文書側「温度上昇」と bigram 重複ゼロ。lexical レグは
(ファミリ+部品)の 2/3 カバレッジ文書群を同点で返し、hashing vector レグも同じ token を
見るので救えない。gold は (部品+ファミリ) を共有するディストラクタ文書と区別不能になり、
同点集団が文書数と共に膨らむため **recall@5 は 0.40@3,000 → 0.067@10,000 とほぼ全滅**する。
**tenant_lexicon を検索時クエリ展開に接続(1c)すれば lexical レグの被覆が直接回復する形**。

### paraphrase(0.64@3,000 → 0.50@10,000): 「語順・文型の違い」ではなく共有語彙の混雑で落ちる

クエリは gold の内容語(ファミリ/部品/事象)をそのまま含むため、劣化要因は synonym と同じ
「部分カバレッジ同点文書の押し出し」。真の意味的言い換え耐性は stg(実埋め込み)でしか
測れない点に注意(スコープ宣言参照)。

### multi_doc(1.00): 識別子メタデータレグの構造的な得意分野

gold の定義が「その設備IDを持つ全文書」であり、識別子レグがまさにそれを全部返すため
ほぼトートロジカルに満点。**「設備IDを知っている質問」は現行実装でもスケールに耐える**
という(限定的だが実用上重要な)確認として読む。

## 1b / 1c への示唆

測定結果は **1b(RRF融合)を先に、1c(同義語展開)をすぐ続けて** を支持する:

1. **件数インパクト最大の劣化は identifier スライス(60問、recall@5 1.0→0.42@10k)で、
   原因はスコア設計(フラット1.25の同点)**。RRF は「複数レグで上位に来る文書」を機械的に
   持ち上げるので、両識別子一致(メタデータレグ+lexical レグの両方で上位)の gold が
   同点グループから分離される — まさにこの形の欠陥に効く。paraphrase の部分カバレッジ同点
   (50問、0.64→0.50)にも同様に効く。union-max(`services/retrieval.py:61`)の置換だけで
   identifier/paraphrase 両スライス(=回答可能170問中110問)の改善が見込める。
   実装時は `_apply_query_plan_boosts` との相互作用に注意(プラン参照)。
2. **synonym スライスの崩壊(0.067@10k)は fusion では直らない** — どのレグにも gold を
   同義語で引く信号が無いから。ここは 1c(tenant_lexicon の `retrieval.synonyms` 名前空間+
   lexical レグのみ展開)が唯一の lever。相対劣化率は全スライス中最悪(−93%)だが件数は
   30問なので、修正順序は 1b → 1c。ただし 1b 単独では synonym の底(≈0)は動かない —
   **1c まで完了して初めて overall が回復する**点は明記しておく。
3. **レイテンシは 1b/1c と独立の Ops 課題として最優先級** — 品質以前に、現行の
   O(N) 全件転送検索は **10,000文書では1並列で既に p95 2.2s(SLA 2s 超過)、8並列で
   p95 15.6s / 0.63 QPS** に達し、パイロット規模で成立しない。修正方向は
   (a) vector レグに LIMIT 付き HNSW 走査(ACL 後段フィルタ分の over-fetch 係数付き)、
   (b) lexical レグの SQL 候補絞り(tsvector は CJK bigram を落とすので、bigram 配列
   カラム等の設計が必要)。これは Wave 1 の別チケットに切るべき
   (本ベンチはスコープ外=測定のみ)。

## stg モード(実埋め込み・実スタック)runbook — 未実行

stg 実測は **課金が発生**(文書3,000件 × チャンク毎の OpenAI 埋め込み + クエリ毎の埋め込み)
するため本 Wave では未実行。実行する場合:

1. **専用テナントに隔離**: ハーネスは tenant/collection とも `bench` 固定
   (`run_bench.py`)。デモテナント(`demo`)を汚さない。ACL grant も `bench-user` のみ。
2. **in-VPC 実行**: answer-service は内部ALBのみ。`scripts/aws/migrate-seed.sh` と同じ
   ops RunTask パターン(`infra/ops/Dockerfile` 像は `scripts/` 同梱)でタスク内から:
   ```bash
   ANSWER_SERVICE_URL=http://<AnswerServiceInternalLoadBalancerDnsName> \
   RAKU_INTERNAL_AUTH_SECRET=<Secrets Manager: raku-rag/internal-auth> \
   python3 scripts/bench/run_bench.py --mode stg --n-docs 3000 --yes-costs-money \
     --out /tmp/bench_stg_3000.json
   ```
3. **明示フラグ必須**: `--yes-costs-money` が無いと即座に拒否する。
4. 事後クリーンアップ: `bench` テナントの documents/chunks を tombstone/purge
   (`DELETE /internal/documents/{id}` ループ、または DB 上で tenant_id='bench' を確認の上
   管理オペとして削除)。
5. 読み方: stg では paraphrase/synonym スライスに vector レグ(実埋め込み)の寄与が乗る。
   local との差分が「実埋め込みが救っている分」= 1c の残りの必要性の実測になる。

## 再現手順(local)

```bash
# 専用DB raku_bench を自動作成(maintenance DB 経由)+ マイグレーション適用込み。
# raku_parity / raku_tier_b_gate / raku_demo はハーネスが拒否する。
python3 scripts/bench/run_bench.py --mode local --n-docs 3000  --out /tmp/bench3000.json
python3 scripts/bench/run_bench.py --mode local --n-docs 10000 --out /tmp/bench10000.json
# 再インジェストを飛ばして検索だけ再測定:
python3 scripts/bench/run_bench.py --mode local --n-docs 10000 --skip-ingest
```

スモークテスト: `tests/unit/test_bench_generator.py`(生成の決定性 / eval set の妥当性 /
synonym ペアの bigram 非重複 / rank metrics の正しさ)。
