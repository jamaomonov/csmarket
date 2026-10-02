"""Every customer-facing string of the letters, in ru / uz / en (M4b T4).

Owner copy rules (AGENTS §12): short sentences, outcome not mechanism, «вы»; no
marketplace or refund internals. Uzbek uses ʻ (U+02BB) after o/g and ʼ (U+02BC) elsewhere.
Placeholders: ``{number}``, ``{skin}``, ``{time}``, ``{amount}``.
"""

from __future__ import annotations

from typing import Final

#: ``COPY[locale][key]``.
COPY: Final[dict[str, dict[str, str]]] = {
    "ru": {
        "receipt.subject": "Заказ #{number} оплачен",
        "receipt.body": "Оплата получена. Покупаем {skin} — обмен придёт в Steam, примите его.",
        "trade_sent.subject": "Обмен по заказу #{number} отправлен",
        "trade_sent.body": "Продавец отправил обмен в Steam. Примите его до {time} по Ташкенту.",
        "trade_sent.body_open": "Продавец отправил обмен в Steam. Примите его в Steam.",
        "refunded.subject": "Деньги по заказу #{number} на балансе",
        "refunded.body": "Обмен не состоялся. {amount} вернулись на баланс csmarket.",
        "verify.subject": "Подтвердите почту",
        "verify.body": (
            "Нажмите кнопку, чтобы получать письма о заказах. Ссылка действует 24 часа. "
            "Если это были не вы, просто удалите письмо."
        ),
        "button.order": "Открыть заказ",
        "button.balance": "Открыть баланс",
        "button.verify": "Подтвердить почту",
        "fallback": "Кнопка не работает? Откройте ссылку:",
        "footer": "csmarket.uz — скины CS2 в Узбекистане",
        "footer.auto": "Письмо отправлено автоматически, отвечать на него не нужно.",
        "currency": "сум",
    },
    "uz": {
        "receipt.subject": "#{number} buyurtma toʻlandi",
        "receipt.body": (
            "Toʻlov qabul qilindi. {skin} sotib olinmoqda — almashuv Steamʼga keladi, "
            "uni qabul qiling."
        ),
        "trade_sent.subject": "#{number} buyurtma boʻyicha almashuv yuborildi",
        "trade_sent.body": (
            "Sotuvchi Steamʼda almashuv yubordi. Uni Toshkent vaqti bilan {time} gacha "
            "qabul qiling."
        ),
        "trade_sent.body_open": "Sotuvchi Steamʼda almashuv yubordi. Uni Steamʼda qabul qiling.",
        "refunded.subject": "#{number} buyurtma puli balansda",
        "refunded.body": "Almashuv amalga oshmadi. {amount} csmarket balansiga qaytarildi.",
        "verify.subject": "Pochtangizni tasdiqlang",
        "verify.body": (
            "Buyurtmalar haqida xat olish uchun tugmani bosing. Havola 24 soat amal qiladi. "
            "Agar bu siz boʻlmasangiz, xatni oʻchirib tashlang."
        ),
        "button.order": "Buyurtmani ochish",
        "button.balance": "Balansni ochish",
        "button.verify": "Pochtani tasdiqlash",
        "fallback": "Tugma ishlamayaptimi? Havolani oching:",
        "footer": "csmarket.uz — Oʻzbekistonda CS2 skinlari",
        "footer.auto": "Xat avtomatik yuborildi, unga javob berish shart emas.",
        "currency": "soʻm",
    },
    "en": {
        "receipt.subject": "Order #{number} is paid",
        "receipt.body": (
            "Payment received. We are buying {skin} — a trade offer will arrive in Steam, "
            "accept it."
        ),
        "trade_sent.subject": "Trade offer for order #{number} is sent",
        "trade_sent.body": (
            "The seller sent you a trade offer in Steam. Accept it by {time} Tashkent time."
        ),
        "trade_sent.body_open": "The seller sent you a trade offer in Steam. Accept it in Steam.",
        "refunded.subject": "Money for order #{number} is on your balance",
        "refunded.body": "The trade did not happen. {amount} went back to your csmarket balance.",
        "verify.subject": "Confirm your email",
        "verify.body": (
            "Press the button to get emails about your orders. The link works for 24 hours. "
            "If this wasn't you, just delete this email."
        ),
        "button.order": "Open order",
        "button.balance": "Open balance",
        "button.verify": "Confirm email",
        "fallback": "Button not working? Open the link:",
        "footer": "csmarket.uz — CS2 skins in Uzbekistan",
        "footer.auto": "This email was sent automatically; no need to reply.",
        "currency": "UZS",
    },
}
