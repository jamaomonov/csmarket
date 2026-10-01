import { Suspense } from "react";

import { SteamCallback } from "./SteamCallback";

export const dynamic = "force-dynamic";

export default function SteamCallbackPage() {
  return (
    <Suspense>
      <SteamCallback />
    </Suspense>
  );
}
