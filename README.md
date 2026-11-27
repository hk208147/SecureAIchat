# Secure AI Chat

AIDD学習用プロジェクト
Amazon Bedrock (Claude Sonnet 4.6 / Opus 4.6) を使った個人専用 AI チャットアプリ。
1 ユーザー専用設計。Cognito 認証 (TOTP MFA 必須) でアクセス制御。

---

## 現行仕様

| 機能 | 内容 |
|---|---|
| 認証 | Amazon Cognito、セルフサインアップ無効、TOTP MFA 必須 |
| モデル切り替え | Sonnet 4.6（既定）/ Opus 4.6-v1（比較）、UI で切り替え可能 |
| 思考量 | 軽い / 通常 / 深く考える（Bedrock adaptive thinking: low/medium/high）|
| 会話管理 | セッション一覧・選択・削除（トゥームストーン方式で競合防止）|
| 推定推論費用 | 各アシスタント回答にリアルタイム表示（AU Geo Standard 単価）|
| 入力上限 | 固定文字数上限なし。380,000 UTF-8 バイト超過時は Bedrock 呼び出し前にエラー返却 |
| 履歴保存 | DynamoDB 単一テーブル、TTL 30 日 |
| セキュリティ | Lambda で sub 照合（1 ユーザーのみ許可）、ログに会話内容・sub を含めない |

### 推定推論費用の単価（AU Geo Cross-Region、Standard ティア）

| モデル | 入力 | 出力 |
|---|---|---|
| Sonnet 4.6 (`au.anthropic.claude-sonnet-4-6`) | $3.30 / 1M tokens | $16.50 / 1M tokens |
| Opus 4.6-v1 (`au.anthropic.claude-opus-4-6-v1`) | $5.50 / 1M tokens | $27.50 / 1M tokens |

出典: AWS Bedrock pricing page + Anthropic 公開価格表（In-Region & Geo Cross Region 行）

---

## アーキテクチャ

```
ブラウザ
  │ HTTPS
  ▼
CloudFront (OAC) ──────── S3 (SPA, 非公開)
  │
  │ /chat  /sessions  /messages  (HTTP API)
  ▼
API Gateway HTTP API
  │ JWT オーソライザー (Cognito, scope: personal-chat-api/chat)
  ▼
Lambda (Python 3.12, 512 MB, timeout 60s)
  │ sub 照合 → 入力検証 → DynamoDB 履歴読込
  ├──▶ Bedrock (Converse API, au.anthropic.claude-sonnet-4-6 / opus-4-6-v1)
  └──▶ DynamoDB (会話履歴, TTL 30日)
        └──▶ CloudWatch Logs / EMF Metrics → Alarm → SNS → メール
```

---

## ディレクトリ構成

```
terraform/          インフラ定義 (Terraform)
  terraform.tfvars.example  設定サンプル → terraform.tfvars にコピーして使用
lambda/             Lambda バックエンド (Python 3.12)
  tests/            pytest テストスイート
frontend/           フロントエンド (React + TypeScript + Vite)
  .env.example      環境変数サンプル → .env にコピーして使用
  src/              ソースコード
scripts/            ビルド・検証スクリプト (PowerShell)
docs/               詳細ドキュメント
```

---

## 再構築手順

別の PC で同等の環境を再構築する手順。**全手順を上から順に実行する。**

### 前提ツール

| ツール | バージョン目安 | 用途 |
|---|---|---|
| Node.js | 20 LTS 以上 | フロントエンドビルド |
| Python | 3.12 | Lambda テスト |
| Terraform | 1.9 以上 | インフラ管理 |
| AWS CLI | 2.x | デプロイ・Cognito 操作 |
| PowerShell | 5.1 (Windows 組込) | スクリプト実行 |

### 1. AWS 認証設定

このプロジェクトは AWS SSO を使用する。`bedrock-terraform` プロファイルが Terraform および S3/CloudFront 操作に使われる。

```powershell
# AWS SSO でログイン（ブラウザが開く）
aws sso login --profile bedrock-terraform

# 動作確認
aws sts get-caller-identity --profile bedrock-terraform
```

