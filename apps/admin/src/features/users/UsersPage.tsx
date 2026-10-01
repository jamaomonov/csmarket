/** «Пользователи»: find an account by name or Steam ID, newest first, page by page. */
import { Button } from "@csmarket/ui";
import { type InfiniteData, useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { type AdminUserRow, type AdminUsersPage, listUsers, type ListUsersParams } from "./api";
import { errorText, roleLabel } from "./labels";

import { formatDateTime, formatSum } from "@/lib/format";
import { useDebounced } from "@/lib/useDebounced";

const DEBOUNCE_MS = 300;

function params(q: string, cursor: string | null): ListUsersParams {
  return { ...(q !== "" && { q }), ...(cursor !== null && { cursor }) };
}

function Avatar({ url }: { url: string | null }) {
  return url ? (
    <img src={url} alt="" width={32} height={32} loading="lazy" className="h-8 w-8 rounded" />
  ) : (
    <div className="bg-surface-2 h-8 w-8 rounded" aria-hidden="true" />
  );
}

function UserRow({ user }: { user: AdminUserRow }) {
  return (
    <tr className="border-border border-t">
      <td className="py-2 pr-3">
        <Avatar url={user.avatar_url} />
      </td>
      <td className="py-2 pr-3">
        <Link to={`/users/${user.id}`} className="font-medium hover:underline">
          {user.display_name ?? "Без имени"}
        </Link>
      </td>
      <td className="whitespace-nowrap py-2 pr-3 text-right tabular-nums">
        {formatSum(user.balance_uzs)}
      </td>
      <td className="text-fg-muted py-2 pr-3">{roleLabel(user.roles)}</td>
      <td className="py-2 pr-3">
        {user.banned_at && (
          <span className="bg-danger text-danger-fg rounded px-2 py-0.5 text-xs">заблокирован</span>
        )}
      </td>
      <td className="text-fg-muted whitespace-nowrap py-2">{formatDateTime(user.created_at)}</td>
    </tr>
  );
}

export function UsersPage() {
  const [text, setText] = useState("");
  const q = useDebounced(text.trim(), DEBOUNCE_MS);
  const list = useInfiniteQuery<
    AdminUsersPage,
    Error,
    InfiniteData<AdminUsersPage, string | null>,
    readonly ["admin", "users", "list", string],
    string | null
  >({
    queryKey: ["admin", "users", "list", q],
    queryFn: ({ pageParam }) => listUsers(params(q, pageParam)),
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const users = list.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <section className="space-y-6">
      <h1 className="text-2xl font-bold">Пользователи</h1>
      <label className="flex max-w-md flex-col gap-1 text-sm">
        Имя или Steam ID
        <input
          type="search"
          value={text}
          maxLength={80}
          onChange={(e) => {
            setText(e.target.value);
          }}
          className="border-border bg-bg h-10 rounded-md border px-3 text-base"
        />
      </label>
      {list.isPending && <p className="text-fg-muted">Загрузка…</p>}
      {list.isError && (
        <p role="alert" className="text-danger">
          {errorText(list.error)}
        </p>
      )}
      {list.isSuccess && users.length === 0 && <p className="text-fg-muted">Никого не нашли.</p>}
      {users.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm" data-testid="users-table">
            <thead className="text-fg-muted">
              <tr>
                <th className="py-1 font-normal">
                  <span className="sr-only">Аватар</span>
                </th>
                <th className="py-1 font-normal">Имя</th>
                <th className="py-1 text-right font-normal">Баланс</th>
                <th className="py-1 font-normal">Роль</th>
                <th className="py-1 font-normal">
                  <span className="sr-only">Блокировка</span>
                </th>
                <th className="py-1 font-normal">Регистрация</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <UserRow key={u.id} user={u} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {list.hasNextPage && (
        <Button
          variant="secondary"
          disabled={list.isFetchingNextPage}
          onClick={() => {
            void list.fetchNextPage();
          }}
        >
          Показать ещё
        </Button>
      )}
    </section>
  );
}
