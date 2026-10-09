/**
 * A big search that submits to the market (a GET form: works without JS) and quick chips: weapons
 * link to their indexable `/weapon/<slug>` pages, finishes to a market search.
 */
import { getTranslations } from "next-intl/server";

import { SearchIcon } from "./Icons";

import { getPathname, Link } from "@/i18n/navigation";
import { MARKET, weaponPath } from "@/lib/paths";
import { weaponSlug } from "@/lib/skin-landing";

const WEAPONS = ["AK-47", "AWP", "M4A1-S", "Desert Eagle", "Karambit", "Butterfly Knife"];
const FINISHES = ["Doppler", "Printstream"];

export async function SearchBlock({ locale }: { locale: string }) {
  const t = await getTranslations({ locale, namespace: "web.landing.search" });
  const action = getPathname({ href: MARKET, locale });
  return (
    <div className="wrap find">
      <form className="searchbar" action={action} method="get" role="search">
        <label className="sfield">
          <span className="sr">{t("label")}</span>
          <SearchIcon />
          <input
            type="search"
            name="q"
            placeholder={t("placeholder")}
            autoComplete="off"
            maxLength={80}
          />
        </label>
        <button className="btn btn-primary" type="submit">
          {t("submit")}
        </button>
      </form>
      <div className="quick">
        <small>{t("often")}</small>
        {WEAPONS.map((w) => (
          <Link key={w} className="chip" href={weaponPath(weaponSlug(w))}>
            {w}
          </Link>
        ))}
        {FINISHES.map((q) => (
          <Link key={q} className="chip" href={{ pathname: MARKET, query: { q } }}>
            {q}
          </Link>
        ))}
        <Link className="chip" href={{ pathname: MARKET, query: { max: "100000" } }}>
          {t("cheap")}
        </Link>
      </div>
    </div>
  );
}
