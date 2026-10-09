/** Stroke icons of the landing (24×24, `currentColor`); decorative unless labelled. */
import type { ReactNode, SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function Svg({ children, ...rest }: IconProps & { children: ReactNode }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden {...rest}>
      {children}
    </svg>
  );
}

export const ArrowIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </Svg>
);
export const SearchIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="11" cy="11" r="7" />
    <path d="M20 20l-3.5-3.5" />
  </Svg>
);
export const CartIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 6h15l-1.5 9h-12zM6 6L5 3H2M9 20h.01M18 20h.01" />
  </Svg>
);
export const WalletIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 7h15a3 3 0 013 3v8a2 2 0 01-2 2H5a2 2 0 01-2-2zM3 7l12-4v4M17 14h.01" />
  </Svg>
);
export const CheckIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </Svg>
);
export const ShieldIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z" />
    <path d="M8.5 12l2.5 2.5 4.5-5" />
  </Svg>
);
export const PlusIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 5v14M5 12h14" />
  </Svg>
);
export const CardIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="2.5" y="5" width="19" height="14" rx="2.5" />
    <path d="M2.5 10h19M6.5 15h4" />
  </Svg>
);
export const BanIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M5.6 5.6l12.8 12.8" />
  </Svg>
);
export const RefundIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 12a9 9 0 109-9 9.7 9.7 0 00-6.7 2.8L3 8" />
    <path d="M3 3v5h5M12 8v4l3 2" />
  </Svg>
);
export const ChatIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M21 12a8 8 0 01-11.6 7.1L4 20.5l1.4-4.9A8 8 0 1121 12z" />
    <path d="M8.5 11h.01M12 11h.01M15.5 11h.01" />
  </Svg>
);
/** Filled glyphs (no stroke). */
export const SteamGlyph = (p: IconProps) => (
  <svg viewBox="0 0 24 24" aria-hidden className="steam-ic" {...p}>
    <path d="M12 2a10 10 0 00-9.96 9.1l5.36 2.22a2.8 2.8 0 011.6-.5h.16l2.38-3.46v-.05a3.77 3.77 0 113.77 3.77h-.09l-3.4 2.43v.13a2.83 2.83 0 01-5.6.56L2.4 14.6A10 10 0 1012 2z" />
  </svg>
);
export const TelegramGlyph = (p: IconProps) => (
  <svg viewBox="0 0 24 24" aria-hidden {...p}>
    <path d="M21.6 4.2L2.9 11.4c-1.3.5-1.3 1.2-.2 1.6l4.8 1.5 1.8 5.6c.2.6.4.8.9.8.4 0 .6-.2.9-.4l2.2-2.1 4.6 3.4c.8.5 1.4.2 1.6-.8l3-14.3c.3-1.3-.5-1.8-1.3-1.5zM8.4 14.2l9.3-5.9c.4-.3.8-.1.5.2l-7.6 6.9-.3 3.4z" />
  </svg>
);
