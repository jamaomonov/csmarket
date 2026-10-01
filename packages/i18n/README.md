# @csmarket/i18n

Single source of truth for translations. Three locales: `ru` (default), `uz`, `en`. Every
key must exist in all three locale files; CI will fail otherwise.

Files are organised by feature namespace: `locales/<locale>/<namespace>.json`.

Consumers: `apps/web` (next-intl) and `apps/admin` (static import of `ru`).
