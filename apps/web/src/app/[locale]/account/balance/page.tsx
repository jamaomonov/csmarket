import { permanentRedirect } from "@/i18n/navigation";
import { TRANSACTIONS } from "@/lib/paths";

/** The balance page moved to «Транзакции» (old links in letters and bookmarks keep working). */
export default async function Page({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  permanentRedirect({ href: TRANSACTIONS, locale });
}
