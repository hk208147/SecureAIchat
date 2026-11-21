# セキュリティ設計

## 認証・認可

| 項目 | 実装 |
|---|---|
| ユーザー作成 | 管理者のみ（セルフサインアップ無効） |
| MFA | TOTP 必須、SMS 不使用 |
| 認証フロー | Authorization Code + PKCE |
| UI | Cognito Managed Login（Essentials）|
| API トークン | アクセストークン（ID トークンを API 認証に使わない） |
| カスタムスコープ | `personal-chat-api/chat`（POST /chat・GET /sessions 両方で必須） |
| Lambda sub 検証 | JWT claims の `sub` を `ALLOWED_SUB` と照合（本人のみ許可）|
| ユーザー入力 | session_id を PK に組み込む前にサーバーで sub を付与（client 送信の userId を信用しない） |

## データ保護

| 項目 | 実装 |
|---|---|
| DynamoDB 暗号化 | AWS 管理キー（SSE 有効） |
| S3 暗号化 | SSE-S3 |
| 通信 | HTTPS 強制（CloudFront が HTTP→HTTPS リダイレクト） |
| S3 公開アクセス | Block Public Access 全有効、OAC 経由のみ |
| ログ内容 | 会話本文・認証トークン・個人情報をログ出力しない |
| DynamoDB TTL | 30 日で自動削除（物理削除は最大 48h 遅延） |

## IAM 最小権限

- Lambda 実行ロールは DynamoDB・Bedrock・CloudWatch Logs の当該リソースのみ
- Bedrock リソースは AU 推論プロファイルと必要な基盤モデル ARN を列挙（`Resource: "*"` 不使用）
- Lambda に SNS Publish 権限なし（アラームから SNS へ直接通知）
- S3 バケットポリシー: SourceArn を当該 CloudFront ディストリビューションに限定

## アプリ側の制約

- サーバー側でモデル ID を固定（クライアントからのモデル指定を受け付けない）
- 入力は 3,000 文字で切り詰め（Lambda とフロントエンドの両方で適用）
- 予約同時実行数 5 でコスト爆発を緩和（課金の厳密な上限ではない）

## 除外事項（有料・過剰）

- Cognito Advanced Security Features（有料）
- WAF
- Identity Pool
- DynamoDB PITR
