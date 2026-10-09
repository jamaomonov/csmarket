/** A page's title row: back link, title, a muted meta line and actions (review §4.5). */
import { type ReactNode } from "react";
import { Link } from "react-router-dom";

interface PageHeaderProps {
  title: ReactNode;
  meta?: ReactNode;
  back?: { to: string; label: string };
  actions?: ReactNode;
  /** Chips beside the title (a status, «внимание»). */
  badges?: ReactNode;
}

export function PageHeader({ title, meta, back, actions, badges }: PageHeaderProps) {
  return (
    <header className="space-y-1">
      {back !== undefined && (
        <Link to={back.to} className="text-fg-muted hover:text-fg text-sm">
          ← {back.label}
        </Link>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <h1 className="truncate text-[22px] font-semibold leading-tight">{title}</h1>
          {badges}
        </div>
        {actions !== undefined && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
      {meta !== undefined && <p className="text-fg-muted text-sm">{meta}</p>}
    </header>
  );
}
