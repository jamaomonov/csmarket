# @csmarket/i18n

Single source of truth for translations. Three locales: `ru` (default), `uz`, `en`. Every
key must exist in all three locale files; CI will fail otherwise.

Files are organised by feature namespace: `locales/<locale>/<namespace>.json`.

Consumers: `apps/web` (next-intl) and `apps/admin` (static import of `ru`).

`legal.json` holds the storefront's legal documents (`/legal`, `apps/web/src/lib/legal.ts`). It
is server-only: the web layout leaves it out of the client catalogue. Russian is the master
text; `uz` and `en` are faithful translations of it, and the agreement says Russian prevails.
