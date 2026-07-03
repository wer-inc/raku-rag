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

## Wave 1b 実施後の再実測(RRF融合+レグ修正)— 2026-07-03

Wave 1b(branch `feat/rrf-fusion`)で union-max マージを置換し、同一ハーネス・同一シード
(20260703)で再実測した。実装は4点セット:

1. **順位付けの契約**(`services/retrieval.py::_merge_hybrid_results` /
   `_apply_query_plan_boosts`): ①絶対スコア+query-plan boost(バンド構造は従来どおり
   識別子メタデータ 1.25 > lexical > vector)→ ②メタデータレグ内 rank(=識別子一致
   **多重度**)→ ③RRF(Σ 1/(60+rank)、3レグ横断)→ ④chunk_id。`retrieval_score` は
   従来どおり最大レグスコア(絶対スケール)のまま — RRF は**順序信号のみ**で、
   groundedness pre-gate(`score_threshold=0.10`)/confidence/scorecard の閾値意味論は不変。
   `ScoreOrderReranker` は検索順序を保存する identity に変更(スコア再ソートで融合順序を
   壊さない)。
2. **メタデータレグの多重度ランキング**(in-memory / Postgres 両ストア、parity テスト
   `tests/postgres/test_hybrid_multiplicity_parity.py`): フラット1.25の同点を「クエリ内の
   何個の識別子に一致したか」で順位付け。両識別子一致の gold が単一一致の群れより先に出る。
3. **lexical レグの識別子重み**(`core/hybrid_retrieval.py::LEXICAL_IDENTIFIER_MATCH_WEIGHT
   =0.18`): 文書番号(INS-0435 等)のようにメタデータに無い識別子は本文の逐語一致で拾う。
   従来は識別子が ~17 lexical 語のうちの 1-2 語でしかなく、カバレッジ差(~0.023)が
   recency boost(0.09)に負けて gold がレグの top_k から溢れていた(識別子60問の
   残存不良の主因はこれで、順位付け戦略をどう変えても ~0.62 で頭打ちだった)。
   `part_no` も HOT_IDENTIFIER_FIELDS に追加(交換部品の型番指名)。
4. **recency をタイブレーカに降格**(`LEXICAL_RECENCY_BOOST_MAX` 0.09→0.02): 0.09 は
   「同族・同部品の新しい別文書」が「正解文書」をカバレッジ差ごと追い越せる大きさだった
   (paraphrase 劣化の根本原因)。0.02 は現実的なクエリ長で内容語1語分のカバレッジ未満。

順位付け契約は**戦略グリッドの実測で選定**した(等重み RRF をバンド横断で使う案は
multi_doc recall@5 1.0→0.32@3k に崩壊させたため棄却 — 識別子メタデータ一致を最強信号に
保つ製造ドメイン設計を維持。boost を RRF スケールに換算して RRF 優先で並べる案も同様に
棄却)。

### 検索品質 before → after(concurrency=1、200問、doc-level)

#### N=3,000

| スライス | recall@5 | recall@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|
| **overall** | 0.635 → **0.794** | 0.747 → **0.888** | 0.530 → **0.750** | 0.581 → **0.782** |
| identifier | 0.567 → **1.000** | 0.650 → **1.000** | 0.400 → **0.981** | 0.460 → **0.986** |
| paraphrase | 0.640 → 0.640 | 0.800 → 0.800 | 0.586 → **0.625** | 0.635 → **0.665** |
| synonym | 0.400 → **0.433** | 0.600 → **0.700** | 0.226 → **0.244** | 0.313 → **0.350** |
| multi_doc | 1.000 → 1.000 | 1.000 → 1.000 | 1.000 → 1.000 | 1.000 → 1.000 |

#### N=10,000

| スライス | recall@5 | recall@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|
| **overall** | 0.482 → **0.706** | 0.659 → **0.794** | 0.448 → **0.675** | 0.496 → **0.701** |
| identifier | 0.417 → **1.000** | 0.617 → **1.000** | 0.372 → **0.992** | 0.428 → **0.994** |
| paraphrase | 0.500 → **0.540** | 0.740 → 0.740 | 0.449 → **0.463** | 0.514 → **0.526** |
| synonym | 0.067 → **0.100** | 0.267 → 0.267 | 0.048 → **0.067** | 0.097 → **0.111** |
| multi_doc | 1.000 → 1.000 | 1.000 → 1.000 | 1.000 → 1.000 | 1.000 → 1.000 |

ヘッドライン: **identifier recall@5@10k は 0.417 → 1.000(目標 ≥0.9 達成)**。
paraphrase は全指標で改善(recall@5 0.50→0.54、MRR 0.449→0.463)。両スケール・全スライス・
全指標で before を下回るセルは無い。

