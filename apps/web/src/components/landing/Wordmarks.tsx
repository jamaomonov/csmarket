/** Click / Payme / Uzum: the providers' own logos (`public/pay/`) on white plates. */
import Image from "next/image";

import { cx } from "./format";

export type PayKey = "click" | "payme" | "uzum";

/** Each logo's file and its width at 20 px high, so the plates line up. */
export const PAY_LOGOS: Readonly<Record<PayKey, { src: string; w: number; name: string }>> = {
  click: { src: "/pay/click.svg", w: 78, name: "Click" },
  payme: { src: "/pay/payme.png", w: 51, name: "Payme" },
  uzum: { src: "/pay/uzum.png", w: 68, name: "Uzum" },
};
const KEYS: PayKey[] = ["click", "payme", "uzum"];

export function PayLogo({ k, on = false }: { k: PayKey; on?: boolean }) {
  const logo = PAY_LOGOS[k];
  return (
    <span className={cx("pay-logo", on && "on")}>
      <Image src={logo.src} alt={logo.name} width={logo.w} height={20} unoptimized />
    </span>
  );
}

export function PayMarks() {
  return (
    <>
      {KEYS.map((k) => (
        <PayLogo key={k} k={k} />
      ))}
    </>
  );
}
