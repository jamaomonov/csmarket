import { Button } from "@csmarket/ui";
import { Link } from "react-router-dom";

/** Explicit 404 — a typo must not look like "you are already home". */
export function NotFoundPage() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center text-center">
      <h1 className="text-2xl font-bold">Страница не найдена</h1>
      <p className="text-fg-muted mt-2">Такого адреса нет в админке. Проверьте ссылку.</p>
      <Link to="/" className="mt-6">
        <Button type="button">На дашборд</Button>
      </Link>
    </div>
  );
}
