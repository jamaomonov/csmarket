import { createNavigation } from "next-intl/navigation";

import { routing } from "./routing";

/** Locale-aware `Link` and friends: hrefs keep the visitor's language. */
export const { Link, redirect, permanentRedirect, usePathname, useRouter, getPathname } =
  createNavigation(routing);
