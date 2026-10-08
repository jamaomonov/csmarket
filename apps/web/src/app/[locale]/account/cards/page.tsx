import { permanentRedirect } from "@/i18n/navigation";
import { ACCOUNT } from "@/lib/paths";

/** «Мои карты» moved into the profile (old links and bookmarks keep working). */
export default async function Page({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  permanentRedirect({ href: ACCOUNT, locale });
}
