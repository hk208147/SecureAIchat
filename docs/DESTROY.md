# リソース削除手順

**別途承認が必要。** 以下は手順の記録であり、実行承認ではない。

---

## 1. S3 バケット内オブジェクト削除（Terraform destroy 前に必要）

```powershell
$BUCKET = "personal-chat-app-frontend-<account_id>"
aws s3 rm "s3://$BUCKET/" --recursive --profile bedrock-dev
```

## 2. Terraform destroy

```powershell
cd C:\Users\Hidey\AWS-Learning\terraform
terraform destroy -var-file="terraform.tfvars"
# 削除対象を確認してから承認する
```

## 3. 手動削除が必要な可能性があるリソース

- CloudWatch ロググループ（Terraform 管理外の場合）
- SNS サブスクリプション確認メール（未確認のまま destroy した場合、ペンディング購読が残る）
- DynamoDB テーブルの TTL による物理削除は即時ではない（最大 48 時間）

## 4. 削除後の確認

- AWS コンソールで以下が残っていないことを確認:
  - Lambda 関数
  - API Gateway HTTP API
  - Cognito User Pool
  - DynamoDB テーブル
  - S3 バケット
  - CloudFront ディストリビューション
  - SNS トピック
  - CloudWatch アラーム
  - AWS Budgets
