import Link from "next/link";
import { getTranslations } from "next-intl/server";

export default async function NotFound() {
  const t = await getTranslations("web.notFound");
  const common = await getTranslations("common");
  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col items-center justify-center px-6 text-center">
      <p className="text-accent font-mono text-6xl font-bold">404</p>
      <h1 className="mt-4 text-2xl font-bold">{t("title")}</h1>
      <p className="text-fg-muted mt-3">{t("subtitle")}</p>
      <Link href="/" className="bg-accent text-accent-fg mt-8 rounded-md px-5 py-3 font-semibold">
        {common("actions.home")}
      </Link>
    </main>
  );
}
