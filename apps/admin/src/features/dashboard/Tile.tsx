/**
 * A dashboard tile: a title over a figure; optionally a link and a red edge. A tile that opens a
 * page looks like a link (admin UX audit §8): a chevron by its title and a hover.
 */
import { ChevronRight } from "lucide-react";
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
      <div className="text-fg-muted flex items-center justify-between gap-2 text-sm font-normal">
        <span>{title}</span>
        {to !== undefined && (
          <ChevronRight
            aria-hidden
            data-testid="tile-chevron"
            className="text-fg-dim group-hover:text-accent size-4 shrink-0 transition-colors"
          />
        )}
      </div>
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
        <Link
          to={to}
          className={`${cls} hover:bg-surface-hover hover:border-border-strong group transition-colors`}
        >
          {body}
        </Link>
      )}
    </div>
  );
}
