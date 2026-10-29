/**
 * Top-level route table. `/login` and the Steam callback are public; everything
 * else sits behind `AuthGuard` (signed-in admin only).
 */
import { lazy, Suspense } from "react";
import { Navigate, createBrowserRouter } from "react-router-dom";

import { Layout } from "./Layout";
import { OrdersRedirect } from "./OrdersRedirect";

import { ApiKeyRedirect } from "@/features/apiKeys/ApiKeyCard";
import { ArticleEditor } from "@/features/articles/ArticleEditor";
import { ArticlesPage } from "@/features/articles/ArticlesPage";
import { AuditPage } from "@/features/audit/AuditPage";
import { AuthGuard } from "@/features/auth/AuthGuard";
import { LoginPage } from "@/features/auth/LoginPage";
import { SteamCallback } from "@/features/auth/SteamCallback";
import { CataloguePage } from "@/features/catalogue/CataloguePage";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { OrderDetail } from "@/features/orders/OrderDetail";
import { P2PPage } from "@/features/p2p/P2PPage";
import { FeeSettingsPage } from "@/features/payments/FeeSettingsPage";
import { HoldsPage } from "@/features/payments/HoldsPage";
import { PaymentDetail } from "@/features/payments/PaymentDetail";
import { PaymentsPage } from "@/features/payments/PaymentsPage";
import { PricingPage } from "@/features/pricing/PricingPage";
import { PartnerDetailRoute } from "@/features/referrals/PartnerDetail";
import { PartnersPage } from "@/features/referrals/PartnersPage";
import { ReviewsPage } from "@/features/reviews/ReviewsPage";
import { PayoutDetail } from "@/features/sales/PayoutDetail";
import { PayoutsPage } from "@/features/sales/PayoutsPage";
import { PriceCheckPage } from "@/features/sales/PriceCheckPage";
import { ReconciliationPage } from "@/features/sales/ReconciliationPage";
import { SaleDetail } from "@/features/sales/SaleDetail";
import { SaleSettingsPage } from "@/features/sales/SaleSettingsPage";
import { SalesPage } from "@/features/sales/SalesPage";
import { SellBlocksPage } from "@/features/sales/SellBlocksPage";
import { TradesPage } from "@/features/trades/TradesPage";
import { UserCard } from "@/features/users/UserCard";
import { UsersPage } from "@/features/users/UsersPage";
import { NotFoundPage } from "@/routes/NotFound";

// recharts lives in this chunk only (ADR 0020): the other pages do not load it.
const AnalyticsPage = lazy(async () => ({
  default: (await import("@/features/analytics/AnalyticsPage")).AnalyticsPage,
}));

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
          {
            path: "/analytics",
            element: (
              <Suspense fallback={<p className="text-fg-muted">Загрузка…</p>}>
                <AnalyticsPage />
              </Suspense>
            ),
          },
          { path: "/catalogue", element: <CataloguePage /> },
          { path: "/pricing", element: <PricingPage /> },
          { path: "/users", element: <UsersPage /> },
          { path: "/users/:id", element: <UserCard /> },
          { path: "/orders", element: <OrdersRedirect /> },
          { path: "/orders/:number", element: <OrderDetail /> },
          { path: "/trades", element: <TradesPage /> },
          { path: "/payments", element: <PaymentsPage /> },
          { path: "/payments/:id", element: <PaymentDetail /> },
          { path: "/payment-holds", element: <HoldsPage /> },
          { path: "/payment-settings", element: <FeeSettingsPage /> },
          { path: "/p2p", element: <P2PPage /> },
          { path: "/audit", element: <AuditPage /> },
          { path: "/payouts", element: <PayoutsPage /> },
          { path: "/payouts/:id", element: <PayoutDetail /> },
          { path: "/sales", element: <SalesPage /> },
          { path: "/sales/reconciliation", element: <ReconciliationPage /> },
          { path: "/sales/price-check", element: <PriceCheckPage /> },
          { path: "/sales/:number", element: <SaleDetail /> },
          { path: "/sale-settings", element: <SaleSettingsPage /> },
          { path: "/sale-blocks", element: <SellBlocksPage /> },
          { path: "/reviews", element: <ReviewsPage /> },
          { path: "/partners", element: <PartnersPage /> },
          { path: "/partners/:userId", element: <PartnerDetailRoute /> },
          { path: "/articles", element: <ArticlesPage /> },
          { path: "/articles/new", element: <ArticleEditor /> },
          { path: "/articles/:id", element: <ArticleEditor /> },
          { path: "/api-keys", element: <Navigate to="/users?has_api_key=true" replace /> },
          { path: "/api-keys/:id", element: <ApiKeyRedirect /> },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
]);
