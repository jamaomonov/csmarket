/** A file picker that uploads one image (JPG, PNG, WebP, ≤ 5 MB) and hands back its media row. */
import { Button } from "@csmarket/ui";
import { useId, useState } from "react";

import { type Media, uploadMedia } from "./api";
import { articleErrorText } from "./labels";

import { newUuid } from "@/lib/uuid";

const ACCEPT = ".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp";
const MAX_BYTES = 5 * 1024 * 1024;

interface MediaButtonProps {
  /** The button's text and the hidden input's label. */
  label: string;
  onUploaded: (media: Media) => void;
  onError: (message: string) => void;
}

/** Uploads `file`, refusing one over 5 MB before sending it; a failure is an `Error` whose
 * message is the operator's text. */
export async function uploadImage(file: File): Promise<Media> {
  if (file.size > MAX_BYTES) throw new Error("Файл больше 5 МБ.");
  try {
    return await uploadMedia(file, `admin-article-media-${newUuid()}`);
  } catch (e) {
    throw new Error(articleErrorText(e));
  }
}

export function MediaButton({ label, onUploaded, onError }: MediaButtonProps) {
  const id = useId();
  const [busy, setBusy] = useState(false);
  const pick = (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    uploadImage(file)
      .then(onUploaded)
      .catch((e: unknown) => {
        onError(e instanceof Error ? e.message : articleErrorText(e));
      })
      .finally(() => {
        setBusy(false);
      });
  };
  return (
    <>
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <input
        id={id}
        type="file"
        accept={ACCEPT}
        className="sr-only"
        disabled={busy}
        onChange={(e) => {
          pick(e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      <Button
        size="sm"
        variant="secondary"
        disabled={busy}
        onClick={() => {
          document.getElementById(id)?.click();
        }}
      >
        {busy ? "Загружаем…" : label}
      </Button>
    </>
  );
}
