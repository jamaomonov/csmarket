import { steamImageSize } from "@csmarket/utils/skins";
import Image from "next/image";

import type { OrderOut } from "@/lib/orders";

import { Link } from "@/i18n/navigation";
import { itemPath } from "@/lib/paths";

interface OrderItemProps {
  order: Pick<OrderOut, "slug" | "name" | "phase" | "image_url">;
  /** The price, formatted. */
  price: string;
  /** Link the name to the item page (the order page); a list card is a link itself. */
  linked?: boolean;
}

/** The skin an order is for: art, name (English), phase and the price paid. */
export function OrderItem({ order, price, linked = true }: OrderItemProps) {
  return (
    <div className="flex w-full items-center gap-4">
      <div className="bg-surface-2 relative h-16 w-20 shrink-0 overflow-hidden rounded-md">
        {order.image_url ? (
          <Image
            src={steamImageSize(order.image_url, "128fx96f")}
            alt=""
            fill
            // A Steam CDN image already cut to size: the optimizer adds nothing.
            unoptimized
            sizes="80px"
            className="object-contain p-1"
          />
        ) : null}
      </div>
      <div className="min-w-0 flex-1">
        <p className="font-semibold leading-snug">
          {linked ? (
            <Link href={itemPath(order.slug)} className="hover:underline">
              {order.name}
            </Link>
          ) : (
            order.name
          )}
        </p>
        {order.phase ? <p className="text-fg-dim text-sm">{order.phase}</p> : null}
      </div>
      <p className="shrink-0 font-bold tabular-nums">{price}</p>
    </div>
  );
}
