# infra/connect — Amazon Connect 取込みアーティファクト(024)

番号が取得できたあと、Connect コンソールで行う one-time 配線の手順とアーティファクト置き場。
前段の手配(インスタンス作成・番号のサポートケース)は `docs/phone/connect-setup-runbook.md`。

構成(全体像):

```
着信 → Contact Flow (contact-flow.json)
        ├ Lambda action=call_start ──→ /internal/phone/calls/simulate(call_id発行)
        ├ Lex V2 ja-JP(ASRのみ・判断させない)
        ├ Lambda action=turn ────────→ /internal/phone/calls/{id}/turns
        └ $.External.action で分岐: continue(読み上げ→再聴取)/ handoff(キュー転送)/
                                    end_call(切断)/ reject・error(定型案内)
```

## 0. 前提

- CDK を `-c phoneTelephony=connect -c connectInstanceArn=<インスタンスARN>` 付きでデプロイ済み
  (deploy workflow の実行時に指定。Lambda `raku-rag-<stage>-connect-phone-adapter` と
  SSM `/raku-rag/<stage>/phone/did-map` が作成される)。
- DID マッピングを SSM に投入済み(下記 §4)。

## 1. Lex V2 bot(音声→テキスト変換専用・約10分)

Lex は **ASR としてだけ**使う(NLU 判断は raku-rag orchestrator 側 — research.md Decision 2)。

1. コンソール → Amazon Lex → **ボットを作成**(Traditional / 空のボット)
   - 名前: `raku-rag-phone-passthrough` / IAM: 基本ロール自動作成 / 児童向け: いいえ
   - 言語: **日本語 (ja-JP)**、音声: Kazuha(任意 — 実際のTTSはflow側)
2. インテント設計(**重要**):
   - Lex V2 はビルドに最低1つのカスタムインテントが必要。ダミーとして `Noop` を作成し、
     サンプル発話に実際には出ない一文(例: `ゼロゼロ終端キーワード`)を1つだけ登録。
   - それ以外は組込みの **FallbackIntent** に落ちる = すべての発話が
     `$.Lex.InputTranscript`(生テキスト)として flow に返る。フルフィルメントは**無効**のまま。
3. **ビルド** → **バージョンを作成** → エイリアス `live` をそのバージョンに向ける。
4. エイリアス ARN を控える(flow の `REPLACE_ME_LEX_BOT_ALIAS_ARN`)。

## 2. Connect インスタンスへの関連付け

1. Connect コンソール → インスタンス → **フロー**:
   - **Amazon Lex**: 上記 bot / エイリアス `live` を追加
   - **AWS Lambda**: `raku-rag-<stage>-connect-phone-adapter` を追加
     (CDK が Connect からの Invoke 許可を `connectInstanceArn` 条件付きで付与済み)

## 3. Contact Flow の取込み(約10分)

1. `contact-flow.json` をローカルで開き、3つのプレースホルダを置換:
   - `REPLACE_ME_LAMBDA_ARN` → CDK 出力 `ConnectPhoneAdapterArn`
   - `REPLACE_ME_LEX_BOT_ALIAS_ARN` → §1 のエイリアス ARN
   - `REPLACE_ME_QUEUE_ARN` → 転送先キュー(まずは既定の **BasicQueue** の ARN)
   - `REPLACE_ME_CUSTOMER_QUEUE_FLOW_ARN` → `customer-queue-flow.json` を type=CUSTOMER_QUEUE で
     先に取込んだ flow の ARN(キュー待ちを ~70秒で丁寧に打ち切る。無人キューでの無限保留防止)
2. Connect 管理画面(`https://<alias>.my.connect.aws/`)→ ルーティング → **フロー → フローの作成 →
   インポート** で JSON を取込み → **保存 → 公開**。
   - インポートがスキーマ差異で失敗した場合は、上の構成図どおりに手動配線しても10ブロック程度
     (ログ有効化 → TTS音声設定 → Lambda(call_start) → 属性保存 raku_call_id → プロンプト再生(挨拶) →
     顧客の入力を取得(Lex) → Lambda(turn: call_id=$.Attributes.raku_call_id,
     utterance=$.Lex.InputTranscript) → `$.External.action` で分岐 → 各終端)。
3. **電話番号 → このフロー**を紐付け(ルーティング → 電話番号 → フロー選択)。

## 4. DID マッピング(どの番号がどのテナント/ナレッジか)

SSM パラメータ `/raku-rag/<stage>/phone/did-map` に JSON を設定(fail-closed: 未登録番号は定型案内で切断):

```json
{
  "+815012345678": {
    "tenant_id": "demo",
    "user_id": "phone-gateway",
    "groups": [],
    "collection_id": "manuals",
    "scenario_id": "faq-basic"
  }
}
```

- `user_id`(サービスユーザー)への **ACL grant が電話AIの知識範囲**。stg のデモKBは
  migrate-seed が `phone-gateway` に READ を付与済み(scripts/demo/demo_seed.py)。
- 反映は Lambda のコールドスタート時(即時反映したい場合は Lambda を再デプロイ or 数分待つ)。

## 5. 受電テスト(runbook §4 と同じ)

1. 携帯から番号へ発信 → 挨拶 → 「営業時間を教えてください」→ 根拠付き回答(音声)
2. 「人につないでください」→ 転送アナウンス → **CCP**(`.../ccp-v2`)で応答可能(Basic Routing
   Profile のエージェントでログインしておく)
3. `/phone` 画面 → 転送キューに HandoffPackage(要約・マスク済み経緯・引用)が出ること
4. 障害注入: answer-service を止めて着信 → 定型案内(無音にならない)= SC-L3

## トラブルシュート

- **Lambda がタイムアウト**: CloudWatch `/aws/lambda/raku-rag-<stage>-connect-phone-adapter`。
  内部ALBへのSG(CDKが自動設定)と `RAKU_INTERNAL_API_BASE` を確認。
- **「この番号は現在ご利用いただけません」**: DID マップ未登録(§4)。キーは E.164(+81…)。
- **回答が毎回転送になる**: `user_id` に対象コレクションの ACL grant がない(§4)。
- **Flow で Lambda エラー分岐に落ちる**: Connect の Lambda 応答は string→string のフラットマップ必須。
  アダプタは常にその形で返す(`tests/unit/test_phone_connect_adapter.py::test_flatten_values_are_strings`)。
