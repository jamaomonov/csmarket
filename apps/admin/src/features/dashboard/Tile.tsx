/** A dashboard tile: a title over a figure; optionally a link and a red edge. */
import { type ReactNode } from "react";
import { Link } from "react-router-dom";

interface TileProps {
  title: string;
  children: ReactNode;
  /** The whole tile opens this page. */
  to?: string;
  /** Something waits for an operator: a red edge. */
  alert?: boolean;
}

export function Tile({ title, children, to, alert = false }: TileProps) {
  const body = (
    <>
      <div className="text-fg-muted text-sm font-normal">{title}</div>
      <div className="mt-1 flex flex-col gap-0.5 text-lg font-semibold tabular-nums">
        {children}
      </div>
    </>
  );
  const cls = `border-border bg-surface block h-full rounded-lg border p-4 ${
    alert ? "shadow-[inset_3px_0_0_var(--color-danger)]" : ""
  }`;
  return (
    <div data-testid={`tile-${title}`} className="h-full">
      {to === undefined ? (
        <div className={cls}>{body}</div>
      ) : (
        <Link to={to} className={`${cls} hover:bg-surface-hover`}>
          {body}
        </Link>
      )}
    </div>
  );
}
