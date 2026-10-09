/** «Пользователи»: find an account by name or Steam ID; a tab keeps those with an API key. */
import { Button } from "@csmarket/ui";
import { type InfiniteData, useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { type AdminUsersPage, listUsers, type ListUsersParams } from "./api";
import { errorText, roleLabel } from "./labels";
import { tariffLabel } from "../apiKeys/labels";

import { DataTable } from "@/components/DataTable";
import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { StatusChip } from "@/components/StatusChip";
import { Tabs } from "@/components/Tabs";
import { UserCell } from "@/components/UserCell";
import { formatDateTime } from "@/lib/format";
import { useDebounced } from "@/lib/useDebounced";

const DEBOUNCE_MS = 300;
type View = "all" | "api";

function params(q: string, cursor: string | null, view: View): ListUsersParams {
  return {
    ...(q !== "" && { q }),
    ...(cursor !== null && { cursor }),
    ...(view === "api" && { hasApiKey: true }),
  };
}

export function UsersPage() {
  const navigate = useNavigate();
  const [search, setSearch] = useSearchParams();
  const view: View = search.get("has_api_key") === "true" ? "api" : "all";
  const [text, setText] = useState("");
  const q = useDebounced(text.trim(), DEBOUNCE_MS);
  const list = useInfiniteQuery<
    AdminUsersPage,
    Error,
    InfiniteData<AdminUsersPage, string | null>,
    readonly ["admin", "users", "list", string, View],
    string | null
  >({
    queryKey: ["admin", "users", "list", q, view],
    queryFn: ({ pageParam }) => listUsers(params(q, pageParam, view)),
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const users = list.data?.pages.flatMap((p) => p.items);

  return (
    <section className="space-y-4">
      <PageHeader title="Пользователи" />
      <div className="flex flex-wrap items-end justify-between gap-3">
        <Tabs<View>
          label="Кого показать"
          value={view}
          onChange={(next) => {
            setSearch(next === "api" ? { has_api_key: "true" } : {}, { replace: true });
          }}
          items={[
            { key: "all", label: "Все" },
            { key: "api", label: "С API-ключом" },
          ]}
        />
        <input
          type="search"
          aria-label="Имя или Steam ID"
          placeholder="Имя или Steam ID"
          value={text}
          maxLength={80}
          onChange={(e) => {
            setText(e.target.value);
          }}
          className="border-border bg-bg h-9 w-full rounded-md border px-3 text-sm sm:w-72"
        />
      </div>
      <DataTable
        label="Пользователи"
        rows={users}
        rowKey={(u) => u.id}
        loading={list.isPending}
        error={list.isError ? errorText(list.error) : undefined}
        empty="Никого не нашли."
        onRowClick={(u) => {
          void navigate(`/users/${u.id}`);
        }}
        columns={[
          {
            key: "name",
            header: "Пользователь",
            cell: (u) => (
              <UserCell id={u.id} name={u.display_name} avatarUrl={u.avatar_url} sub={u.steam_id} />
            ),
          },
          {
            key: "balance",
            header: "Баланс",
            align: "right",
            cell: (u) => <Money uzs={u.balance_uzs} />,
          },
          {
            key: "api",
            header: "API",
            cell: (u) =>
              u.api_key === null ? (
                <span className="text-fg-dim">—</span>
              ) : (
                <StatusChip tone="neutral">{tariffLabel(u.api_key.pricing_profile)}</StatusChip>
              ),
          },
          {
            key: "role",
            header: "Роль",
            cell: (u) => (
              <div className="flex flex-wrap gap-1">
                <span className="text-fg-muted">{roleLabel(u.roles)}</span>
                {u.banned_at !== null && <StatusChip tone="danger">заблокирован</StatusChip>}
              </div>
            ),
          },
          {
            key: "created",
            header: "Регистрация",
            cell: (u) => (
              <span className="text-fg-muted whitespace-nowrap">
                {formatDateTime(u.created_at)}
              </span>
            ),
          },
        ]}
        mobileCard={(u) => (
          <div className="flex items-center justify-between gap-3">
            <UserCell
              id={u.id}
              name={u.display_name}
              avatarUrl={u.avatar_url}
              sub={u.banned_at !== null ? "заблокирован" : roleLabel(u.roles)}
            />
            <Money uzs={u.balance_uzs} className="text-sm" />
          </div>
        )}
        footer={
          list.hasNextPage ? (
            <Button
              variant="secondary"
              size="sm"
              disabled={list.isFetchingNextPage}
              onClick={() => {
                void list.fetchNextPage();
              }}
            >
              Показать ещё
            </Button>
          ) : undefined
        }
      />
    </section>
  );
}
