"""The letter shell: table layout, inline styles, one CTA button (M4b T4).

Email-client-safe HTML (Gmail, Apple Mail, Outlook): tables, inline styles, a "bulletproof"
button with an Outlook fallback, a plain-text link under it. No images, no external fonts,
no tracking pixels — the header is a text wordmark in the storefront's colours.
"""

from __future__ import annotations

from html import escape

from csmarket.modules.notifications.copy import COPY

_DARK = "#14171F"
_ACCENT = "#EDB234"
_ON_ACCENT = "#241B0B"
_PAGE_BG = "#F4F5F7"
_CARD_BG = "#FFFFFF"
_BORDER = "#E6E8EC"
_HEADING = "#0F1117"
_BODY = "#4A4F5C"
_MUTED = "#8A90A0"
_LINK = "#8A5A00"
_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"


def paragraph(text: str) -> str:
    """One body paragraph; ``text`` is escaped."""
    return (
        f'<p style="margin:0 0 16px;font-family:{_FONT};font-size:15px;line-height:23px;'
        f'color:{_BODY};">{escape(text)}</p>'
    )


def button(*, href: str, label: str) -> str:
    """The call to action, with an Outlook (VML) fallback."""
    url, text = escape(href, quote=True), escape(label)
    return (
        '<table role="presentation" border="0" cellpadding="0" cellspacing="0" '
        'style="margin:28px auto 4px;"><tr>'
        f'<td align="center" bgcolor="{_ACCENT}" style="border-radius:12px;">'
        "<!--[if mso]>"
        f'<v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" href="{url}" '
        'style="height:48px;v-text-anchor:middle;width:280px;" arcsize="25%" '
        f'fillcolor="{_ACCENT}" stroke="f"><center style="color:{_ON_ACCENT};'
        f'font-family:{_FONT};font-size:15px;font-weight:700;">{text}</center>'
        "</v:roundrect><![endif]-->"
        "<!--[if !mso]><!-- -->"
        f'<a href="{url}" target="_blank" style="display:inline-block;padding:15px 34px;'
        f"font-family:{_FONT};font-size:15px;font-weight:700;line-height:18px;"
        f'color:{_ON_ACCENT};text-decoration:none;border-radius:12px;">{text}</a>'
        "<!--<![endif]-->"
        "</td></tr></table>"
    )


def fallback_link(*, href: str, locale: str) -> str:
    """The plain link under the button, for clients that drop it."""
    url = escape(href, quote=True)
    return (
        f'<p style="margin:20px 0 0;font-family:{_FONT};font-size:13px;line-height:20px;'
        f'color:{_MUTED};">{escape(COPY[locale]["fallback"])}</p>'
        f'<p style="margin:6px 0 0;font-family:{_FONT};font-size:13px;line-height:20px;'
        f'word-break:break-all;"><a href="{url}" target="_blank" '
        f'style="color:{_LINK};text-decoration:underline;">{url}</a></p>'
    )


def page(*, locale: str, heading: str, body_html: str, site_url: str) -> str:
    """Wrap ``body_html`` in the branded shell; ``heading`` is escaped."""
    words = COPY[locale]
    site = escape(site_url, quote=True)
    return (
        f'<!DOCTYPE html><html lang="{locale}" xmlns:v="urn:schemas-microsoft-com:vml">'
        '<head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light">'
        f"<title>{escape(heading)}</title></head>"
        f'<body style="margin:0;padding:0;background:{_PAGE_BG};">'
        '<table role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0" '
        f'bgcolor="{_PAGE_BG}" style="background:{_PAGE_BG};"><tr>'
        '<td align="center" style="padding:28px 12px;">'
        '<table role="presentation" width="520" border="0" cellpadding="0" cellspacing="0" '
        'style="width:520px;max-width:520px;">'
        f'<tr><td style="background:{_DARK};border-radius:16px 16px 0 0;padding:22px 28px;'
        f'text-align:center;"><a href="{site}" target="_blank" style="font-family:{_FONT};'
        "font-size:22px;font-weight:800;letter-spacing:-0.5px;color:#FFFFFF;"
        f'text-decoration:none;">cs<span style="color:{_ACCENT}">market</span></a></td></tr>'
        f'<tr><td style="background:{_CARD_BG};padding:34px 30px;'
        f'border-left:1px solid {_BORDER};border-right:1px solid {_BORDER};">'
        f'<h1 style="margin:0 0 12px;font-family:{_FONT};font-size:21px;line-height:28px;'
        f'font-weight:700;color:{_HEADING};">{escape(heading)}</h1>{body_html}</td></tr>'
        f'<tr><td style="background:{_DARK};border-radius:0 0 16px 16px;padding:22px 28px;'
        f'text-align:center;"><p style="margin:0;font-family:{_FONT};font-size:13px;'
        f'line-height:20px;color:#C8CDD8;">{escape(words["footer"])}</p>'
        f'<p style="margin:8px 0 0;font-family:{_FONT};font-size:12px;line-height:18px;'
        f'color:#6C7284;">{escape(words["footer.auto"])}</p></td></tr>'
        "</table></td></tr></table></body></html>"
    )