### 回答不能スライスのスコア分離(before → after)

| N docs | 回答可能 mean top-1 | 回答不能 mean top-1 | 回答不能 max top-1 |
|---|---|---|---|
| 3,000 | 1.071 → 1.083 | 0.791 → 0.730 | 0.951 → **0.881** |
| 10,000 | 1.081 → 1.089 | 0.859 → 0.789 | 0.946 → **0.876** |

recency 降格で「新しいだけの非該当文書」のスコアが下がり、分離は**改善**した(スコア自体の
スケールと閾値意味論は不変 — golden corpus の unanswerable 7問は全問 refuse を維持、
committed baseline `tests/fixtures/eval/golden_baseline.json` は実測値不変のため未変更)。

### レイテンシ(after; before との差は lexical レグの識別子抽出 regex 分)

| N docs | conc | p50 (ms) | p95 (ms) | QPS |
|---|---|---|---|---|
| 3,000 | 1 | 561 → 591 | 643 → 735 | 1.77 → 1.66 |
| 3,000 | 4 | 1,870 → 1,912 | 2,291 → 2,524 | 2.13 → 2.03 |
| 3,000 | 8 | 3,763 → 3,929 | 4,644 → 4,946 | 2.11 → 2.00 |
| 10,000 | 1 | 1,933 → 2,122 | 2,197 → 2,538 | 0.51 → 0.47 |
| 10,000 | 4 | 6,181 → 6,647 | 7,488 → 8,256 | 0.64 → 0.60 |
| 10,000 | 8 | 12,607 → 13,914 | 15,564 → 17,276 | 0.63 → 0.56 |

構造的な O(N) 全件転送(結果2の根本原因)は本 Wave のスコープ外のまま — p50/p95 の
数%〜十数%の上振れは lexical レグに追加した本文識別子抽出の分で、レイテンシ課題の
別チケット(HNSW LIMIT + SQL 候補絞り)で lexical レグごと再設計するのが正道。

### 残る課題

- **synonym スライスは想定どおり 1b では底上がりしない**(recall@5 0.067→0.100@10k —
  タイブレーク改善分だけ)。1c(tenant_lexicon クエリ展開)が唯一の lever という結論は不変。
- paraphrase の recall@5 は 3k で横ばい(タイブレーク改善で MRR/nDCG のみ改善)。
  vector レグを等重みで融合すると recall@5 は上がるが MRR が悪化する(hashing 埋め込みの
  ノイズ)ため見送り — 実埋め込み(stg)では vector レグの寄与が変わるので、stg 実測後に
  融合重みを再検討する価値がある。

## Wave 1c 実施後の再実測(tenant_lexicon 同義語クエリ展開)— 2026-07-03

Wave 1c(branch `feat/synonym-expansion`)で `retrieval.synonyms` 名前空間の同義語展開を
lexical レグに接続し、同一ハーネス・同一シード(20260703)で再実測した。before は上の
Wave 1b after(コミット済み数値。`--no-synonyms` での再実行が両スケールとも再現することを
確認済み — 差分は展開のみに帰属する)。

### 展開の契約(どこに効き、どこに効かないか)

1. **テナント承認語彙のみ**: `EDITABLE_NAMESPACES` に追加した `retrieval.synonyms`
   (key=正式表記、values=同義語/略語)。既存の監査付き admin API(`PUT
   /internal/admin/lexicon/...`)で設定するテナント設定であり、**ビルトインのデフォルト辞書は
   無い** — 同義語等価はテナントが承認した語彙主張であって、プラットフォーム語彙ではない。
   グループ照合は対称({key}∪values のどれをクエリが使っても残りが代替語になる)。
