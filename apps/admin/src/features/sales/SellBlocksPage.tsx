/**
 * «Запрет выкупа»: every user an admin stopped from selling (newest first), why and by whom,
 * with «Разрешить» to lift it. A block is set from a payout's «Риски» block.
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { listSellBlocks, type SellBlock, setSellBlock } from "./api";
import { SELL_BLOCKS_KEY } from "./keys";
import { payoutErrorText } from "./labels";

import { DataTable } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { When } from "@/components/When";
import { errorText } from "@/features/users/labels";
import { useIdempotencyKey } from "@/features/users/useIdempotencyKey";

function Unblock({ block }: { block: SellBlock }) {
  const qc = useQueryClient();
  const key = useIdempotencyKey("admin-sell-unblock");
  const lift = useMutation({
    mutationFn: () => setSellBlock(block.user.id, false, null, key.keyFor(block.user.id)),
    onSuccess: () => {
      key.reset();
      void qc.invalidateQueries({ queryKey: SELL_BLOCKS_KEY });
    },
  });
  return (
    <span className="inline-flex flex-col gap-1">
      <Button
        variant="secondary"
        size="sm"
        disabled={lift.isPending}
        onClick={() => {
          lift.mutate();
        }}
      >
        Разрешить
      </Button>
      {lift.isError ? (
        <span role="alert" className="text-danger text-xs">
          {payoutErrorText(lift.error)}
        </span>
      ) : null}
    </span>
  );
}

export function SellBlocksPage() {
  const query = useQuery({ queryKey: SELL_BLOCKS_KEY, queryFn: listSellBlocks });
  return (
    <section className="space-y-4">
      <PageHeader
        title="Запрет выкупа"
        meta="Эти пользователи не могут продавать скины. Запретить можно на странице выплаты, в блоке «Риски»."
      />
      <DataTable
        label="Запрет выкупа"
        rows={query.data?.items}
        rowKey={(b) => b.user.id}
        loading={query.isPending}
        error={query.isError ? errorText(query.error) : undefined}
        empty="Никому не запрещено."
        columns={[
          {
            key: "user",
            header: "Пользователь",
            cell: (b) => (
              <Link to={`/users/${b.user.id}`} className="hover:underline">
                {b.user.display_name ?? "Без имени"}
              </Link>
            ),
          },
          { key: "reason", header: "Причина", cell: (b) => b.reason ?? "—" },
          {
            key: "by",
            header: "Кто и когда",
            cell: (b) => (
              <span className="text-fg-muted">
                {b.blocked_by?.display_name ?? "—"}
                {b.blocked_at ? (
                  <>
                    , <When iso={b.blocked_at} />
                  </>
                ) : null}
              </span>
            ),
          },
          { key: "act", header: "", cell: (b) => <Unblock block={b} /> },
        ]}
        mobileCard={(b) => (
          <div className="space-y-1 text-sm">
            <div className="flex items-center justify-between gap-2">
              <Link to={`/users/${b.user.id}`} className="font-medium hover:underline">
                {b.user.display_name ?? "Без имени"}
              </Link>
              <Unblock block={b} />
            </div>
            <p>{b.reason ?? "—"}</p>
            <p className="text-fg-dim text-xs">
              {b.blocked_by?.display_name ?? "—"}
              {b.blocked_at ? (
                <>
                  , <When iso={b.blocked_at} />
                </>
              ) : null}
            </p>
          </div>
        )}
      />
    </section>
  );
}
