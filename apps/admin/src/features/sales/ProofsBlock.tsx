/**
 * «Подтверждение оплаты»: up to three receipts (a screenshot or a PDF of the transfer) an admin
 * may attach to a paid payout, to have the proof at hand in a dispute. Optional. A receipt opens
 * from the API with the admin's token (never a public link); it may be deleted for 10 minutes
 * after its upload, then it stays. The seller never sees them.
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { payoutKey } from "./keys";
import { payoutErrorText } from "./labels";
import {
  addProof,
  deleteProof,
  type PayoutDetail,
  type PayoutProof,
  proofFile,
} from "./payoutsApi";

import { CONFIRM_BUTTONS, ConfirmSheet, DANGER_OUTLINE } from "@/components/ConfirmSheet";
import { Section } from "@/components/Section";
import { useIdempotencyKey } from "@/features/users/useIdempotencyKey";
import { formatDateTime } from "@/lib/format";

const MAX_PROOFS = 3;
const MAX_BYTES = 5 * 1024 * 1024;
const ACCEPT = ".jpg,.jpeg,.png,.webp,.pdf,image/jpeg,image/png,image/webp,application/pdf";

function size(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024)).toString()} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1).replace(".", ",")} МБ`;
}

/** Open the receipt in a new tab: the tab opens on the click (no popup block), the file
 * arrives after; without a tab the file is saved instead. */
async function open(requestId: string, proof: PayoutProof): Promise<void> {
  const tab = window.open("", "_blank");
  try {
    const url = URL.createObjectURL(await proofFile(requestId, proof.id));
    if (tab) {
      tab.location.href = url;
    } else {
      const a = document.createElement("a");
      a.href = url;
      a.download = proof.name;
      a.click();
    }
    window.setTimeout(() => {
      URL.revokeObjectURL(url);
    }, 60_000);
  } catch (e) {
    tab?.close();
    throw e;
  }
}

interface ProofsBlockProps {
  detail: PayoutDetail;
}

export function ProofsBlock({ detail }: ProofsBlockProps) {
  const qc = useQueryClient();
  const inputId = useId();
  const id = detail.request.id;
  const proofs = detail.proofs ?? [];
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<PayoutProof | null>(null);
  const addKey = useIdempotencyKey("admin-proof");
  const delKey = useIdempotencyKey("admin-proof-delete");
  const done = (next: PayoutDetail) => {
    qc.setQueryData(payoutKey(id), next);
    setError(null);
  };
  const upload = useMutation({
    mutationFn: (file: File) =>
      addProof(
        id,
        file,
        addKey.keyFor(`${file.name}:${file.size.toString()}:${file.lastModified.toString()}`),
      ),
    onSuccess: (next) => {
      addKey.reset();
      done(next);
    },
    onError: (e) => {
      setError(payoutErrorText(e));
    },
  });
  const remove = useMutation({
    mutationFn: (proof: PayoutProof) => deleteProof(id, proof.id, delKey.keyFor(proof.id)),
    onSuccess: (next) => {
      delKey.reset();
      setDeleting(null);
      done(next);
    },
    onError: (e) => {
      setDeleting(null);
      setError(payoutErrorText(e));
    },
  });
  if (detail.request.status !== "paid" && proofs.length === 0) return null;
  const canAdd = detail.request.status === "paid" && proofs.length < MAX_PROOFS;
  const pick = (file: File | undefined) => {
    if (!file) return;
    if (file.size > MAX_BYTES) {
      setError("Файл больше 5 МБ.");
      return;
    }
    upload.mutate(file);
  };
  return (
    <Section title="Подтверждение оплаты">
      {proofs.length > 0 ? (
        <ul className="mb-3 space-y-2 text-sm">
          {proofs.map((p) => (
            <li key={p.id} className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <button
                  type="button"
                  className="text-accent block max-w-full truncate text-left underline"
                  onClick={() => {
                    open(id, p).catch((e: unknown) => {
                      setError(payoutErrorText(e));
                    });
                  }}
                >
                  {p.name}
                </button>
                <p className="text-fg-muted text-xs">
                  {size(p.size)} · {p.uploaded_by?.display_name ?? "—"} ·{" "}
                  {formatDateTime(p.created_at)}
                </p>
              </div>
              {p.delete_until !== null ? (
                <Button
                  size="sm"
                  variant="secondary"
                  className={DANGER_OUTLINE}
                  aria-label={`Удалить ${p.name}`}
                  onClick={() => {
                    setDeleting(p);
                  }}
                >
                  Удалить
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {deleting ? (
        <ConfirmSheet
          title="Удалить файл"
          busy={remove.isPending}
          onClose={() => {
            setDeleting(null);
          }}
        >
          <p className="mb-3 text-sm">Удалить «{deleting.name}»? Вернуть его не получится.</p>
          <div className={CONFIRM_BUTTONS}>
            <Button
              variant="secondary"
              disabled={remove.isPending}
              onClick={() => {
                setDeleting(null);
              }}
            >
              Отмена
            </Button>
            <Button
              variant="danger"
              disabled={remove.isPending}
              onClick={() => {
                remove.mutate(deleting);
              }}
            >
              Да, удалить
            </Button>
          </div>
        </ConfirmSheet>
      ) : null}
      {canAdd ? (
        <div>
          <label htmlFor={inputId} className="sr-only">
            Загрузить файл
          </label>
          <input
            id={inputId}
            type="file"
            accept={ACCEPT}
            className="sr-only"
            disabled={upload.isPending}
            onChange={(e) => {
              pick(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          <Button
            variant="secondary"
            disabled={upload.isPending}
            onClick={() => {
              document.getElementById(inputId)?.click();
            }}
          >
            {upload.isPending ? "Загружаем…" : "Загрузить файл"}
          </Button>
          <p className="text-fg-muted mt-2 text-xs">
            Скриншот или документ о переводе: JPG, PNG, WebP или PDF до 5 МБ, не больше {MAX_PROOFS}{" "}
            файлов. Необязательно. Удалить можно в течение 10 минут.
          </p>
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="text-danger mt-2 text-sm">
          {error}
        </p>
      ) : null}
    </Section>
  );
}
