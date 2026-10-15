# Flow — Sell skins

A signed-in user with a trade link sells skins from their Steam inventory and is paid in soʻm:
to the csmarket balance (with a bonus) or to a card (with a fee), once Steam's 7-day
protection of the trade is over. Design: ADR-0016; operations:
[`sales.md`](../../runbooks/sales.md); diagram:
[`skin-sale.mmd`](../../architecture/sequence-diagrams/skin-sale.mmd).

## What the seller sees

1. **`/sell`** while selling is on (else «Скоро», `noindex`) is indexed and ends, for everyone,
   in a server-rendered «Как продать скины КС2 (CS2) в Узбекистане»: four steps, where the money
   goes, the buy-back terms and five questions (FAQPage JSON-LD) — no percents or fees. Above
   it the app: signed out → «Войдите через Steam»; no
   trade link → the trade-link form; else the items we buy now, priced in soʻm, dearest
   first, and «Показаны предметы, которые можно продать сейчас», and a «Мои продажи» link. A
   Steam refusal of the account (private profile, trade ban, …) is said in plain words, with
   «Повторить». A trade link found bad says why and shows the trade-link form («Изменить»,
   «где взять?») instead of a retry; selling switched off: «Выкуп скинов временно
   недоступен»; no rate or an outage: «Попробуйте через минуту» with «Повторить».
2. **The cart:** the chosen items, «Куда получить» — the balance (+2 % by default), a saved
   card (up to three) or a new Uzcard / Humo / Uzum Visa (the number checked as it is typed),
   the fee or the bonus, «Вы получите», and «Что дальше»: accept the trade in Steam → Steam's
   7 days → the money (to the balance 7 days after the trade; to a card after the 7 days,
   usually within 2 days). A number of another type says «Это не карта {type}», a typo
   «Проверьте номер карты». «Продать за {sum}» stays off under the minimum («Добавьте ещё на
   {sum}»; the API's refusal names the minimum) and for a card under 30 000 soʻm (said then).
   A typed card is saved once: a refused sale retried with it pays to the saved card (the cart
   switches to it), never a second copy. A saved card deleted meanwhile: «Этой карты больше
   нет — выберите другую», and the cart falls back to the balance.
3. **«Продать»:** the browser goes to `/account/sales/{number}`: «Примите обмен» with
   «Открыть обмен в Steam», the bot's name and the deadline (the sentence drops whichever
   Steam did not give). If prices moved: «Цены
   обновились — проверьте сумму и нажмите ещё раз», and the inventory is read again.
4. **After the trade:** «Скины получены. {amount} поступят {date}.» (a card: «После {date}
   отправим {amount} на карту …») — then «Деньги на балансе» or, for a card, «Отправляем
   деньги» → «Деньги отправлены». A rejected card payout: «Перевод на карту не прошёл.
   {amount} зачислены на ваш баланс», «Вы получите» = the items' sum, no fee row; the admin's
   reason is never shown to the seller (nor in the letter). A declined or expired offer: «Продажа не
   состоялась»; a trade reversed in Steam: «Обмен отменён».
5. **Account:** «Обмены» lists the sales beside the purchases («Продажи» and «В холде» filter
   them; the sale page shows the steps Обмен принят → Защита Steam → Деньги, items with their
   wear); the header shows «+{sum} в холде» under the balance; the profile's «Мои карты» (`/account/cards` redirects there) lists cards by brand logo and forgets them;
   «Транзакции» shows «Ожидает зачисления: {sum}» while balance sales wait, and the credit
   as «Продажа скинов».
6. **Letters** (to a confirmed address): skins received, money sent, sale did not go through.

## Rules

- The payout is fixed when the sale is created; Skinslink crediting a little less is ours.
- The minimum is on the sum of the items (1.10 $ at Skinslink's prices by default; Skinslink refuses exactly 1 $), not per item.
- Nothing is paid before Steam's protection ends; nothing is paid twice; a reversal is never
  debited automatically.
