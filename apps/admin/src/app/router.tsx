/** Top-level route table. M1 wraps everything below `/login` in an `AuthGuard`. */
import { createBrowserRouter } from "react-router-dom";

import { Layout } from "./Layout";

import { DashboardPage } from "@/routes/Dashboard";
import { NotFoundPage } from "@/routes/NotFound";

export const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <DashboardPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
