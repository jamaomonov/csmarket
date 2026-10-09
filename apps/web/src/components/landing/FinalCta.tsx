/** The green closing call to action with a few real skins. */
import { type SkinItem, steamImageSize } from "@csmarket/utils/skins";
import Image from "next/image";
import { getTranslations } from "next-intl/server";

import { ArrowIcon } from "./Icons";

import { Link } from "@/i18n/navigation";
import { MARKET } from "@/lib/paths";

export async function FinalCta({ items, locale }: { items: SkinItem[]; locale: string }) {
  const t = await getTranslations({ locale, namespace: "web.landing.final" });
  const pics = items.filter((i) => i.image_url !== null).slice(0, 3);
  return (
    <div className="wrap">
      <div className="final rv">
        <div>
          <h2>{t("title")}</h2>
          <p>{t("text")}</p>
        </div>
        <div className="final-imgs" aria-hidden>
          {pics.map((p) => (
            <Image
              key={p.slug}
              src={steamImageSize(p.image_url ?? "", "256fx192f")}
              alt=""
              width={150}
              height={112}
              unoptimized
              loading="lazy"
            />
          ))}
        </div>
        <Link className="btn" href={MARKET}>
          {t("cta")}
          <ArrowIcon />
        </Link>
      </div>
    </div>
  );
}
