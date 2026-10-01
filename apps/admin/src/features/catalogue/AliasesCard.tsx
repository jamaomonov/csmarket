/** Search aliases: a word people type and the word the search should use instead. */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type SubmitEvent, useState } from "react";

import { deleteAlias, listAliases, putAlias } from "./api";

import { ApiError, formatApiError } from "@/lib/api";

function errorText(err: unknown): string {
  return err instanceof ApiError ? formatApiError(err) : "Не получилось. Попробуйте ещё раз.";
}

export function AliasesCard() {
  const qc = useQueryClient();
  const [alias, setAlias] = useState("");
  const [text, setText] = useState("");
  const list = useQuery({ queryKey: ["catalogue", "aliases"], queryFn: listAliases });
  const refresh = () => qc.invalidateQueries({ queryKey: ["catalogue", "aliases"] });

  const add = useMutation({
    mutationFn: (v: { alias: string; text: string }) => putAlias(v.alias, v.text),
    onSuccess: async () => {
      setAlias("");
      setText("");
      await refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (name: string) => deleteAlias(name),
    onSuccess: refresh,
  });

  const onSubmit = (e: SubmitEvent<HTMLFormElement>) => {
    e.preventDefault();
    const a = alias.trim();
    const t = text.trim();
    if (a && t) add.mutate({ alias: a, text: t });
  };

  const items = list.data?.items ?? [];
  const input = "border-border bg-bg h-10 rounded-md border px-3 text-base";
  return (
    <section className="border-border bg-surface rounded-lg border p-5">
      <h2 className="mb-3 text-lg font-semibold">Синонимы для поиска</h2>
      {list.isPending && <p className="text-fg-muted">Загрузка…</p>}
      {list.isError && (
        <p role="alert" className="text-danger">
          {errorText(list.error)}
        </p>
      )}
      {list.data && items.length === 0 && <p className="text-fg-muted">Пока нет ни одного.</p>}
      {items.length > 0 && (
        <table className="w-full text-left text-sm">
          <thead className="text-fg-muted">
            <tr>
              <th className="py-1 font-normal">Как ищут</th>
              <th className="py-1 font-normal">Что находит</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((a) => (
              <tr key={a.alias} className="border-border border-t">
                <td className="py-2">{a.alias}</td>
                <td className="py-2">{a.text}</td>
                <td className="py-2 text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={remove.isPending}
                    onClick={() => {
                      remove.mutate(a.alias);
                    }}
                  >
                    Удалить
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <form onSubmit={onSubmit} className="mt-4 flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-sm">
          Как ищут
          <input
            value={alias}
            onChange={(e) => {
              setAlias(e.target.value);
            }}
            maxLength={64}
            className={input}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Что найти
          <input
            value={text}
            onChange={(e) => {
              setText(e.target.value);
            }}
            maxLength={128}
            className={input}
          />
        </label>
        <Button type="submit" disabled={add.isPending}>
          Добавить
        </Button>
      </form>
      <p className="text-fg-muted mt-2 text-sm">
        Например: ак → ak-47, керамбит → karambit. Поиск заменяет слово целиком.
      </p>
      {add.isError && (
        <p role="alert" className="text-danger mt-2">
          {errorText(add.error)}
        </p>
      )}
      {remove.isError && (
        <p role="alert" className="text-danger mt-2">
          {errorText(remove.error)}
        </p>
      )}
    </section>
  );
}
