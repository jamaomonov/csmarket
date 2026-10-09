/** «Купить скин — три шага», shown on one real skin: picked, paid with Click, the Steam offer. */
import { formatUzs, isVanilla, type SkinItem, steamImageSize } from "@csmarket/utils/skins";
import Image from "next/image";
import { getTranslations } from "next-intl/server";

import { rarityVar } from "./format";
import { ArrowIcon, CheckIcon, ShieldIcon, SteamGlyph } from "./Icons";
import { PayLogo } from "./Wordmarks";

import type { ReactNode } from "react";

import { Link } from "@/i18n/navigation";
import { MARKET } from "@/lib/paths";

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <li className="fl-step">
      <span className="fl-n">{n}</span>
      <div className="fl-body">
        <b className="fl-t">{title}</b>
        {children}
      </div>
    </li>
  );
}

export async function BuyFlow({ item, locale }: { item: SkinItem | null; locale: string }) {
  const t = await getTranslations({ locale, namespace: "web.landing.buyPanel" });
  const tSkins = await getTranslations({ locale, namespace: "web.skins" });
  const price = item?.price_uzs ? formatUzs(locale, item.price_uzs) : null;
  const name = item === null ? "" : isVanilla(item) ? tSkins("vanilla") : (item.skin ?? item.name);
  const pic = item?.image_url ? steamImageSize(item.image_url, "256fx192f") : null;
  return (
    <article className="panel panel-buy rv" aria-labelledby="lp-buy">
      <div className="kicker">{t("kicker")}</div>
      <h3 id="lp-buy">{t("title")}</h3>
      <p className="pl">{t("lead")}</p>
      {item !== null && (
        <ol className="flow" aria-label={t("title")}>
          <Step n={1} title={t("s1")}>
            <div className="fl-skin" style={rarityVar(item.rarity_color)}>
              {pic !== null && (
                <Image src={pic} alt="" width={112} height={84} unoptimized loading="lazy" />
              )}
              <div className="fl-skin-tx">
                <span className="fl-m">
                  {item.exterior !== null && <em>{item.exterior}</em>}
                  {item.weapon ?? item.name}
                </span>
                <b>
                  {name}
                  {item.phase !== null && <> · {item.phase}</>}
                </b>
                {price !== null && <span className="num fl-price">{price}</span>}
              </div>
              <span className="fl-pick">
                <CheckIcon />
                {t("picked")}
              </span>
            </div>
          </Step>
          <Step n={2} title={t("s2")}>
            <div className="fl-pay">
              <div className="fl-logos">
                <PayLogo k="click" on />
                <PayLogo k="payme" />
                <PayLogo k="uzum" />
              </div>
              {price !== null && (
                <div className="fl-due">
                  <span>{t("toPay")}</span>
                  <b className="num">{price}</b>
                </div>
              )}
            </div>
          </Step>
          <Step n={3} title={t("s3")}>
            <div className="fl-offer">
              <div className="fl-offer-h">
                <SteamGlyph />
                {t("offer")}
              </div>
              <div className="fl-offer-b">
                {pic !== null && (
                  <span className="fl-offer-img" style={rarityVar(item.rarity_color)}>
                    <Image src={pic} alt="" width={64} height={48} unoptimized loading="lazy" />
                  </span>
                )}
                <span className="fl-offer-tx">
                  <span>{t("youGet")}</span>
                  <b>{item.name}</b>
                </span>
                <span className="fl-accept">{t("accept")}</span>
              </div>
            </div>
          </Step>
        </ol>
      )}
      <div className="buy-foot">
        <Link className="btn btn-primary" href={MARKET}>
          {t("go")}
          <ArrowIcon />
        </Link>
        <span className="assure">
          <ShieldIcon />
          {t("assure")}
        </span>
      </div>
    </article>
  );
}
