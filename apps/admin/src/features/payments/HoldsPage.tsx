/**
 * «На проверке»: payments the risk limits held (spec 2026-10-21-payment-risk-limits). The money is
 * in the kassa; the operator either lets the payment through («Пропустить») or, after sending
 * the money back to the card (in the kassa's cabinet, or by a card transfer for P2P), marks it
 * («Вернул на карту»).
 */
import { Button } from "@csmarket/ui";
import {
  type InfiniteData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { decideHold, getHolds, type Hold, type HoldPage } from "./api";
import { HOLD_DECISION_LABELS, HOLD_REASON_LABELS, holdErrorText } from "./labels";

import { DataTable } from "@/components/DataTable";
import { Modal } from "@/components/Modal";
import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { Tabs } from "@/components/Tabs";
import { UserCell } from "@/components/UserCell";
import { When } from "@/components/When";
import { getDashboard } from "@/features/dashboard/api";
import { DASHBOARD_KEY } from "@/features/dashboard/keys";
import { errorText, providerLabel } from "@/features/users/labels";
import { useIdempotencyKey } from "@/features/users/useIdempotencyKey";
import { formatSum } from "@/lib/format";
import { pick } from "@/lib/url-guards";
import { useUrlParams } from "@/lib/useUrlParams";

type State = "open" | "decided";
type Act = "release" | "returned";

const LIST_KEY = ["admin", "payments", "holds"] as const;
const KIND_LABELS: Record<Hold["kind"], string> = { topup: "Пополнение", order: "Заказ" };

function windowText(h: Hold): string | null {
  if (h.window_sum_uzs === null || h.limit_uzs === null) return null;
  return `за окно: ${formatSum(h.window_sum_uzs)} из ${formatSum(h.limit_uzs)}`;
}

function confirmText(h: Hold, act: Act): string {
  if (act === "release") {
    return `Пропустить платёж ${h.number}? ${
      h.kind === "topup" ? "Пополнение будет зачислено." : "Заказ уйдёт в покупку."
    }`;
  }
  const how = h.provider === "p2p" ? "переводом на карту" : "на карту в кабинете кассы";
  return `Вы вернули ${formatSum(h.amount_uzs)} ${how}? На баланс ничего не зачислится.`;
}

const ACT_LABEL: Record<Act, string> = { release: "Пропустить", returned: "Вернул на карту" };

interface DecideDialogProps {
  hold: Hold;
  act: Act;
  onDone: () => void;
  onClose: () => void;
}

function DecideDialog({ hold, act, onDone, onClose }: DecideDialogProps) {
  const qc = useQueryClient();
  const key = useIdempotencyKey(`admin-hold-${act}`);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: LIST_KEY });
    void qc.invalidateQueries({ queryKey: DASHBOARD_KEY });
  };
  const decide = useMutation({
    mutationFn: () => decideHold(hold.id, act, key.keyFor(hold.id)),
    onSuccess: () => {
      key.reset();
      refresh();
      onDone();
    },
    onError: refresh,
  });
  return (
    <Modal
      title={ACT_LABEL[act]}
      description={confirmText(hold, act)}
      onClose={onClose}
      busy={decide.isPending}
    >
      {decide.isError && (
        <p role="alert" className="text-danger text-sm">
          {holdErrorText(decide.error)}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button variant="secondary" disabled={decide.isPending} onClick={onClose}>
          Отмена
        </Button>
        <Button
          disabled={decide.isPending}
          onClick={() => {
            decide.mutate();
          }}
        >
          {ACT_LABEL[act]}
        </Button>
      </div>
    </Modal>
  );
}

function Actions({ onPick }: { onPick: (a: Act) => void }) {
  return (
    <div className="flex flex-wrap justify-end gap-2">
      {(["release", "returned"] as const).map((a) => (
        <Button
          key={a}
          size="sm"
          variant={a === "release" ? "primary" : "secondary"}
          onClick={() => {
            onPick(a);
          }}
        >
          {ACT_LABEL[a]}
        </Button>
      ))}
    </div>
  );
}

function DecisionCell({ h }: { h: Hold }) {
  const label = h.decision === null ? "—" : (HOLD_DECISION_LABELS[h.decision] ?? h.decision);
  return (
    <div className="text-sm">
      <div>{label}</div>
      <div className="text-fg-muted text-xs">
        {h.decided_by?.display_name ?? "—"}
        {h.decided_at !== null && (
          <>
            {" · "}
            <When iso={h.decided_at} />
          </>
        )}
      </div>
    </div>
  );
}

const STATES: readonly State[] = ["open", "decided"];

export function HoldsPage() {
  const url = useUrlParams();
  const state: State = pick(STATES, url.get("state")) ?? "open";
  // The open count is the dashboard's (shared with the menu's counter): the list has none.
  const dashboard = useQuery({
    queryKey: [...DASHBOARD_KEY, 1],
    queryFn: () => getDashboard(1),
    refetchInterval: 60_000,
  });
  const [picked, setPicked] = useState<{ hold: Hold; act: Act } | null>(null);
  const list = useInfiniteQuery<
    HoldPage,
    Error,
    InfiniteData<HoldPage, string | null>,
    readonly unknown[],
    string | null
  >({
    queryKey: [...LIST_KEY, state],
    queryFn: ({ pageParam }) => getHolds(state, pageParam),
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const holds = list.data?.pages.flatMap((p) => p.items);
  const open = state === "open";

  return (
    <section className="space-y-4">
      <PageHeader title="На проверке" />
      <Tabs<State>
        label="Состояние"
        value={state}
        onChange={(v) => {
          url.set("state", v === "open" ? "" : v);
        }}
        items={[
          {
            key: "open",
            label: "Открытые",
            ...(dashboard.data !== undefined && { count: dashboard.data.holds_open }),
            alert: true,
          },
          { key: "decided", label: "Решённые" },
        ]}
      />
      <DataTable
        label="Платежи на проверке"
        rows={holds}
        rowKey={(h) => h.id}
        loading={list.isPending}
        error={list.isError ? errorText(list.error) : undefined}
        empty={open ? "Ничего не ждёт решения." : "Решённых пока нет."}
        columns={[
          {
            key: "number",
            header: "Номер",
            cell: (h) => (
              <>
                <Link
                  to={`/payments?q=${encodeURIComponent(h.number)}`}
                  className="font-mono font-medium hover:underline"
                >
                  {h.number}
                </Link>
                <div className="text-fg-muted text-xs">{KIND_LABELS[h.kind]}</div>
              </>
            ),
          },
          { key: "kassa", header: "Касса", cell: (h) => providerLabel(h.provider) },
          {
            key: "sum",
            header: "Сумма",
            align: "right",
            cell: (h) => <Money uzs={h.amount_uzs} />,
          },
          {
            key: "reason",
            header: "Причина",
            cell: (h) => (
              <>
                {HOLD_REASON_LABELS[h.reason] ?? h.reason}
                <div className="text-fg-muted text-xs">{windowText(h)}</div>
              </>
            ),
          },
          {
            key: "user",
            header: "Пользователь",
            cell: (h) => <UserCell id={h.user.id} name={h.user.display_name} />,
          },
          {
            key: "created",
            header: "Создан",
            cell: (h) => <When iso={h.created_at} className="text-fg-muted" />,
          },
          {
            key: "action",
            header: open ? "" : "Решение",
            align: open ? "right" : "left",
            cell: (h) =>
              open ? (
                <Actions
                  onPick={(act) => {
                    setPicked({ hold: h, act });
                  }}
                />
              ) : (
                <DecisionCell h={h} />
              ),
          },
        ]}
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
      {picked !== null && (
        <DecideDialog
          hold={picked.hold}
          act={picked.act}
          onDone={() => {
            setPicked(null);
          }}
          onClose={() => {
            setPicked(null);
          }}
        />
      )}
    </section>
  );
}
