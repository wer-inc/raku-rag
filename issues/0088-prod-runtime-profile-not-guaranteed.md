# 0088 — prod でも `RAKU_RUNTIME_PROFILE=production` が保証されず、出力ガードレールが無言でオフになる(系統 = deploy / safety / guardrail)

> Priority: **P1/High** / Status: Fixed (2026-08-01, 未コミット) / Labels: `deploy`, `cdk`, `safety`, `guardrail`, `prod`

## 背景(なぜ今)

prod プロファイルガード(deploy.yml「Preflight (prod profile guard)」+ CDK synth-time assert)追加作業の
続きで「他に prod を無防備にする入力の組み合わせはないか」を洗った際に発見。

## どんな課題か

- CDK の `productionRuntimeEnvironment`(`infra/cdk/lib/raku-rag-stack.ts` 227行付近)は
  **visual providers が構成されているか、`answerLlm=bedrock` かつ guardrail id+version が揃っている場合のみ**
  `RAKU_RUNTIME_PROFILE=production` を注入する。`isProd` は条件に入っていない。
- そのため **stage=prod でも** `answer_llm=openai` / `gemini`(または `extractive`)+
  `visual_provider_profile=default` の組み合わせだと runtime profile は既定の `deterministic` のまま。
- `guardrail_from_settings`(`src/raku_rag/providers/guardrails.py` 110–113行)は profile が
  `deterministic` なら **出力ガードレール None** を返す。production profile の fail-closed バックストップは
  「profile が production のとき」しか発動しないので、この構成では**発動する機会すらない**。
- 新設の prod preflight ガードも guardrail 必須チェックは `ANSWER_LLM=bedrock` のときだけ。
  openai/gemini の実 LLM を prod に載せた場合、**出力ガードレールなし・警告なし**で通る。

## どこで起きたか

- コード: `infra/cdk/lib/raku-rag-stack.ts`(`productionRuntimeEnvironment` の条件式)、
  `.github/workflows/deploy.yml`(prod profile guard の guardrail チェックが bedrock 限定)、
  `src/raku_rag/providers/guardrails.py`(deterministic → None)
- 環境: `stage=prod` + `answer_llm=openai|gemini|extractive` + `visual_provider_profile=default`
- 再現条件: 上記入力で dispatch(dry_run=true の synth でも env の欠落は確認可能)

## 影響

- 本番クライアント: 実 LLM(OpenAI/Gemini)の生成出力が**ガードレール未適用**で顧客に返る。
  埋め込み/プロバイダの production バックストップ(profile 前提の防御)も全て無効。
- 監査: 「prod は production profile で動いている」という前提が構成次第で崩れるのに、
  synth も preflight も警告しない(サイレント)。

## どう解決すべきか

1. CDK: `isProd` を `productionRuntimeEnvironment` の有効化条件に加える
   (`isProd || visualProvidersConfigured || (bedrock+guardrail)`)。prod で profile が付かない構成を
   構造的に不可能にする。
2. CDK: prod × 実 LLM(bedrock/openai/gemini)で guardrail 構成が無い場合は synth を throw する
   (現行の bedrock 限定 assert を実 LLM 全般に拡張するか、production profile の fail-closed に委ねるなら
   その旨をコメントで明示)。openai/gemini 用に guardrail が適用可能か(BedrockGuardrailProvider は
   ApplyGuardrail API で LLM 非依存に使えるか)を確認して方式を決める。
3. deploy.yml: prod profile guard の guardrail チェックを `ANSWER_LLM != extractive` 全般に広げる。
4. テスト: `infra/cdk` の synth テストに「prod は必ず RAKU_RUNTIME_PROFILE=production を持つ」を追加。

## QA checklist

- [ ] 再現テストがある(prod + openai/gemini synth で profile 欠落 → 修正後は必ず付与 or throw)。
- [ ] 正常系(prod + bedrock + guardrail)の synth が従来どおり通る。
- [ ] sales/stg の意図的な deterministic 構成を壊さない。
- [ ] security/safety gate を弱めていない。

## 受け入れ条件(DoD)

- stage=prod で `RAKU_RUNTIME_PROFILE=production` が付かないデプロイ構成が存在しない
  (または synth 時に明示的に失敗する)。
- prod で実 LLM を使う全構成で、出力ガードレールが適用されるか fail-closed になる。

## スコープ外

- sales/stg の demo 向け deterministic 構成の廃止。
- guardrail プロバイダ自体の新規実装(既存 BedrockGuardrailProvider の適用範囲確認まで)。

## 参照

- 同時に入れた prod ガード: `.github/workflows/deploy.yml`(prod profile guard)、
  `infra/cdk/lib/raku-rag-stack.ts`(embeddingProvider=openai 必須 assert)
- `docs/production-readiness/paid-pilot-readiness.md`

## 修正内容(2026-08-01)

1. `infra/cdk/lib/raku-rag-stack.ts`: `productionRuntimeEnvironment` の条件に `isProd` を追加。
   stage=prod は構成に関係なく `RAKU_RUNTIME_PROFILE=production` を持つ。
2. `infra/cdk/lib/raku-rag-stack.ts`: guardrail 必須 assert を `useBedrockAnswerLlm` から
   `useRealAnswerLlm`(= `answerLlm !== "extractive"`)に拡張。openai/gemini も対象。
   **未確定だった点の結論**: `BedrockGuardrailProvider` は `apply_guardrail` API を
   `source="OUTPUT"` で回答テキストに適用する(`src/raku_rag/providers/guardrails.py:79-84`)ため
   **LLM 非依存**。openai/gemini の生成出力を同じ Bedrock guardrail で審査できる。
3. `.github/workflows/deploy.yml`: prod profile guard の guardrail チェックを
   `ANSWER_LLM != extractive` 全般に拡張。
4. `infra/cdk/scripts/assert-stage-guards.sh` を追加し `deploy-checks.yml` に結線(9 ケース)。

**profile 強制の副作用調査(全 production-profile 分岐を確認済み)**: rerank は fail-safe で
score-order に縮退(`rerankers.py:36-41`)、LLM は明示 `RAKU_LLM_PROVIDER` が profile より優先
(`llms.py:470-473`)、semantic danger classifier は extractive のとき None(安全側の追加のみ)、
secret store は prod で Secrets Manager が正、exporter は例外安全。**fail-closed なのは guardrail
のみ**で、それは上記 2/3 の assert で synth 時に落とす。よって prod での profile 強制は安全。

**ネガティブコントロール実施済み**: `isProd` を外すと prod+extractive の synth から
`RAKU_RUNTIME_PROFILE=production` が消え、追加したアサーションが FAIL することを確認(テストが
実際に回帰を捕まえることの証明)。その後 fix を復元。

DoD 4項目のうち 1-4 を満たす。残存: `answer_llm=extractive` の prod は警告のみ(拒否ではない)。
