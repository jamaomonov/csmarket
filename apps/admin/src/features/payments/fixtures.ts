/** Shared fixtures for the payments tests. Fake numbers only; never a real phone or account. */
import { type AdminPaymentDetail, type AdminPaymentRow } from "./api";

export const ROW: AdminPaymentRow = {
  id: "p-1",
  number: "P100001",
  purpose: "topup",
  provider: "click",
  amount_uzs: "50000",
  status: "succeeded",
  created_at: "2026-09-30T10:00:00Z",
  succeeded_at: "2026-09-30T10:01:00Z",
  user: { id: "u-1", display_name: "Ivan" },
};

/** A fake number that must never reach the screen unmasked. */
export const RAW_PHONE = "998901234567";

export const DETAIL: AdminPaymentDetail = {
  payment: { ...ROW, provider_ref: "ref-77" },
  topup: {
    number: "T100001",
    amount_uzs: "50000",
    status: "succeeded",
    expires_at: "2026-09-30T10:30:00Z",
    succeeded_at: "2026-09-30T10:01:00Z",
  },
  kassa: [
    {
      provider: "payme",
      external_id: "payme-abc",
      status: "performed",
      amount: "5000000",
      amount_unit: "tiyin",
      times: {
        created: "2026-09-30T10:00:00Z",
        performed: "2026-09-30T10:01:00Z",
        cancelled: null,
      },
      extra: { account: "T100001" },
    },
    {
      provider: "uzum",
      external_id: "uzum-xyz",
      status: "CONFIRMED",
      amount: "50000",
      amount_unit: "soum",
      times: { created: "2026-09-30T09:59:00Z", performed: null, cancelled: null },
      // `payment_source` and `raw_phone` are not allow-listed; `phone` is masked by the API.
      extra: {
        account: "T100001",
        source: "uzum_bank",
        phone: "+998••••••67",
        payment_source: RAW_PHONE,
        raw_phone: RAW_PHONE,
      },
    },
  ],
};
