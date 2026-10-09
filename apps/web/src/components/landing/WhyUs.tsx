/** «Сделано для игроков из Узбекистана»: four guarantees and, once set, the Telegram link. */
import { getTranslations } from "next-intl/server";

import { BanIcon, CardIcon, ChatIcon, RefundIcon, TelegramGlyph } from "./Icons";

import type { ReactNode } from "react";

import { telegramUrl } from "@/lib/landing";

const CARDS: { key: "g1" | "g2" | "g3" | "g4"; icon: ReactNode; tint: string }[] = [
  { key: "g1", icon: <CardIcon />, tint: "93 178 255" },
  { key: "g2", icon: <BanIcon />, tint: "245 184 61" },
  { key: "g3", icon: <RefundIcon />, tint: "47 191 113" },
  { key: "g4", icon: <ChatIcon />, tint: "42 171 238" },
];

export async function WhyUs({ locale }: { locale: string }) {
  const tg = telegramUrl();
  const t = await getTranslations({ locale, namespace: "web.landing.why" });
  return (
    <section aria-labelledby="lp-why">
      <div className="wrap why">
        <div>
          <div className="kicker">{t("kicker")}</div>
          <h2 id="lp-why">{t("title")}</h2>
          <p className="sec-lead">{t("lead")}</p>
          {tg !== "" && (
            <a className="tg" href={tg} rel="noopener noreferrer" target="_blank">
              <TelegramGlyph />
              {t("telegram")}
            </a>
          )}
        </div>
        <div className="why-cards">
          {CARDS.map((c) => (
            <div key={c.key} className="g rv">
              <span
                className="g-ic"
                style={{ background: `rgb(${c.tint} / .14)`, color: `rgb(${c.tint})` }}
              >
                {c.icon}
              </span>
              <h3>{t(c.key)}</h3>
              <p>{t(`${c.key}d`)}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
