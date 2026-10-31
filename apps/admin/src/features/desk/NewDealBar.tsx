/** The new deal's sum, pinned to the bottom: «Заплачено $X · Skinslink $Y · +$Z» and «Сохранить». */
import { Button } from "@csmarket/ui";

import { TAP } from "./Parts";

import { Money } from "@/components/Money";

interface NewDealBarProps {
  /** `null` while the price is not given (or cannot be told). */
  paidUsd: number | null;
  skinslinkUsd: number;
  ready: boolean;
  busy: boolean;
  onSave: () => void;
}

export function NewDealBar({ paidUsd, skinslinkUsd, ready, busy, onSave }: NewDealBarProps) {
  return (
    <div
      role="region"
      aria-label="Итог сделки"
      className="border-border bg-bg/95 bottom-(--bottom-nav) fixed inset-x-0 z-30 border-t px-4 py-3 backdrop-blur md:px-6 lg:bottom-0"
    >
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-3 gap-y-2">
        <p className="text-sm">
          {paidUsd !== null && (
            <>
              Заплачено <Money usd={paidUsd.toFixed(2)} /> ·{" "}
            </>
          )}
          Skinslink <Money usd={skinslinkUsd.toFixed(2)} />
          {paidUsd !== null && skinslinkUsd > 0 && (
            <>
              {" "}
              · <Money usd={(skinslinkUsd - paidUsd).toFixed(2)} signed />
            </>
          )}
        </p>
        <Button className={`ml-auto ${TAP}`} disabled={!ready || busy} onClick={onSave}>
          {busy ? "Сохраняем…" : "Сохранить сделку"}
        </Button>
      </div>
    </div>
  );
}
