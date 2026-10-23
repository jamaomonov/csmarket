/** One review in «Отзывы»: stars, text, language, user, deal, when; «Разобрано», hide / show. */
import { Button } from "@csmarket/ui";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { type AdminReview, resolveReview, setReviewHidden } from "./api";
import { dealPath, KIND_LABELS, LOCALE_LABELS } from "./labels";
import { StarsText } from "./StarsText";

import { CONFIRM_BUTTONS, ConfirmSheet } from "@/components/ConfirmSheet";
import { TextLink } from "@/components/TextLink";
import { UserCell } from "@/components/UserCell";
import { When } from "@/components/When";
import { errorText } from "@/features/users/labels";
import { useIdempotencyKey } from "@/features/users/useIdempotencyKey";

const NOTE_MAX = 500;

interface ReviewRowProps {
  review: AdminReview;
  /** A write went through: re-read the list and the counters. */
  onChanged: () => void;
}

export function ReviewRow({ review, onChanged }: ReviewRowProps) {
  const [resolving, setResolving] = useState(false);
  const [note, setNote] = useState("");
  const resolveKey = useIdempotencyKey("admin-review-resolve");
  const hideKey = useIdempotencyKey("admin-review-hide");
  const resolve = useMutation({
    mutationFn: (text: string) =>
      resolveReview(review.id, text, resolveKey.keyFor(`${review.id}:${text}`)),
    onSuccess: () => {
      resolveKey.reset();
      setResolving(false);
      onChanged();
    },
  });
  const hide = useMutation({
    mutationFn: (hidden: boolean) =>
      setReviewHidden(review.id, hidden, hideKey.keyFor(`${review.id}:${String(hidden)}`)),
    onSuccess: () => {
      hideKey.reset();
      onChanged();
    },
  });
  const open = review.rating < 4 && review.resolved_at === null;
  return (
    <li
      data-testid={`review-${review.id}`}
      className="border-border bg-surface flex flex-col gap-2 rounded-lg border p-3"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <StarsText rating={review.rating} />
        <span className="text-fg-muted">
          {KIND_LABELS[review.kind]} · {LOCALE_LABELS[review.locale]}
          {review.hidden ? " · скрыт" : ""}
        </span>
        <UserCell
          id={review.user.id}
          name={review.user.display_name}
          avatarUrl={review.user.avatar_url}
        />
        <TextLink to={dealPath(review)} number>
          {review.number}
        </TextLink>
        <When iso={review.created_at} className="text-fg-dim ml-auto" />
      </div>
      {review.text !== null ? <p className="whitespace-pre-line">{review.text}</p> : null}
      {review.resolved_at !== null ? (
        <p className="text-fg-muted text-sm">
          Разобрано <When iso={review.resolved_at} /> ·{" "}
          {`${review.resolved_by?.display_name ?? "—"} · ${review.resolved_note ?? ""}`}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {open ? (
          <Button
            size="sm"
            onClick={() => {
              setResolving(true);
            }}
          >
            Разобрано
          </Button>
        ) : null}
        <Button
          size="sm"
          variant="secondary"
          disabled={hide.isPending}
          onClick={() => {
            hide.mutate(!review.hidden);
          }}
        >
          {review.hidden ? "Показать" : "Скрыть с сайта"}
        </Button>
      </div>
      {hide.isError ? (
        <p role="alert" className="text-danger text-sm">
          {errorText(hide.error)}
        </p>
      ) : null}
      {resolving ? (
        <ConfirmSheet
          title="Отзыв разобран"
          busy={resolve.isPending}
          onClose={() => {
            setResolving(false);
          }}
        >
          <form
            className="flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              const text = note.trim();
              if (text !== "") resolve.mutate(text);
            }}
          >
            <label className="flex flex-col gap-1 text-sm">
              Что сделали
              <textarea
                value={note}
                maxLength={NOTE_MAX}
                rows={3}
                onChange={(e) => {
                  setNote(e.target.value);
                }}
                className="border-border bg-bg text-fg rounded-md border p-2 text-base"
              />
            </label>
            {resolve.isError ? (
              <p role="alert" className="text-danger text-sm">
                {errorText(resolve.error)}
              </p>
            ) : null}
            <div className={CONFIRM_BUTTONS}>
              <Button
                variant="ghost"
                onClick={() => {
                  setResolving(false);
                }}
              >
                Отмена
              </Button>
              <Button type="submit" disabled={note.trim() === "" || resolve.isPending}>
                Отметить
              </Button>
            </div>
          </form>
        </ConfirmSheet>
      ) : null}
    </li>
  );
}
