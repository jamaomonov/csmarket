/** The closed sets the payments API filters by (kept apart from `api.ts` so tests can mock that). */
export const PAYMENT_STATUSES = [
  "created",
  "pending",
  "succeeded",
  "failed",
  "cancelled",
  "refunded",
] as const;
export type PaymentStatus = (typeof PAYMENT_STATUSES)[number];

export const PAYMENT_PROVIDERS = ["click", "payme", "uzum", "mock"] as const;
export type PaymentProvider = (typeof PAYMENT_PROVIDERS)[number];

export const PAYMENT_PURPOSES = ["topup", "order"] as const;
export type PaymentPurpose = (typeof PAYMENT_PURPOSES)[number];
