import { cn } from "../../lib/cn";

import type { ReactNode } from "react";


interface PanelProps {
  as?: "div" | "section" | "aside";
  className?: string;
  children: ReactNode;
}

/** The surface container: filter sidebar, toolbar, cards of content. */
export function Panel({ as: Tag = "div", className, children }: PanelProps) {
  return <Tag className={cn("bg-surface rounded-xl p-4", className)}>{children}</Tag>;
}
