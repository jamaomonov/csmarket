/** A user in a table: avatar (or an initial), a linked name and a muted second line (§4.4). */
import { type ReactNode } from "react";
import { Link } from "react-router-dom";

import { LINK } from "./TextLink";

interface UserCellProps {
  id: string;
  name: string | null;
  avatarUrl?: string | null | undefined;
  sub?: ReactNode;
  /** Chips and icons beside the name (a role chip on an admin, an API key icon). */
  badges?: ReactNode;
}

export function UserCell({ id, name, avatarUrl, sub, badges }: UserCellProps) {
  const shown = name !== null && name !== "" ? name : "Без имени";
  return (
    <div className="flex min-w-0 items-center gap-2">
      {avatarUrl !== undefined && avatarUrl !== null && avatarUrl !== "" ? (
        <img src={avatarUrl} alt="" className="size-6 shrink-0 rounded-full" loading="lazy" />
      ) : (
        <span
          aria-hidden
          className="bg-surface-2 text-fg-muted text-meta grid size-6 shrink-0 place-items-center rounded-full font-medium"
        >
          {shown.slice(0, 1).toUpperCase()}
        </span>
      )}
      <div className="min-w-0">
        <div className="flex min-w-0 items-center gap-1.5">
          <Link to={`/users/${id}`} className={`${LINK} truncate`}>
            {shown}
          </Link>
          {badges}
        </div>
        {sub !== undefined && <div className="text-fg-dim truncate text-xs">{sub}</div>}
      </div>
    </div>
  );
}
