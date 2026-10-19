/**
 * The inventory while it loads: the loaded page's own layout — toolbar, the total line, item
 * cards, the cart beside them — drawn empty and pulsing, so nothing jumps when it arrives.
 */
import { useTranslations } from "next-intl";

const CARDS = 8;

function Bar({ className }: { className: string }) {
  return <span aria-hidden className={`bg-surface-2 block rounded ${className}`} />;
}

function CardSkeleton() {
  return (
    <div
      data-skeleton-card
      className="bg-surface border-border flex flex-col overflow-hidden rounded-lg border"
    >
      <span className="bg-surface-2/60 relative block aspect-[4/3] w-full">
        <span className="absolute inset-x-2.5 top-2.5 flex items-center gap-1">
          <Bar className="h-4 w-8" />
          <span aria-hidden className="border-border-strong ml-auto size-5 rounded-md border" />
        </span>
      </span>
      <span className="border-border flex flex-col gap-1.5 border-t px-3 pb-3 pt-2.5">
        <Bar className="h-3 w-1/3" />
        <Bar className="h-4 w-3/4" />
        <Bar className="mt-2 h-5 w-1/2" />
      </span>
    </div>
  );
}

export function SellSkeleton() {
  const t = useTranslations("web.sell");
  return (
    <div
      role="status"
      aria-busy="true"
      aria-label={t("loading")}
      className="grid animate-pulse grid-cols-1 items-start gap-5 lg:grid-cols-[minmax(0,1fr)_380px]"
    >
      <div className="flex min-w-0 flex-col gap-4">
        <div className="flex flex-col gap-2 sm:flex-row">
          <Bar className="h-10 flex-1 rounded-lg" />
          <div className="flex gap-2">
            <Bar className="h-10 flex-1 rounded-lg sm:w-52 sm:flex-none" />
            <Bar className="h-10 w-28 rounded-lg" />
            <Bar className="size-10 rounded-lg" />
          </div>
        </div>
        <Bar className="h-4 w-56" />
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: CARDS }, (_, i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      </div>
      <div
        data-skeleton-cart
        className="bg-surface border-border hidden flex-col gap-5 rounded-xl border p-5 lg:flex"
      >
        <Bar className="h-5 w-1/2" />
        <Bar className="h-16 w-full rounded-lg" />
        <div className="flex flex-col gap-2">
          <Bar className="h-4 w-full" />
          <Bar className="h-4 w-2/3" />
        </div>
        <Bar className="h-11 w-full rounded-lg" />
      </div>
    </div>
  );
}
