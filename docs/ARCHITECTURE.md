# アーキテクチャ概要

```
ブラウザ
  │ HTTPS
  ▼
CloudFront (デフォルトドメイン, HTTP→HTTPS リダイレクト)
  │ OAC                    │ 別経路 (CORS)
  ▼                        ▼
S3 (非公開)          API Gateway HTTP API
React/Vite SPA         POST /chat
                        GET /sessions
  │ 認証リダイレクト          │ JWT オーソライザー
  ▼                        │ スコープ: personal-chat-api/chat
Cognito Managed Login    │
User Pool (TOTP MFA)     ▼
  │ アクセストークン      Lambda (Python 3.12)
  └──────────────────▶   認証 → 入力検証 → 履歴読込
                          │          │
                          ▼          ▼
                        Bedrock    DynamoDB
                        Converse   単一テーブル
                        au.sonnet  会話履歴
                        4.6
                          │
                          ▼
                       CloudWatch Logs (7日)
                       EMF → CloudWatch Metrics
                       Alarm → SNS → メール
                       AWS Budgets → メール
```

## コンポーネント詳細

| コンポーネント | 設定 |
|---|---|
| CloudFront | デフォルトドメイン、OAC、SPA 404 ルーティング |
| S3 | Block Public Access 全有効、SSE-S3 |
| Cognito User Pool | セルフサインアップ無効、TOTP MFA 必須、Managed Login Essentials |
| Cognito App Client | PKCE、アクセストークン 60 分、リフレッシュ 7 日 |
| API Gateway | HTTP API、スロットリング 5 req/s burst 10 |
| Lambda | Python 3.12、512 MB、timeout 60s、同時実行 5 |
| Bedrock | Converse API、`au.anthropic.claude-sonnet-4-6`、max_tokens 4,000 |
| DynamoDB | オンデマンド、TTL 30 日、PITR 無効 |
| CloudWatch | Logs 7 日、2 アラーム（リクエスト数・出力トークン）|
| SNS | 1 トピック、メール購読 |
| AWS Budgets | $25 警告 + $30 通知（2 リソース） |

## 設計上の制約

- HTTP API の最大統合タイムアウト: 29 秒（Lambda 60s と乖離あり）
- Bedrock ARN: デプロイ前に `get-inference-profile` で確認が必要
- 月次コスト自動停止なし（通知のみ）
- AU Cross-Region Inference: ap-southeast-2 → ap-southeast-2/ap-southeast-4 にルーティング
