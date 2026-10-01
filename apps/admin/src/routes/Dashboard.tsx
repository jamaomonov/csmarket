import { Link } from "react-router-dom";

export function DashboardPage() {
  return (
    <section>
      <h1 className="text-2xl font-bold">Дашборд</h1>
      <p className="text-fg-muted mt-2">Вход по Steam работает.</p>
      <p className="mt-2">
        Каталог, курс и обновление цен — в разделе{" "}
        <Link to="/catalogue" className="text-accent underline">
          «Каталог»
        </Link>
        .
      </p>
    </section>
  );
}
