# `skinslink` — the second buy source

Owns everything csmarket knows about Skinslink (spec
`docs/superpowers/specs/2026-10-06-skinslink-buy-source-design.md`): the HTTP client, a mirror
of its CS2 stock, the purchase records, the status webhook and the balance read. It does not
price anything (`skins`) and does not own orders (`orders`); both reach it through `api.py`.

## Settings

| Setting                                      | Default                            | Meaning                                          |
| -------------------------------------------- | ---------------------------------- | ------------------------------------------------ |
| `CSMARKET_SKINSLINK_ENABLED`                 | `false`                            | The switch; with both keys → `skinslink_active`  |
| `CSMARKET_SKINSLINK_API_KEY`                 | empty                              | `X-Api-Key`                                      |
| `CSMARKET_SKINSLINK_SECRET`                  | empty                              | Verifies webhook signatures                      |
| `CSMARKET_SKINSLINK_BASE_URL`                | `https://api.skinslink.com/api/v1` |                                                  |
| `CSMARKET_SKINSLINK_MIRROR_STALE_MINUTES`    | `10`                               | An older mirror offers and prices nothing        |
| `CSMARKET_SKINSLINK_REQUEST_TIMEOUT_SECONDS` | `10`                               | Catalogue, status, balance                       |
| `CSMARKET_SKINSLINK_BUY_TIMEOUT_SECONDS`     | `35`                               | `POST /merchant/purchase` (≤ 30 s on their side) |
| `CSMARKET_SKINSLINK_BALANCE_ALERT_USD`       | `100`                              | `SkinslinkBalanceLow` fires below it             |
