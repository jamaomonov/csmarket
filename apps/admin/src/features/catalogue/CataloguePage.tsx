/** «Каталог»: job and rate status, find and hide an item, search aliases. */
import { AliasesCard } from "./AliasesCard";
import { ItemsCard } from "./ItemsCard";
import { StatusCard } from "./StatusCard";

import { PageHeader } from "@/components/PageHeader";

export function CataloguePage() {
  return (
    <section className="space-y-6">
      <PageHeader title="Каталог" />
      <StatusCard />
      <ItemsCard />
      <AliasesCard />
    </section>
  );
}
