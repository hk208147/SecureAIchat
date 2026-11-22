# デプロイ手順

**前提**: AWSへの作成・変更、課金を伴うデプロイは事前承認が必要。読み取り専用の状態確認とローカル検証は実施可能。未デプロイ。

---

## 0. デプロイ前チェックリスト

- [ ] Bedrock モデルアクセス確認（FTU フォーム提出・`GetFoundationModelAvailability` で AVAILABLE 確認）
- [ ] `aws bedrock get-inference-profile` で Bedrock ARN を確認・`terraform.tfvars` に記載
- [ ] 120 USD クレジットの Bedrock 適用可否を Billing > Credits で確認
- [ ] 既存の AWS Budgets ($5 設定の有無) を Billing コンソールで確認
- [ ] `aws sso login --profile bedrock-terraform` でセッション有効確認
- [ ] AU Cross-Region Inference の Free plan 利用可否確認（初回成功後 15 分以上経過して継続確認）
- [ ] `terraform.tfvars` の `alert_email` 設定
- [ ] `frontend/.env.local` は Terraform output 後に作成（後述）

---

## 1. Terraform 初期化・インフラ構築

AWS providerは `~> 6.12.0`。旧v5のlockファイルがある場合、`terraform init -upgrade` で更新し、生成された `.terraform.lock.hcl` を保存する。Managed Login用のbrandingリソースを削除しない。

```powershell
cd C:\Users\Hidey\AWS-Learning\terraform
$env:AWS_PROFILE = "bedrock-terraform"
$env:AWS_REGION = "ap-southeast-2"

# terraform.tfvars を作成（デプロイ前チェック後）
# terraform.tfvars の内容:
#   alert_email                    = "your@email.com"
#   allowed_sub                    = ""  # ユーザー作成後に設定
#   bedrock_inference_profile_arn  = "arn:aws:bedrock:..."  # 要確認
#   bedrock_base_model_arns        = ["arn:aws:bedrock:ap-southeast-2::...", "arn:aws:bedrock:ap-southeast-4::..."]

terraform init
terraform plan -var-file="terraform.tfvars"
# plan 内容を確認してから apply を承認する
# terraform apply は別途承認必須
```

---

## 2. Cognito ユーザー作成・ALLOWED_SUB 設定

```powershell
# Terraform apply 後に実行
$POOL_ID = terraform output -raw cognito_user_pool_id

# 一時パスワードを生成（大文字・小文字・数字・記号を含む 14 文字以上）
$TempPassword = (-join ((65..90 + 97..122 + 48..57) | Get-Random -Count 12 | ForEach-Object {[char]$_})) + "!1A"
Write-Host "一時パスワード: $TempPassword  ← 控えておくこと（次のステップで使用）"

aws cognito-idp admin-create-user `
  --user-pool-id $POOL_ID `
  --username "your@email.com" `
  --user-attributes Name=email,Value="your@email.com" Name=email_verified,Value=true `
  --temporary-password $TempPassword `
  --profile bedrock-terraform

# sub を取得
aws cognito-idp admin-get-user `
  --user-pool-id $POOL_ID `
  --username "your@email.com" `
  --profile bedrock-terraform

# 取得した sub を terraform.tfvars に設定して再 apply
# allowed_sub = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

---

## 3. Lambda パッケージビルド

`terraform plan` 実行時に `archive_file` データソースが `lambda/` を `dist/lambda.zip` へ自動パッケージ化する。`build-lambda.ps1` の手動実行は不要。

`dist/` ディレクトリが存在しない場合は `terraform plan` 前に作成する（`local-verify.ps1` が自動作成する）。

```powershell
# dist/ がなければ作成する（terraform plan で archive_file が参照する出力先）
if (-not (Test-Path "dist")) { New-Item -ItemType Directory dist }
```

> `terraform plan -out=tfplan` で保存したプランを `terraform apply tfplan` で適用する場合、`dist/lambda.zip` をプラン保存後から apply まで変更しないこと。

---

## 4. フロントエンドビルド・S3 デプロイ

```powershell
# terraform output から値を取得して .env.local 作成
cd C:\Users\Hidey\AWS-Learning\terraform
$CF_DOMAIN    = terraform output -raw cloudfront_domain
$API_ENDPOINT = terraform output -raw api_endpoint
$POOL_ID      = terraform output -raw cognito_user_pool_id
$CLIENT_ID    = terraform output -raw cognito_app_client_id
$DOMAIN_HOST  = terraform output -raw cognito_domain_host   # ホスト名のみ（https:// なし）

@"
VITE_USER_POOL_ID=$POOL_ID
VITE_USER_POOL_CLIENT_ID=$CLIENT_ID
VITE_COGNITO_DOMAIN=$DOMAIN_HOST
VITE_API_ENDPOINT=$API_ENDPOINT
"@ | Out-File -FilePath "..\frontend\.env.local" -Encoding utf8

# フロントエンドビルド
cd C:\Users\Hidey\AWS-Learning
.\scripts\build-frontend.ps1

# S3 同期・CloudFront キャッシュ削除（別途承認）
# build-frontend.ps1 で作業ディレクトリが変わる場合があるため明示的に戻す
cd C:\Users\Hidey\AWS-Learning\terraform
$BUCKET = terraform output -raw frontend_bucket_name
aws s3 sync ..\frontend\dist\ "s3://$BUCKET/" --profile bedrock-terraform
$CF_ID = terraform output -raw cloudfront_distribution_id
aws cloudfront create-invalidation --distribution-id $CF_ID --paths "/*" --profile bedrock-terraform
```

---

## 5. 動作確認

1. ブラウザで `https://<cloudfront_domain>` を開く
2. サインインボタン → Cognito Managed Login へリダイレクト
3. 一時パスワードでログイン → パスワード変更 → TOTP MFA 設定
4. チャット画面でメッセージ送信
5. 15 分以上経過後にも正常動作することを確認（ISSUE-05 継続確認）
6. 504などのエラー時は自動再送せず、セッションを開き直して保存済み回答を確認する。

---

## 注意事項

- `terraform apply` は別途承認が必要。plan 確認後に改めて依頼すること。
- 初回applyでは `allowed_sub = ""` とし、Lambdaは全ユーザーを拒否する（fail closed）。Cognitoユーザー作成後に本人のsubを設定し、再applyしてから試用する。
- ログアウト URL (`/logout`) は Cognito コンソールで確認する。
- デプロイ後の実費用は Billing コンソールで追跡すること。