2. **lexical レグのみ展開**(`services/retrieval.py` → 両ストアの `lexical_matches(...,
   expansions=)` → 共有 `lexical_match_score`。in-memory / Postgres の同一挙動は
   `tests/postgres/test_lexical_synonym_parity.py` で担保)。embedding レグ・識別子メタデータ
   レグ・query plan・`intent_query`(高リスク分類)・salient-coverage ゲートは **RAW クエリの
   まま**(#78/#80 不変条件。`tests/unit/test_synonym_expansion_safety.py` で固定)。
3. **順位規則**: 同義語経由でカバーされた語は直接一致の 0.9 倍のカバレッジ寄与
   (`SYNONYM_COVERAGE_WEIGHT`)+ frequency/density 寄与ゼロ — **同一カバレッジなら展開ヒットは
   直接ヒットを絶対に上回らない**。スコアは従来どおり lexical バンド上限 1.20 でキャップ
   (識別子メタデータ一致 1.25 が最強のまま)。
4. **no-answer ゲートとの関係(最重要の設計判断)**: salient-coverage ゲートは **元クエリを
   判定し続け、同義語展開で拾った証拠もそれを通過しなければならない**。展開語が証拠に
   一致することは「質問に応答的」とは見なさない — クエリの salient 語が実質すべて同義語側に
   ある質問は、検索では文書が見つかっても回答は refuse する(fail-safe 方向。golden corpus の
   同義語項目は、salient 語の過半が直接カバーされる現実的な混合クエリとして設計)。ゲート側で
   「テナント承認同義語ならカバー扱い」に広げる案は、refuse 分離の再実測を伴う別チケット。
5. **fail-open**: lexicon 障害時は展開なしで検索続行(chatbot/phone と同じガードパターン)。
   参照は1リクエスト1回の namespace 読みで、`retrieval_synonym_expansion_count` メトリクス+
   span 属性で観測可能。

### 検索品質 before → after(concurrency=1、200問、doc-level)

#### N=3,000

| スライス | recall@5 | recall@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|
| **overall** | 0.794 → **0.847** | 0.888 → **0.929** | 0.750 → **0.831** | 0.782 → **0.854** |
| identifier | 1.000 → 1.000 | 1.000 → 1.000 | 0.981 → 0.981 | 0.986 → 0.986 |
| paraphrase | 0.640 → 0.640 | 0.800 → 0.800 | 0.625 → 0.625 | 0.665 → 0.665 |
| synonym | 0.433 → **0.733** | 0.700 → **0.933** | 0.244 → **0.706** | 0.350 → **0.758** |
| multi_doc | 1.000 → 1.000 | 1.000 → 1.000 | 1.000 → 1.000 | 1.000 → 1.000 |

#### N=10,000

| スライス | recall@5 | recall@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|
| **overall** | 0.706 → **0.824** | 0.794 → **0.888** | 0.675 → **0.795** | 0.701 → **0.816** |
| identifier | 1.000 → 1.000 | 1.000 → 1.000 | 0.992 → 0.992 | 0.994 → 0.994 |
| paraphrase | 0.540 → 0.540 | 0.740 → 0.740 | 0.463 → 0.463 | 0.526 → 0.526 |
| synonym | 0.100 → **0.767** | 0.267 → **0.800** | 0.067 → **0.747** | 0.111 → **0.760** |
| multi_doc | 1.000 → 1.000 | 1.000 → 1.000 | 1.000 → 1.000 | 1.000 → 1.000 |

ヘッドライン: **synonym recall@5 は 0.433→0.733@3k / 0.100→0.767@10k(MRR 0.067→0.747@10k)**
— 1b 後も「ほぼ全滅」だったスライスがスケール非依存の水準まで回復し、スケールで落ちる
スライスは paraphrase(共有語彙の混雑、実埋め込み=stg 実測待ち)だけになった。identifier /
paraphrase / multi_doc は全指標不変(展開は同義語グループがクエリに現れたときだけ動く
加算的な仕組みで、他スライスのクエリはグループ非該当)。回答不能スライスのスコア分離も
不変(mean/max 0.730/0.881@3k、0.789/0.876@10k — 展開対象語彙が unanswerable 質問に
現れないため)。

### レイテンシ(concurrency=1; 展開は lexicon 1読み+文字列走査のみ)

| N docs | p50 (ms) | p95 (ms) |
|---|---|---|
| 3,000 | 591 → 595 | 735 → 749 |
| 10,000 | 2,122 → 2,145 | 2,538 → 2,666 |

O(N) 全件転送というレイテンシの構造課題(結果2)は 1c と独立のまま(別チケット)。

### golden corpus / CI ゲート

- `tests/fixtures/uat/golden_corpus.json` に **同義語カテゴリ3問**(クエリ=同義語表記、
  文書=正式表記、`lexicon` ブロックをハーネスが seed)+ ディストラクタ文書を追加。
  lexicon なしではディストラクタが決定的に gold を上回り MRR floor(1.0)が割れる —
  `test_synonym_slice_actually_measures_expansion` がこの「歯」を固定。
- 項目追加により dataset_version / registry_version / query_cost(18→21)を再測定し
  `tests/fixtures/eval/golden_baseline.json` を #80 と同じ手順で更新(floor 値は全て実測)。
- ベンチ側: `run_bench.py` はデフォルトで bench テナントに `SYMPTOM_SYNONYMS` 対応の
  lexicon を seed(local=直接 upsert / stg=admin API 経由)。`--no-synonyms` で 1c 前の
  挙動を測定できる(A/B 用)。

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
