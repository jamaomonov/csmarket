import Image from "next/image";

interface StickerImageProps {
  /** A Steam CDN image URL (the API keeps only those). */
  src: string;
  name: string;
  /** Rendered box, CSS pixels. */
  size: number;
  className?: string;
}

/**
 * A sticker or charm thumbnail served through our own image endpoint (`/_next/image`),
 * which fetches it from Steam once and caches it. Steam's CDN nodes sometimes fail an
 * uncached file (503 "Backend unavailable"); the buyer never sees that.
 */
export function StickerImage({ src, name, size, className }: StickerImageProps) {
  return (
    <Image
      src={src}
      alt={name}
      title={name}
      width={size}
      height={Math.round((size * 3) / 4)}
      loading="lazy"
      {...(className === undefined ? {} : { className })}
    />
  );
}
