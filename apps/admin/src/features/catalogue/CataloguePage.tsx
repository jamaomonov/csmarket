/** «Каталог»: job and rate status, find and hide an item, search aliases. */
import { AliasesCard } from "./AliasesCard";
import { ItemsCard } from "./ItemsCard";
import { StatusCard } from "./StatusCard";

export function CataloguePage() {
  return (
    <section className="space-y-6">
      <h1 className="text-2xl font-bold">Каталог</h1>
      <StatusCard />
      <ItemsCard />
      <AliasesCard />
    </section>
  );
}
