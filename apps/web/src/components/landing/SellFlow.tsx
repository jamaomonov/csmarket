/**
 * «Продайте скины — получите сумы»: real skins with their prices, three of them picked, the sum
 * and where it goes. An illustration of the sell page — it is not a quote.
 */
import { formatUzs, type SkinItem, steamImageSize } from "@csmarket/utils/skins";
import Image from "next/image";
import { getTranslations } from "next-intl/server";

import { cx, rarityVar } from "./format";
import { ArrowIcon, CheckIcon, WalletIcon } from "./Icons";

import { Link } from "@/i18n/navigation";
import { SELL } from "@/lib/paths";

const SHOWN = 6;
const STAR = new Set(["knives", "gloves"]);
const PICKED = 3;
const CARDS = [
  { src: "/payout/uzcard.png", alt: "Uzcard", w: 35 },
  { src: "/payout/humo.png", alt: "Humo", w: 37 },
  { src: "/payout/uzum-visa.png", alt: "Uzum Visa", w: 35 },
] as const;

export async function SellFlow({ items, locale }: { items: SkinItem[]; locale: string }) {
  const t = await getTranslations({ locale, namespace: "web.landing.sellPanel" });
  const priced = items.filter((i) => i.image_url !== null && i.price_uzs !== null);
  // Everyday skins read as a believable sale; knives and gloves only fill a short list.
  const everyday = priced.filter((i) => !STAR.has(i.category));
  const inv = (everyday.length >= SHOWN ? everyday : priced).slice(0, SHOWN);
  const total = inv.slice(0, PICKED).reduce((sum, i) => sum + Number(i.price_uzs), 0);
  return (
    <article className="panel panel-sell rv" aria-labelledby="lp-sell">
      <div className="kicker" style={{ color: "var(--info)" }}>
        {t("kicker")}
      </div>
      <h3 id="lp-sell">{t("title")}</h3>
      <p className="pl">{t("lead")}</p>
      {inv.length >= PICKED && (
        <div className="sell-demo" aria-hidden>
          <div className="sv-grid">
            {inv.map((it, i) => (
              <div
                key={it.slug}
                className={cx("sv", i < PICKED && "on")}
                style={rarityVar(it.rarity_color)}
              >
                <span className="sv-ck">
                  <CheckIcon />
                </span>
                <Image
                  src={steamImageSize(it.image_url ?? "", "128fx96f")}
                  alt=""
                  width={112}
                  height={84}
                  unoptimized
                  loading="lazy"
                />
                <span className="sv-n">{it.weapon ?? it.name}</span>
                <span className="sv-p num">{formatUzs(locale, it.price_uzs ?? "0")}</span>
              </div>
            ))}
          </div>
          <div className="sv-sum">
            <div className="sv-total">
              <span>{t("chosen", { count: PICKED })}</span>
              <b className="num">{formatUzs(locale, total)}</b>
            </div>
            <div className="sv-to">
              <span className="sv-to-l">{t("where")}</span>
              <div className="sv-opts">
                <span className="sv-opt sv-bal">
                  <WalletIcon />
                  {t("toBalance")}
                </span>
                {CARDS.map((c, i) => (
                  <span key={c.alt} className={cx("sv-opt", i === 0 && "on")}>
                    <Image src={c.src} alt={c.alt} width={c.w} height={22} />
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
      <p className="sv-hint">{t("picked")}</p>
      <Link className="btn btn-sell" href={SELL}>
        {t("cta")}
        <ArrowIcon />
      </Link>
    </article>
  );
}
