/**
 * One language of an article: title, description (with a search-snippet preview), the cover's
 * alt text, the Markdown body with a live preview, «Перевод готов». The toolbar puts images and
 * skin cards where the caret is; pasting or dropping an image file uploads it.
 */
import { Checkbox, Input, Markdown } from "@csmarket/ui";
import { type ClipboardEvent, type DragEvent, useRef, useState } from "react";

import { insertAt, imageMarkdown } from "./insert";
import { MediaButton, uploadImage } from "./MediaButton";
import { SkinPicker } from "./SkinPicker";

import type { TranslationIn } from "./api";

import { apiBase } from "@/lib/api";

const LIMITS = { title: 120, description: 200, cover_alt: 160 } as const;

interface TranslationTabProps {
  value: TranslationIn;
  onChange: (next: TranslationIn) => void;
  onError: (message: string) => void;
}

function Counted({
  label,
  value,
  max,
  onChange,
  multiline = false,
}: {
  label: string;
  value: string;
  max: number;
  onChange: (v: string) => void;
  multiline?: boolean;
}) {
  return (
    <label className="block space-y-1 text-sm">
      <span className="flex justify-between">
        <span>{label}</span>
        <span className={value.length > max ? "text-danger" : "text-fg-dim"}>
          {value.length}/{max}
        </span>
      </span>
      {multiline ? (
        <textarea
          aria-label={label}
          className="border-border bg-surface w-full rounded-lg border px-3 py-2"
          rows={2}
          maxLength={max}
          value={value}
          onChange={(e) => {
            onChange(e.target.value);
          }}
        />
      ) : (
        <Input
          aria-label={label}
          maxLength={max}
          value={value}
          onChange={(e) => {
            onChange(e.target.value);
          }}
        />
      )}
    </label>
  );
}

export function TranslationTab({ value, onChange, onError }: TranslationTabProps) {
  const area = useRef<HTMLTextAreaElement>(null);
  const [picking, setPicking] = useState(false);
  const set = (patch: Partial<TranslationIn>) => {
    onChange({ ...value, ...patch });
  };
  const insert = (snippet: string, block: boolean) => {
    const el = area.current;
    const pos = el?.selectionStart ?? value.body.length;
    const next = insertAt(value.body, pos, snippet, block);
    set({ body: next.text });
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(next.caret, next.caret);
    });
  };
  const wrapLine = (prefix: string) => {
    insert(prefix, false);
  };
  const filesOf = (list: FileList | null): File | undefined =>
    Array.from(list ?? []).find((f) => f.type.startsWith("image/"));
  const fromClipboard = (file: File | undefined, prevent: () => void) => {
    if (!file) return;
    prevent();
    uploadImage(file)
      .then((m) => {
        insert(imageMarkdown(m), false);
      })
      .catch((e: unknown) => {
        onError(e instanceof Error ? e.message : String(e));
      });
  };
  return (
    <div className="space-y-4">
      <Counted
        label="Заголовок"
        value={value.title}
        max={LIMITS.title}
        onChange={(v) => {
          set({ title: v });
        }}
      />
      <Counted
        label="Описание"
        value={value.description}
        max={LIMITS.description}
        multiline
        onChange={(v) => {
          set({ description: v });
        }}
      />
      <div className="border-border rounded-lg border p-3 text-sm" aria-label="Как в поиске">
        <p className="text-accent truncate">{value.title || "Заголовок"}</p>
        <p className="text-fg-muted line-clamp-2">{value.description || "Описание"}</p>
      </div>
      <Counted
        label="Подпись к обложке"
        value={value.cover_alt}
        max={LIMITS.cover_alt}
        onChange={(v) => {
          set({ cover_alt: v });
        }}
      />
      <div className="flex flex-wrap gap-2">
        <MediaButton
          label="Картинка в текст"
          onUploaded={(m) => {
            insert(imageMarkdown(m), false);
          }}
          onError={onError}
        />
        <button
          type="button"
          className="border-border rounded-md border px-3 text-sm"
          onClick={() => {
            setPicking((p) => !p);
          }}
        >
          Скин
        </button>
        <button
          type="button"
          className="border-border rounded-md border px-3 text-sm"
          onClick={() => {
            wrapLine("\n## ");
          }}
        >
          H2
        </button>
        <button
          type="button"
          className="border-border rounded-md border px-3 text-sm"
          onClick={() => {
            wrapLine("\n- ");
          }}
        >
          Список
        </button>
        <button
          type="button"
          className="border-border rounded-md border px-3 text-sm"
          onClick={() => {
            insert("[текст](https://)", false);
          }}
        >
          Ссылка
        </button>
      </div>
      {picking ? (
        <SkinPicker
          onPick={(slug) => {
            insert(`[[skin:${slug}]]`, true);
            setPicking(false);
          }}
        />
      ) : null}
      <div className="grid gap-4 lg:grid-cols-2">
        <label className="block space-y-1 text-sm">
          <span>Текст</span>
          <textarea
            ref={area}
            className="border-border bg-surface min-h-[420px] w-full rounded-lg border px-3 py-2 font-mono text-sm"
            value={value.body}
            onChange={(e) => {
              set({ body: e.target.value });
            }}
            onPaste={(e: ClipboardEvent<HTMLTextAreaElement>) => {
              fromClipboard(filesOf(e.clipboardData.files), () => {
                e.preventDefault();
              });
            }}
            onDrop={(e: DragEvent<HTMLTextAreaElement>) => {
              fromClipboard(filesOf(e.dataTransfer.files), () => {
                e.preventDefault();
              });
            }}
          />
        </label>
        <div
          className="border-border bg-surface min-h-[420px] rounded-lg border p-4"
          aria-label="Предпросмотр"
        >
          <Markdown
            source={value.body}
            className="article-body"
            mediaUrl={(path) => `${apiBase}/api/v1${path}`}
            renderSkin={(slug) => (
              <div className="border-border text-fg-muted my-2 rounded-lg border border-dashed p-3 text-sm">
                Карточка скина: {slug}
              </div>
            )}
          />
        </div>
      </div>
      <Checkbox
        checked={value.ready}
        onChange={(e) => {
          set({ ready: e.target.checked });
        }}
      >
        Перевод готов
      </Checkbox>
    </div>
  );
}
