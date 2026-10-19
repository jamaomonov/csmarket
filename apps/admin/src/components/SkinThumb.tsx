/** A skin's picture in a list row (or a grey box when it has none). */
import { steamImageSize } from "@csmarket/utils/skins";

export function SkinThumb({ url }: { url: string | null | undefined }) {
  return url ? (
    <img
      src={steamImageSize(url, "128fx96f")}
      alt=""
      width={48}
      height={36}
      loading="lazy"
      className="bg-surface-2 h-9 w-12 shrink-0 rounded object-contain"
    />
  ) : (
    <div className="bg-surface-2 h-9 w-12 shrink-0 rounded" aria-hidden="true" />
  );
}
