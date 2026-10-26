/**
 * One article in the admin (spec 2026-10-26-articles «Admin»): section, address, cover, and
 * three tabs ru / uz / en. «Сохранить» writes it; «Опубликовать» / «Снять с публикации» ask first.
 * Unsaved changes are kept in this browser and offered back on the next open.
 */
import { Button, Select } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  type AdminArticle,
  type ArticleIn,
  type ArticleLocale,
  createArticle,
  getArticle,
  type Media,
  publishArticle,
  type Section,
  type TranslationIn,
  unpublishArticle,
  updateArticle,
} from "./api";
import { ARTICLES_KEY } from "./ArticlesPage";
import {
  articleErrorText,
  LOCALE_LABEL,
  LOCALES,
  SECTION_LABEL,
  SECTIONS,
  STATUS_LABEL,
} from "./labels";
import { MediaButton } from "./MediaButton";
import { TranslationTab } from "./TranslationTab";

import { CONFIRM_BUTTONS, ConfirmSheet } from "@/components/ConfirmSheet";
import { PageHeader } from "@/components/PageHeader";
import { Tabs } from "@/components/Tabs";
import { useIdempotencyKey } from "@/features/users/useIdempotencyKey";
import { apiBase } from "@/lib/api";

interface Form {
  section: Section;
  slug: string;
  cover: Media | null;
  translations: Partial<Record<ArticleLocale, TranslationIn>>;
}

const BLANK: TranslationIn = { title: "", description: "", cover_alt: "", body: "", ready: false };
const EMPTY_FORM: Form = { section: "news", slug: "", cover: null, translations: {} };

function formOf(a: AdminArticle): Form {
  const translations: Form["translations"] = {};
  for (const l of LOCALES) {
    const t = a.translations[l];
    if (t)
      translations[l] = {
        title: t.title,
        description: t.description,
        cover_alt: t.cover_alt,
        body: t.body,
        ready: t.ready,
      };
  }
  return { section: a.section, slug: a.slug, cover: a.cover, translations };
}

/** The ru title, else the first one written. */
function titleOf(form: Form): string {
  return LOCALES.map((l) => form.translations[l]?.title ?? "").find((t) => t !== "") ?? "Статья";
}

const draftKey = (id: string | undefined) => `admin.article-draft.${id ?? "new"}`;

function readDraft(id: string | undefined): Form | null {
  try {
    const raw = localStorage.getItem(draftKey(id));
    return raw ? (JSON.parse(raw) as Form) : null; // our own JSON, written below
  } catch {
    return null;
  }
}

function writeDraft(id: string | undefined, form: Form | null): void {
  try {
    if (form === null) localStorage.removeItem(draftKey(id));
    else localStorage.setItem(draftKey(id), JSON.stringify(form));
  } catch {
    // storage blocked: the draft is a convenience only
  }
}

/** Only the languages with something written are sent. */
function written(t: Form["translations"]): Form["translations"] {
  const out: Form["translations"] = {};
  for (const l of LOCALES) {
    const v = t[l];
    if (v && (v.title || v.description || v.body || v.cover_alt || v.ready)) out[l] = v;
  }
  return out;
}

