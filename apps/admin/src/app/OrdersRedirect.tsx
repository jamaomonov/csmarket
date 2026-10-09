import { Navigate, useLocation } from "react-router-dom";

/** The old `/orders` list now lives at `/trades`; `?q=` and any other params travel along. */
export function OrdersRedirect() {
  const { search } = useLocation();
  return <Navigate to={{ pathname: "/trades", search }} replace />;
}
