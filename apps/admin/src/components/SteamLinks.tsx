/** A buyer's trade link and a Steam trade offer, whole, as links an admin opens or copies. */
import { CopyButton } from "./CopyButton";

/** The trade link as saved; an erased one (masked text) is shown as text, not a link. */
export function TradeLinkValue({ link }: { link: string | null }) {
  if (link === null) return <>не указана</>;
  const whole = link.startsWith("https://") && !link.includes("•");
  return (
    <span className="break-all">
      {whole ? (
        <a href={link} target="_blank" rel="noreferrer" className="text-accent hover:underline">
          {link}
        </a>
      ) : (
        link
      )}
      <CopyButton value={link} label="Скопировать трейд-ссылку" />
    </span>
  );
}

export function steamOfferUrl(offerId: string): string {
  return `https://steamcommunity.com/tradeoffer/${encodeURIComponent(offerId)}/`;
}

/** A Steam trade offer id as a link to the offer, with its URL to copy. */
export function SteamOfferValue({ offerId }: { offerId: string | null }) {
  if (offerId === null) return <>—</>;
  const url = steamOfferUrl(offerId);
  return (
    <span className="break-all">
      <a href={url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
        {url}
      </a>
      <CopyButton value={url} label="Скопировать ссылку на оффер" />
    </span>
  );
}
