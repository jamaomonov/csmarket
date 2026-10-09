/** Buy in three steps and sell for soʻm, side by side. The sell cards are illustrative, without sums. */
import { type SkinItem, steamImageSize } from "@csmarket/utils/skins";
import Image from "next/image";
import { getTranslations } from "next-intl/server";

import { cx, rarityVar } from "./format";
import { ArrowIcon, CheckIcon, ShieldIcon, WalletIcon } from "./Icons";
import { PayMarks } from "./Wordmarks";

import type { ReactNode } from "react";

import { Link } from "@/i18n/navigation";
import { MARKET, SELL } from "@/lib/paths";

function Step({
  n,
  title,
  text,
  tail,
}: {
  n: number;
  title: string;
  text: string;
  tail: ReactNode;
}) {
  return (
    <li>
      <span className="n">{n}</span>
      <div className="tx">
        <b>{title}</b>
        <span>{text}</span>
      </div>
      <div className="tail">{tail}</div>
    </li>
  );
}

export async function BuySell({ samples, locale }: { samples: SkinItem[]; locale: string }) {
  const t = await getTranslations({ locale, namespace: "web.landing" });
  const step = samples[0];
  const inv = samples.slice(0, 6);
  return (
    <section aria-label={`${t("buyPanel.kicker")} · ${t("sellPanel.kicker")}`}>
      <div className="wrap duo">
        <article className="panel panel-buy rv" aria-labelledby="lp-buy">
          <div className="kicker">{t("buyPanel.kicker")}</div>
          <h3 id="lp-buy">{t("buyPanel.title")}</h3>
          <p className="pl">{t("buyPanel.lead")}</p>
          <ol className="steps">
            <Step
              n={1}
              title={t("buyPanel.s1")}
              text={t("buyPanel.s1d")}
              tail={
                step?.image_url ? (
                  <Image
                    className="mini-thumb"
                    src={steamImageSize(step.image_url, "128fx96f")}
                    alt=""
                    width={72}
                    height={44}
                    unoptimized
                    loading="lazy"
                  />
                ) : null
              }
            />
            <Step n={2} title={t("buyPanel.s2")} text={t("buyPanel.s2d")} tail={<PayMarks />} />
            <Step
              n={3}
              title={t("buyPanel.s3")}
              text={t("buyPanel.s3d")}
              tail={
                <span className="offer">
                  {t("buyPanel.offer")} <em>{t("buyPanel.accept")}</em>
                </span>
              }
            />
          </ol>
          <div className="buy-foot">
            <Link className="btn btn-primary" href={MARKET}>
              {t("buyPanel.go")}
              <ArrowIcon />
            </Link>
            <span className="assure">
              <ShieldIcon />
              {t("buyPanel.assure")}
            </span>
          </div>
        </article>

        <article className="panel panel-sell rv" aria-labelledby="lp-sell">
          <div className="kicker" style={{ color: "var(--info)" }}>
            {t("sellPanel.kicker")}
          </div>
          <h3 id="lp-sell">{t("sellPanel.title")}</h3>
          <p className="pl">{t("sellPanel.lead")}</p>
          {inv.length > 0 && (
            <div className="invgrid" aria-hidden>
              {inv.map((it, i) => (
                <div
                  key={it.slug}
                  className={cx("inv", i < 3 && "on")}
                  style={rarityVar(it.rarity_color)}
                >
                  <span className="ck">
                    <CheckIcon />
                  </span>
                  {it.image_url && (
                    <Image
                      src={steamImageSize(it.image_url, "128fx96f")}
                      alt=""
                      width={96}
                      height={72}
                      unoptimized
                      loading="lazy"
                    />
                  )}
                  <span>{it.exterior ?? it.weapon ?? ""}</span>
                </div>
              ))}
            </div>
          )}
          <div className="sumrow">
            <div className="lbl">{t("sellPanel.picked")}</div>
            <div className="payouts" aria-label={t("sellPanel.where")}>
              <span className="bal">
                <WalletIcon />
                {t("sellPanel.toBalance")}
              </span>
              <span className="po">
                <Image src="/payout/uzcard.png" alt="Uzcard" width={35} height={22} />
              </span>
              <span className="po">
                <Image src="/payout/humo.png" alt="Humo" width={37} height={22} />
              </span>
            </div>
          </div>
          <Link className="btn btn-sell" href={SELL}>
            {t("sellPanel.cta")}
            <ArrowIcon />
          </Link>
        </article>
      </div>
    </section>
  );
}
