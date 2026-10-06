import { permanentRedirect } from "@/i18n/navigation";
import { TRADES } from "@/lib/paths";

/** «Мои заказы» moved to «Обмены» (old links in letters and bookmarks keep working). */
export default async function Page({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  permanentRedirect({ href: TRADES, locale });
}
