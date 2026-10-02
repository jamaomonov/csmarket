"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { useOrderSocket } from "@/hooks/useOrderSocket";
import { AuthProvider } from "@/lib/auth";

interface ProvidersProps {
  children: ReactNode;
}

export function Providers({ children }: ProvidersProps) {
  const [client] = useState(
    () => new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false } } }),
  );
  return (
    <QueryClientProvider client={client}>
      <AuthProvider>
        <OrderSocketMount />
        {children}
      </AuthProvider>
    </QueryClientProvider>
  );
}

/** Opens the order socket for a signed-in buyer (it needs the auth context). */
function OrderSocketMount(): null {
  useOrderSocket();
  return null;
}
