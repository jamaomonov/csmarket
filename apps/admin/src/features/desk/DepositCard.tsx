/** One Skinslink deposit of a deal: its state, the bot that sends the offer, why it failed. */
import { type DeskDeposit } from "./api";
import { DEPOSIT_STATUS } from "./labels";

import { Money } from "@/components/Money";
import { reasonText } from "@/lib/dictionary";

/** Skinslink's statuses while the offer is still on its way or with the trader. */
export const OPEN_DEPOSIT = new Set(["creating", "new", "pending", "active"]);

const PROFILE = "https://steamcommunity.com/profiles/";

function Bot({ deposit: x }: { deposit: DeskDeposit }) {
  const name = x.bot_persona ?? x.bot_name;
  if (name === null) return null;
  const face = (
    <>
      {x.bot_avatar_url && (
        <img
          src={x.bot_avatar_url}
          alt=""
          width={24}
          height={24}
          className="size-6 rounded-full"
          loading="lazy"
        />
      )}
      <span>Бот: {name}</span>
    </>
  );
  return x.bot_steam_id ? (
    <a
      href={`${PROFILE}${x.bot_steam_id}`}
      target="_blank"
      rel="noreferrer"
      className="text-fg inline-flex items-center gap-2 underline-offset-2 hover:underline"
    >
      {face}
    </a>
  ) : (
    <p className="inline-flex items-center gap-2">{face}</p>
  );
}

export function DepositCard({ deposit: x }: { deposit: DeskDeposit }) {
  const failed = x.status === "failed" || x.status === "canceled";
  return (
    <div className="border-border space-y-1 rounded-lg border p-3 text-sm">
      {failed ? (
        <p className="text-danger font-medium">
          {x.fail_reason
            ? `Skinslink отклонил обмен: ${reasonText("market", x.fail_reason)}`
            : "Skinslink отклонил обмен"}
        </p>
      ) : (
        <p className="font-medium">Обмен Skinslink: {DEPOSIT_STATUS[x.status] ?? x.status}</p>
      )}
      <Bot deposit={x} />
      <p className="text-fg-muted">
        {x.trade_offer_id && <>обмен №{x.trade_offer_id}</>}
        {x.trade_offer_id && x.amount_usd && " · "}
        {x.amount_usd &&
          (x.amount_estimated ? (
            <>
              примерно <Money usd={x.amount_usd} /> — точная сумма в кабинете Skinslink
            </>
          ) : (
            <>
              Skinslink: <Money usd={x.amount_usd} />
            </>
          ))}
        {!failed && x.fail_reason && <> · причина: {reasonText("market", x.fail_reason)}</>}
      </p>
    </div>
  );
}
