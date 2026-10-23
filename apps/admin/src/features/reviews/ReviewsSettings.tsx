/** «Показывать отзывы на сайте»: the public page's switch, with what it would show. */
import { Button, Switch } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { getReviewSettings, type ReviewSettings, saveReviewSettings } from "./api";

import { CONFIRM_BUTTONS, ConfirmSheet } from "@/components/ConfirmSheet";
import { Section } from "@/components/Section";
import { errorText } from "@/features/users/labels";
import { useIdempotencyKey } from "@/features/users/useIdempotencyKey";

export const SETTINGS_KEY = ["admin", "reviews", "settings"] as const;

export function ReviewsSettings() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: SETTINGS_KEY, queryFn: getReviewSettings });
  const key = useIdempotencyKey("admin-reviews-settings");
  const [confirming, setConfirming] = useState(false);
  const save = useMutation({
    mutationFn: (on: boolean) => saveReviewSettings(on, key.keyFor(String(on))),
    onSuccess: (data: ReviewSettings) => {
      key.reset();
      setConfirming(false);
      qc.setQueryData(SETTINGS_KEY, data);
    },
  });
  if (q.data === undefined) return null;
  const s = q.data;
  return (
    <Section title="Страница отзывов">
      <Switch
        label="Показывать отзывы на сайте"
        checked={s.reviews_public}
        disabled={save.isPending}
        hint={`Опубликовано: ${String(s.published_count)}`}
        onCheckedChange={(on) => {
          if (on) setConfirming(true);
          else save.mutate(false);
        }}
      />
      {save.isError ? (
        <p role="alert" className="text-danger text-sm">
          {errorText(save.error)}
        </p>
      ) : null}
      {confirming ? (
        <ConfirmSheet
          title="Включить страницу отзывов?"
          busy={save.isPending}
          onClose={() => {
            setConfirming(false);
          }}
        >
          <p className="font-medium">
            На csmarket.uz/reviews появятся опубликованные отзывы: {s.published_count}. Плохие и
            скрытые не показываются.
          </p>
          <div className={CONFIRM_BUTTONS}>
            <Button
              variant="ghost"
              onClick={() => {
                setConfirming(false);
              }}
            >
              Отмена
            </Button>
            <Button
              onClick={() => {
                save.mutate(true);
              }}
            >
              Включить
            </Button>
          </div>
        </ConfirmSheet>
      ) : null}
    </Section>
  );
}
