/**
 * csmarket's Telegram, split by purpose (owner 2026-10-20): the channel for news and deals,
 * the community chat, and support. Public handles, so they live here rather than in an env
 * file a deploy could leave empty.
 */
export const TELEGRAM = {
  channel: "https://t.me/cs2marketuz",
  chat: "https://t.me/csmarketuz_chat",
  support: "https://t.me/jama_omonov",
} as const;

/** The footer's Telegram column, in reading order, with its copy key under `web.landing.footer`. */
export const TELEGRAM_LINKS = [
  { href: TELEGRAM.channel, key: "tgChannel" },
  { href: TELEGRAM.chat, key: "tgChat" },
  { href: TELEGRAM.support, key: "tgSupport" },
] as const;
