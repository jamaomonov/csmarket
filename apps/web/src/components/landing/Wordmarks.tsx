/** Click / Payme / Uzum: the providers' square app icons (`public/pay/`) with their names. */
import Image from "next/image";

import { cx } from "./format";

export type PayKey = "click" | "payme" | "uzum";

export const PAY_LOGOS: Readonly<Record<PayKey, { src: string; name: string }>> = {
  click: { src: "/pay/click.png", name: "Click" },
  payme: { src: "/pay/payme.png", name: "Payme" },
  uzum: { src: "/pay/uzum.png", name: "Uzum" },
};
const KEYS: PayKey[] = ["click", "payme", "uzum"];

export function PayLogo({ k, on = false }: { k: PayKey; on?: boolean }) {
  const logo = PAY_LOGOS[k];
  return (
    <span className={cx("pay-logo", on && "on")}>
      <Image src={logo.src} alt="" width={24} height={24} unoptimized />
      {logo.name}
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