### 2. Bedrock モデルアクセス確認

ap-southeast-2 コンソール（Amazon Bedrock > モデルアクセス）で以下が有効になっていることを確認:
- `anthropic.claude-sonnet-4-6-v1`
- `anthropic.claude-opus-4-6-v1`

未申請の場合はアクセス申請し、AVAILABLE になるまで待つ。

### 3. Bedrock 推論プロファイル ARN を確認

```powershell
# Sonnet 4.6 推論プロファイル ARN
aws bedrock get-inference-profile `
  --inference-profile-identifier au.anthropic.claude-sonnet-4-6 `
  --region ap-southeast-2 --profile bedrock-terraform

# Opus 4.6-v1 推論プロファイル ARN
aws bedrock get-inference-profile `
  --inference-profile-identifier au.anthropic.claude-opus-4-6-v1 `
  --region ap-southeast-2 --profile bedrock-terraform

# ベースモデル ARN（Sydney と Melbourne の両リージョン）
aws bedrock list-foundation-models --region ap-southeast-2 --profile bedrock-terraform
aws bedrock list-foundation-models --region ap-southeast-4 --profile bedrock-terraform
```

### 4. Terraform 変数ファイルを準備

```powershell
cd terraform
Copy-Item terraform.tfvars.example terraform.tfvars
# terraform.tfvars をエディタで開き、手順 3 で確認した ARN と自分のメールアドレスを設定
# allowed_sub は最初は "" のまま（後で設定する）
```

### 5. Terraform 初期化・インフラ構築

Lambda zip は Terraform が自動生成する（`archive_file` データソース経由）。`build-lambda.ps1` を事前実行する必要はない。  
Terraform が `lambda/` ディレクトリを `dist/lambda.zip` にパッケージ化してから apply を実行するため、**`dist/` ディレクトリが存在しなければ先に作成する**。

```powershell
cd terraform
$env:AWS_PROFILE = "bedrock-terraform"

# dist/ がなければ作成する（Terraform archive_file の出力先）
if (-not (Test-Path "..\dist")) { New-Item -ItemType Directory "..\dist" }

terraform init

# 差分を確認してから apply する
terraform plan -out=tfplan
# 内容を確認する:  0 to destroy が理想。初回は多数の resources が add される。
terraform apply tfplan
```

apply 完了後、出力値を控えておく:

```powershell
terraform output
# api_endpoint, cloudfront_domain, cognito_user_pool_id, cognito_app_client_id,
# cognito_domain_host, frontend_bucket_name, cloudfront_distribution_id
```

### 6. Cognito ユーザー作成

```powershell
$POOL_ID  = terraform output -raw cognito_user_pool_id
$EMAIL    = "your@email.com"   # 自分のメールアドレスに変更

# 一時パスワード生成（大文字・小文字・数字・記号を含む 14 文字以上）
$TempPassword = (-join ((65..90 + 97..122 + 48..57) | Get-Random -Count 12 |
  ForEach-Object { [char]$_ })) + "!1A"
Write-Host "一時パスワード: $TempPassword  ← 控えておくこと"

aws cognito-idp admin-create-user `
  --user-pool-id $POOL_ID `
  --username $EMAIL `
  --user-attributes Name=email,Value=$EMAIL Name=email_verified,Value=true `
  --temporary-password $TempPassword `
  --profile bedrock-terraform

# ユーザー作成直後に sub を取得する（次の手順で使用）
aws cognito-idp admin-get-user `
  --user-pool-id $POOL_ID `
  --username $EMAIL `
  --profile bedrock-terraform
# 出力の "sub" 属性値（UUID 形式）をコピーしておく
```

### 7. allowed_sub を設定して再 apply

```powershell
# terraform.tfvars を編集: allowed_sub = "手順 6 で取得した UUID"
# 例: allowed_sub = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

cd terraform
$env:AWS_PROFILE = "bedrock-terraform"
terraform plan -out=tfplan   # 1 change (Lambda env var) のみであることを確認
terraform apply tfplan
```

