/** TanStack Query keys of the analytics page. */
import { type Channel } from "./api";

export const businessKey = (since: string, until: string, channel: Channel) =>
  ["admin", "analytics", "business", since, until, channel] as const;
export const calendarKey = (month: string, channel: Channel) =>
  ["admin", "analytics", "calendar", month, channel] as const;
export const lossesKey = (since: string, until: string, channel: Channel) =>
  ["admin", "analytics", "losses", since, until, channel] as const;
