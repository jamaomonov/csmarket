/**
 * A skin's picture in a list row. Without a picture — none saved, or one that fails to load — a
 * grey box with a muted skin glyph, so a row never reads as a broken image.
 */
import { steamImageSize } from "@csmarket/utils/skins";
import { ImageOff } from "lucide-react";
import { useState } from "react";

export function SkinThumb({ url }: { url: string | null | undefined }) {
  const [failed, setFailed] = useState<string | null>(null);
  if (url && failed !== url) {
    return (
      <img
        src={steamImageSize(url, "128fx96f")}
        alt=""
        width={48}
        height={36}
        loading="lazy"
        onError={() => {
          setFailed(url);
        }}
        className="bg-surface-2 h-9 w-12 shrink-0 rounded object-contain"
      />
    );
  }
  return (
    <div
      data-testid="skin-thumb-empty"
      aria-hidden="true"
      className="bg-surface-2 text-fg-dim grid h-9 w-12 shrink-0 place-items-center rounded"
    >
      <ImageOff className="size-4" />
    </div>
  );
}
