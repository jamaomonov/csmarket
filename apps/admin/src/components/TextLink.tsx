/**
 * A link that looks like one (admin UX audit §8): numbers and names in the accent colour,
 * underlined on hover. Rows that open on a click still give their number a real link.
 */
import { type ReactNode } from "react";
import { Link } from "react-router-dom";

/** The accent link classes, for a `<Link>` or an `<a>` that cannot be a `TextLink`. */
export const LINK = "text-accent hover:underline underline-offset-2";

interface TextLinkProps {
  to: string;
  children: ReactNode;
  /** An order, payment or sale number: monospace, so O and 0 never mix. */
  number?: boolean;
  className?: string;
}

export function TextLink({ to, children, number = false, className = "" }: TextLinkProps) {
  return (
    <Link to={to} className={`${LINK} ${number ? "font-mono" : ""} ${className}`}>
      {children}
    </Link>
  );
}