### 8. フロントエンド環境変数を設定

```powershell
# terraform output の値を使って frontend/.env を作成
$CF_DOMAIN   = terraform output -raw cloudfront_domain
$API_URL     = terraform output -raw api_endpoint
$POOL_ID     = terraform output -raw cognito_user_pool_id
$CLIENT_ID   = terraform output -raw cognito_app_client_id
$DOMAIN_HOST = terraform output -raw cognito_domain_host   # https:// なし、ホスト名のみ

@"
VITE_USER_POOL_ID=$POOL_ID
VITE_USER_POOL_CLIENT_ID=$CLIENT_ID
VITE_COGNITO_DOMAIN=$DOMAIN_HOST
VITE_API_ENDPOINT=$API_URL
"@ | Out-File -FilePath "..\frontend\.env" -Encoding utf8
```

### 9. フロントエンドビルド・S3 デプロイ

```powershell
cd ..   # プロジェクトルートへ

# ビルド（npm ci + tsc + vite build）
.\scripts\build-frontend.ps1

# S3 同期（削除なし）
$BUCKET = & { cd terraform; terraform output -raw frontend_bucket_name }
aws s3 sync frontend/dist/ "s3://$BUCKET/" --profile bedrock-terraform

# CloudFront キャッシュ無効化
$CF_ID = & { cd terraform; terraform output -raw cloudfront_distribution_id }
aws cloudfront create-invalidation `
  --distribution-id $CF_ID --paths "/*" --profile bedrock-terraform
aws cloudfront wait invalidation-completed `
  --distribution-id $CF_ID --id <invalidation_id> --profile bedrock-terraform
```

### 10. 初回ログイン・MFA 設定

1. ブラウザで `https://<cloudfront_domain>` を開く
2. 「サインイン」→ Cognito Managed Login にリダイレクト
3. メールアドレス + 一時パスワードでログイン
4. 新パスワード設定
5. TOTP MFA 設定（Google Authenticator 等で QR コードをスキャン）
6. ログイン完了後、ブラウザに「Secure AI Chat」画面が表示されチャットが使えることを確認

### 11. 動作確認

1. ブラウザを再読み込み（Ctrl+Shift+R）
2. チャット画面でメッセージを送信し、応答が返ることを確認
3. ヘッダーが「Secure AI Chat」、各回答にモデル名と推定費用が表示されることを確認
4. モデル切り替え（Sonnet 4.6 / Opus 4.6）と思考量切り替えを確認
5. セッション削除を確認
6. 3,000 文字を超えるメッセージを送信し、末尾まで送れることを確認

---

## ローカル検証（AWS 不要）

```powershell
# 全チェック一括実行（Python テスト + TypeScript 型検査 + ビルド + Terraform 検証）
.\scripts\local-verify.ps1

# Python テストのみ
cd lambda
python -m pytest tests/ -v

# フロントエンドビルドのみ
.\scripts\build-frontend.ps1
```

---

## 環境ごとに別途用意が必要な設定

| ファイル | 取得・設定方法 |
|---|---|
| `terraform/terraform.tfvars` | `terraform.tfvars.example` をコピーし、手順 3-4 に従い入力 |
| `frontend/.env` | `terraform apply` 後、手順 7 のコマンドで自動生成 |

---

## 参照ドキュメント

- [アーキテクチャ詳細](docs/ARCHITECTURE.md)
- [デプロイ手順（詳細版）](docs/DEPLOY.md)
- [削除手順](docs/DESTROY.md)
- [セキュリティ設計](docs/SECURITY.md)
- [コストモデル](docs/COST_MODEL.md)
- [実装メモ](docs/IMPLEMENTATION_NOTES.md)

### 段階1の論文執筆支援

Persona管理、論旨検討、資料引用、RAG、Web検索の設計と有効化手順は[段階1の開発方針と機能仕様](docs/PHASE1_RESEARCH_ASSISTANT.md)を参照してください。レビュー用の確認事項は[Claude Code向けレビュー引き継ぎ](docs/PHASE1_CLAUDE_REVIEW.md)に記載しています。
