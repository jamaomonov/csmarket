/**
 * Top-level route table. `/login` and the Steam callback are public; everything
 * else sits behind `AuthGuard` (signed-in admin only).
 */
import { createBrowserRouter } from "react-router-dom";

import { Layout } from "./Layout";

import { AuthGuard } from "@/features/auth/AuthGuard";
import { LoginPage } from "@/features/auth/LoginPage";
import { SteamCallback } from "@/features/auth/SteamCallback";
import { DashboardPage } from "@/routes/Dashboard";
import { NotFoundPage } from "@/routes/NotFound";

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  { path: "/auth/steam/callback", element: <SteamCallback /> },
  {
    element: <AuthGuard />,
    children: [
      {
        element: <Layout />,
        children: [
          { path: "/", element: <DashboardPage /> },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
]);
