# 0089 — prod デプロイの既定が demo KB(東洋精機)を本番 DB に投入する(系統 = deploy / seed / data-quality)

> Priority: **P1/High** / Status: Fixed (2026-08-01, 未コミット) / Labels: `deploy`, `demo-seed`, `prod`, `data-quality`

## 背景(なぜ今)

prod プロファイルガード追加作業の続きで、prod dispatch を既定入力で流した場合に何が起きるかを
追跡して発見。0080(seed がユーザーアップロードを消す)は purge 対象の限定で修正済みだが、
「demo KB を投入すること自体」は stage 非依存のまま残っている。

## どんな課題か

- `run_migrate_seed`(deploy.yml)の既定は **true**。migrate-seed ECS タスク
  (`infra/cdk/lib/raku-rag-stack.ts` `MigrateSeedTaskDefinition`)は stage を問わず
  `scripts/pg-migrate.sh up` → `scripts/demo/demo_seed.sh` を**無条件に連結実行**する。
- つまり既定のまま prod をデプロイすると、有償顧客の本番 DB に demo テナント(`demo`)の
  curated 東洋精機 KB(18件)が投入される。マイグレーションだけ流したい prod では
  `run_migrate_seed=false` にすると**マイグレーションまで止まる**(migrate と seed が分離不能)。
- 0080 の修正でユーザーデータの巻き添え purge は防がれたが、seed 自身の書き込みは行われる。

## どこで起きたか

- コード: `.github/workflows/deploy.yml`(`run_migrate_seed` 既定 true)、
  `infra/cdk/lib/raku-rag-stack.ts`(MigrateSeedContainer の command が migrate と seed を固定連結)、
  `scripts/aws/migrate-seed.sh`、`scripts/demo/demo_seed.sh`
- 環境: stage=prod(既定入力での dispatch)
- 再現条件: prod dispatch で `run_migrate_seed` を触らない

## 影響

- 本番クライアント: 顧客環境に demo テナント・demo 文書が存在する(データ品質・信頼性・監査上の問題)。
- 運用: prod のスキーマ更新のたびに「seed も一緒に走る」か「migrate ごと止める」かの二択になる。

## どう解決すべきか

1. migrate と seed を分離する(タスク定義の containerOverrides で command を切り替えるか、
   `RUN_SEED=0/1` 環境変数を migrate-seed.sh → RunTask の overrides で渡す)。
2. deploy.yml: prod では seed を既定 off(migrate のみ)。sales/stg は現行どおり seed 込み既定 on。
   prod で seed を明示要求された場合は警告を出す(または prod profile guard で拒否)。
3. テスト: workflow のガード分岐と migrate-seed.sh のモード分岐の unit/contract テスト。

## QA checklist

- [ ] prod 想定(seed off)で migrate のみが実行されることを確認できる。
- [ ] sales/stg の demo 運用(seed on)が従来どおり動く。
- [ ] 0080 の保全不変条件(`file-*` 保全)を弱めていない。
- [ ] tenant/ACL 境界を越えない。

## 受け入れ条件(DoD)

- 既定入力の prod デプロイが demo KB を本番 DB に書き込まない。
- prod でマイグレーションのみを安全に適用できる経路がある。

## スコープ外

- demo_seed の curated KB 自体の変更。
- 既に seed 済みの環境からの demo データ削除ツール(必要なら別 issue)。

## 参照

- `issues/0080-deploy-seed-wipes-user-uploads.md`(purge 限定の恒久修正)
- `scripts/demo/demo_seed.py` / `scripts/aws/migrate-seed.sh`

## 修正内容(2026-08-01)

1. **migrate と seed を分離**(`infra/cdk/lib/raku-rag-stack.ts` MigrateSeedContainer):
   `scripts/pg-migrate.sh up` は常に実行し、`demo_seed.sh` は `RUN_SEED=1` のときだけ実行する分岐に変更。
   タスク定義の環境変数 `RUN_SEED` の既定は **prod=0 / それ以外=1**。未設定時も `${RUN_SEED:-0}` で
   seed しない側に倒れる(fail-safe)。
2. **per-run 上書き**(`scripts/aws/migrate-seed.sh`): `RUN_SEED` env を追加し、ECS RunTask の
   `--overrides containerOverrides` で注入。既定はスタック名由来(`*-prod` → 0、それ以外 → 1)。
   prod に対して `RUN_SEED=1` を明示した場合は WARNING を出す。完了メッセージも実際の動作に一致させた。
3. **workflow**(`.github/workflows/deploy.yml`): 入力 `seed_demo_kb`(`auto` / `off`、既定 `auto`)を追加。
   prod では `auto` でも `RUN_SEED=0`。**prod でシードする選択肢は入力として用意していない**
   (意図的。必要なら `STACK=RakuRag-prod RUN_SEED=1 bash scripts/aws/migrate-seed.sh` を手動実行)。
   `run_migrate_seed` の説明も「マイグレーション適用」に修正(seed は別入力)。
4. **テスト**: `infra/cdk/scripts/assert-stage-guards.sh` に prod=`RUN_SEED=0` / sales=`RUN_SEED=1` の
   synth アサーションを追加(`deploy-checks.yml` で CI 実行)。

**検証**: (a) synth 済みテンプレートから実際のコンテナ command 文字列を取り出し、`RUN_SEED=0/1/未設定`
の3通りをスタブ実行 → migrate は常時実行・seed は 1 のときのみ・未設定は seed なし、を確認。
(b) AWS CLI をスタブして `migrate-seed.sh` を4通り実行 → prod 既定 0、prod+明示1 は警告付きで1、
stg 既定 1、および `--overrides` JSON が正しいことを確認。(c) workflow の RUN_SEED 判定を
stage×seed_demo_kb の6通りで実行し全て期待どおり。

**0080 の不変条件は不変**: `demo_seed.py` の `select_purge_ids`(`file-*` のユーザーアップロードを
PRESERVE)には一切触れていない。変更したのは seed を「呼ぶかどうか」だけ。

DoD 2項目(既定 prod デプロイがデモKBを書き込まない / prod でマイグレーションのみ適用できる経路がある)を満たす。
**既に seed 済みの環境から demo データを削除するツールは本 issue のスコープ外**(元 issue 記載のとおり)。
