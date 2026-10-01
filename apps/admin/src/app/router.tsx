/**
 * Top-level route table. `/login` and the Steam callback are public; everything
 * else sits behind `AuthGuard` (signed-in admin only).
 */
import { createBrowserRouter } from "react-router-dom";

import { Layout } from "./Layout";

import { AuditPage } from "@/features/audit/AuditPage";
import { AuthGuard } from "@/features/auth/AuthGuard";
import { LoginPage } from "@/features/auth/LoginPage";
import { SteamCallback } from "@/features/auth/SteamCallback";
import { CataloguePage } from "@/features/catalogue/CataloguePage";
import { PaymentDetail } from "@/features/payments/PaymentDetail";
import { PaymentsPage } from "@/features/payments/PaymentsPage";
import { UserCard } from "@/features/users/UserCard";
import { UsersPage } from "@/features/users/UsersPage";
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
          { path: "/catalogue", element: <CataloguePage /> },
          { path: "/users", element: <UsersPage /> },
          { path: "/users/:id", element: <UserCard /> },
          { path: "/payments", element: <PaymentsPage /> },
          { path: "/payments/:id", element: <PaymentDetail /> },
          { path: "/audit", element: <AuditPage /> },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
]);
