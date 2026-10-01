import { Button } from "@csmarket/ui";

import { useAuthStore } from "./authStore";

interface ForbiddenProps {
  suspended: boolean;
}

export function Forbidden({ suspended }: ForbiddenProps) {
  const signOut = useAuthStore((s) => s.signOut);
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 text-center">
      <h1 className="text-2xl font-bold">Нет доступа</h1>
      <p className="text-fg-muted">
        {suspended ? "Этот аккаунт заблокирован." : "Этот аккаунт Steam не администратор."}
      </p>
      <Button variant="secondary" onClick={signOut}>
        Выйти
      </Button>
    </div>
  );
}
