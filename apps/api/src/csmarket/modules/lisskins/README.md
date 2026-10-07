# `lisskins` — the third buy source

Owns everything csmarket knows about LIS-SKINS (spec
`docs/superpowers/specs/2026-10-07-lisskins-buy-source-design.md`): the HTTP client, the
reader of the public price export, the snapshot of instant lots and its roll-up onto the
catalogue, the checkout's availability check, the purchase records and the balance read. It
does not own pricing rules (`skins`) or orders (`orders` buys and applies statuses).

## Settings

| Setting                                     | Default                                                       | Meaning                                        |
| ------------------------------------------- | ------------------------------------------------------------- | ---------------------------------------------- |
| `CSMARKET_LISSKINS_ENABLED`                 | `false`                                                       | The switch; with the key → `lisskins_active`   |
| `CSMARKET_LISSKINS_API_KEY`                 | empty                                                         | `Authorization: Bearer`                        |
| `CSMARKET_LISSKINS_BASE_URL`                | `https://api.lis-skins.com/v1`                                |                                                |
| `CSMARKET_LISSKINS_EXPORT_URL`              | `https://lis-skins.com/market_export_json/api_csgo_full.json` | The public price export (streamed)             |
| `CSMARKET_LISSKINS_STALE_MINUTES`           | `20`                                                          | An older snapshot offers and prices nothing    |
| `CSMARKET_LISSKINS_REQUEST_TIMEOUT_SECONDS` | `10`                                                          | Export, info, balance                          |
| `CSMARKET_LISSKINS_BUY_TIMEOUT_SECONDS`     | `35`                                                          | `POST /market/buy`                             |
| `CSMARKET_LISSKINS_CHECK_TIMEOUT_SECONDS`   | `4`                                                           | The checkout's `check-availability` (ADR-0012) |
| `CSMARKET_LISSKINS_BALANCE_ALERT_USD`       | `100`                                                         | `LisskinsBalanceLow` fires below it            |
