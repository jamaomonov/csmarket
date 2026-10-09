/**
 * Top-level route table. `/login` and the Steam callback are public; everything
 * else sits behind `AuthGuard` (signed-in admin only).
 */
import { createBrowserRouter } from "react-router-dom";

import { Layout } from "./Layout";
import { OrdersRedirect } from "./OrdersRedirect";

import { ApiKeyCard } from "@/features/apiKeys/ApiKeyCard";
import { ApiKeysPage } from "@/features/apiKeys/ApiKeysPage";
import { AuditPage } from "@/features/audit/AuditPage";
import { AuthGuard } from "@/features/auth/AuthGuard";
import { LoginPage } from "@/features/auth/LoginPage";
import { SteamCallback } from "@/features/auth/SteamCallback";
import { CataloguePage } from "@/features/catalogue/CataloguePage";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { OrderDetail } from "@/features/orders/OrderDetail";
import { PaymentDetail } from "@/features/payments/PaymentDetail";
import { PaymentsPage } from "@/features/payments/PaymentsPage";
import { PricingPage } from "@/features/pricing/PricingPage";
import { PayoutDetail } from "@/features/sales/PayoutDetail";
import { PayoutsPage } from "@/features/sales/PayoutsPage";
import { SaleDetail } from "@/features/sales/SaleDetail";
import { SaleSettingsPage } from "@/features/sales/SaleSettingsPage";
import { SalesPage } from "@/features/sales/SalesPage";
import { TradesPage } from "@/features/trades/TradesPage";
import { UserCard } from "@/features/users/UserCard";
import { UsersPage } from "@/features/users/UsersPage";
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
          { path: "/pricing", element: <PricingPage /> },
          { path: "/users", element: <UsersPage /> },
          { path: "/users/:id", element: <UserCard /> },
          { path: "/orders", element: <OrdersRedirect /> },
          { path: "/orders/:number", element: <OrderDetail /> },
          { path: "/trades", element: <TradesPage /> },
          { path: "/payments", element: <PaymentsPage /> },
          { path: "/payments/:id", element: <PaymentDetail /> },
          { path: "/audit", element: <AuditPage /> },
          { path: "/payouts", element: <PayoutsPage /> },
          { path: "/payouts/:id", element: <PayoutDetail /> },
          { path: "/sales", element: <SalesPage /> },
          { path: "/sales/:number", element: <SaleDetail /> },
          { path: "/sale-settings", element: <SaleSettingsPage /> },
          { path: "/api-keys", element: <ApiKeysPage /> },
          { path: "/api-keys/:id", element: <ApiKeyCard /> },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
]);
