# Flow — Sell skins

A signed-in user with a trade link sells skins from their Steam inventory and is paid in soʻm:
to the csmarket balance (with a bonus) or to a card (with a fee), once Steam's 7-day
protection of the trade is over. Design: ADR-0016; operations:
[`sales.md`](../../runbooks/sales.md); diagram:
[`skin-sale.mmd`](../../architecture/sequence-diagrams/skin-sale.mmd).

## What the seller sees

1. **`/sell`** while selling is on (else «Скоро»): signed out → «Войдите через Steam»; no
   trade link → the trade-link form; else the items we buy now, priced in soʻm, dearest
   first, and «Показаны предметы, которые можно продать сейчас». A Steam refusal of the
   account (private profile, trade ban, …) is said in plain words.
2. **The cart:** the chosen items, «Куда получить» — the balance (+2 % by default), a saved
   card (up to three) or a new Uzcard / Humo / Uzum Visa (the number checked as it is typed),
   the fee or the bonus, «Вы получите», and «Деньги придут через 7 дней после обмена».
   «Продать за {sum}» stays off under the minimum («Добавьте ещё на {sum}») and for a card
   under 30 000 soʻm.
3. **«Продать»:** the browser goes to `/account/sales/{number}`: «Примите обмен» with
   «Открыть обмен в Steam», the bot's name and the deadline. If prices moved: «Цены
   обновились — проверьте сумму и нажмите ещё раз», and the inventory is read again.
4. **After the trade:** «Скины получены. {amount} поступят {date}.» — then «Деньги на
   балансе» or, for a card, «Отправляем деньги» → «Деньги отправлены». A rejected card
   payout: «Перевод на карту не прошёл — {amount} зачислены на баланс», with the admin's
   reason on the sale page and in the letter. A declined or expired offer: «Продажа не
   состоялась»; a trade reversed in Steam: «Обмен отменён».
5. **Account:** «Обмены» → «Продажи» lists the sales; «Мои карты» lists and forgets cards;
   «Транзакции» shows «Ожидает зачисления: {sum}» while balance sales wait, and the credit
   as «Продажа скинов».
6. **Letters** (to a confirmed address): skins received, money sent, sale did not go through.

## Rules

- The payout is fixed when the sale is created; Skinslink crediting a little less is ours.
- The minimum is on the sum of the items (1.10 $ at Skinslink's prices by default; Skinslink refuses exactly 1 $), not per item.
- Nothing is paid before Steam's protection ends; nothing is paid twice; a reversal is never
  debited automatically.
