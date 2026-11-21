# コストモデル

PHASE2_IMPLEMENTATION_SPEC.md §10 の参考値。現在の公式価格・実課金を保証しない。
デプロイ前に最新単価を確認すること。

---

## Bedrock 仮定単価（AU Cross-Region Inference）

| 項目 | 仮定値 |
|---|---|
| 入力 | 3.30 USD / 1M tokens |
| 出力 | 16.50 USD / 1M tokens |
| 1 リクエスト平均 | 入力 1,500 トークン（履歴再送込み）/ 出力 800 トークン |

## Bedrock 月次試算（キャッシュ割引なし）

| 月間リクエスト | 入力費 (USD) | 出力費 (USD) | Bedrock 計 (USD) |
|---:|---:|---:|---:|
| 300 | 1.49 | 3.96 | 5.45 |
| 900 | 4.46 | 11.88 | 16.33 |
| 1,500 | 7.43 | 19.80 | 27.23 |

## Global との比較（同じ Bedrock 小計同士）

- AU 1,500 req: 27.23 USD
- Global 1,500 req: 24.75 USD（入力 3.00 / 出力 15.00）
- 差額: 2.48 USD（約 10%）

旧資料の 2.38 USD は比較スコープ非対称のため採用しない（PHASE2 §10）。

## その他コンポーネント

以下は無料枠適用を一律に断定せず、実費として列挙する。
デプロイ後 Billing で確認すること。

- CloudFront: リクエスト数 + データ転送
- S3: ストレージ + リクエスト
- API Gateway HTTP API: リクエスト数
- Lambda: 実行回数 + GB-秒
- Cognito: MAU 数
- DynamoDB: 読み書き + ストレージ
- CloudWatch Logs: 保存 + クエリ
- CloudWatch Metrics / Alarms
- SNS: 配信数
- AWS Budgets: 予算数

## クレジット

過去の記録: 120〜140 USD クレジット。現在の残高・適用先・期限は Billing > Credits で確認。
Marketplace サービスに適用されるかは別途確認が必要。
