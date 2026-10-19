/** TanStack Query keys of the «P2P» pages. */
export const P2P_KEY = ["admin", "p2p"] as const;
export const cardsKey = [...P2P_KEY, "cards"] as const;
export const incomingKey = (amount: string, result: string) =>
  [...P2P_KEY, "incoming", amount, result] as const;
export const requestsKey = (status: string) => [...P2P_KEY, "requests", status] as const;
export const settingsKey = [...P2P_KEY, "settings"] as const;