export function ArticleEditor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const article = useQuery({
    queryKey: [...ARTICLES_KEY, "one", id],
    queryFn: () => getArticle(id ?? ""),
    enabled: id !== undefined,
  });
  const [form, setForm] = useState<Form>(EMPTY_FORM);
  const [dirty, setDirty] = useState(false);
  const [tab, setTab] = useState<ArticleLocale>("ru");
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<"publish" | "unpublish" | null>(null);
  const [draft, setDraft] = useState<Form | null>(() => readDraft(id));
  const saveKey = useIdempotencyKey("admin-article-save");
  const actKey = useIdempotencyKey("admin-article-publish");

  // The loaded article fills the form, never over edits in progress (a restored draft).
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  useEffect(() => {
    if (article.data && !dirtyRef.current) setForm(formOf(article.data));
  }, [article.data]);

  useEffect(() => {
    if (dirty) writeDraft(id, form);
  }, [dirty, form, id]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => {
      window.removeEventListener("beforeunload", warn);
    };
  }, [dirty]);

  const change = (patch: Partial<Form>) => {
    setForm((f) => ({ ...f, ...patch }));
    setDirty(true);
  };
  const saved = (a: AdminArticle) => {
    writeDraft(id, null);
    setDirty(false);
    setError(null);
    qc.setQueryData([...ARTICLES_KEY, "one", a.id], a);
    void qc.invalidateQueries({ queryKey: [...ARTICLES_KEY, "list"] });
  };

  const save = useMutation({
    mutationFn: () => {
      const body: ArticleIn = {
        section: form.section,
        slug: form.slug.trim(),
        translations: written(form.translations),
        ...(form.cover ? { cover_hash: form.cover.hash } : {}),
      };
      const key = saveKey.keyFor(JSON.stringify(body));
      return id === undefined ? createArticle(body, key) : updateArticle(id, body, key);
    },
    onSuccess: (a) => {
      saveKey.reset();
      saved(a);
      if (id === undefined) void navigate(`/articles/${a.id}`, { replace: true });
    },
    onError: (e) => {
      setError(articleErrorText(e));
    },
  });
  const act = useMutation({
    mutationFn: (verb: "publish" | "unpublish") => {
      const key = actKey.keyFor(`${id ?? ""}:${verb}`);
      return verb === "publish" ? publishArticle(id ?? "", key) : unpublishArticle(id ?? "", key);
    },
    onSuccess: (a) => {
      actKey.reset();
      setConfirm(null);
      saved(a);
      setForm(formOf(a));
    },
    onError: (e) => {
      setConfirm(null);
      setError(articleErrorText(e));
    },
  });

  const current = article.data;
  const renamed = current?.published_at != null && form.slug.trim() !== current.slug;
  const t = form.translations[tab] ?? BLANK;
  return (
    <section className="space-y-4">
      <PageHeader
        title={id === undefined ? "Новая статья" : titleOf(form)}
        back={{ to: "/articles", label: "Статьи" }}
        meta={
          current
            ? `${STATUS_LABEL[current.status]} · ${String(current.views)} просмотров · ${String(current.likes)} лайков`
            : undefined
        }
        actions={
          <>
            <Button
              disabled={save.isPending}
              onClick={() => {
                save.mutate();
              }}
            >
              {save.isPending ? "Сохраняем…" : "Сохранить"}
            </Button>
            {current ? (
              <Button
                variant="secondary"
                disabled={dirty || act.isPending}
                title={dirty ? "Сначала сохраните" : undefined}
                onClick={() => {
                  setConfirm(current.status === "published" ? "unpublish" : "publish");
                }}
              >
                {current.status === "published" ? "Снять с публикации" : "Опубликовать"}
              </Button>
            ) : null}
          </>
        }
      />
      {draft ? (
        <div className="border-border bg-surface flex flex-wrap items-center gap-3 rounded-lg border p-3 text-sm">
          <span>Есть несохранённые изменения из прошлого раза.</span>
          <Button
            size="sm"
            onClick={() => {
              setForm(draft);
              setDirty(true);
              setDraft(null);
            }}
          >
            Восстановить
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              writeDraft(id, null);
              setDraft(null);
            }}
          >
            Удалить
          </Button>
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="text-danger text-sm">
          {error}
        </p>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block space-y-1 text-sm">
          <span>Раздел</span>
          <Select
            value={form.section}
            onChange={(e) => {
              change({ section: SECTIONS.find((s) => s === e.target.value) ?? form.section });
            }}
          >
            {SECTIONS.map((s) => (
              <option key={s} value={s}>
                {SECTION_LABEL[s]}
              </option>
            ))}
          </Select>
        </label>
        <label className="block space-y-1 text-sm">
          <span>Адрес (slug)</span>
          <input
            className="border-border bg-surface w-full rounded-lg border px-3 py-2"
            value={form.slug}
            placeholder="top-budget-knives"
            onChange={(e) => {
              change({ slug: e.target.value.toLowerCase() });
            }}
          />
          {renamed ? (
            <span className="text-warning block">Старый адрес будет перенаправлять на новый.</span>
          ) : null}
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {form.cover ? (
          <img
            src={`${apiBase}/api/v1${form.cover.url}`}
            alt=""
            className="h-20 w-36 rounded-lg object-cover"
          />
        ) : (
          <span className="text-fg-muted text-sm">Обложки нет</span>
        )}
        <MediaButton
          label={form.cover ? "Заменить обложку" : "Загрузить обложку"}
          onUploaded={(m) => {
            change({ cover: m });
          }}
          onError={setError}
        />
      </div>
      <Tabs
        label="Язык"
        value={tab}
        onChange={setTab}
        items={LOCALES.map((l) => ({
          key: l,
          label: `${LOCALE_LABEL[l]}${form.translations[l]?.ready ? " ✓" : ""}`,
        }))}
      />
      <TranslationTab
        key={tab}
        value={t}
        onChange={(next) => {
          change({ translations: { ...form.translations, [tab]: next } });
        }}
        onError={setError}
      />
      {confirm ? (
        <ConfirmSheet
          title={confirm === "publish" ? "Опубликовать" : "Снять с публикации"}
          busy={act.isPending}
          onClose={() => {
            setConfirm(null);
          }}
        >
          <p className="mb-3 text-sm">
            {confirm === "publish"
              ? "Готовые переводы появятся на сайте."
              : "Статья пропадёт с сайта; адрес начнёт отвечать 404."}
          </p>
          <div className={CONFIRM_BUTTONS}>
            <Button
              variant="secondary"
              disabled={act.isPending}
              onClick={() => {
                setConfirm(null);
              }}
            >
              Отмена
            </Button>
            <Button
              disabled={act.isPending}
              onClick={() => {
                act.mutate(confirm);
              }}
            >
              {confirm === "publish" ? "Да, опубликовать" : "Да, снять"}
            </Button>
          </div>
        </ConfirmSheet>
      ) : null}
    </section>
  );
}
