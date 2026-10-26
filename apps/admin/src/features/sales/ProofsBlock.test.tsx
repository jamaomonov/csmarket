import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PAYOUT_DETAIL } from "./fixtures";
import { payoutKey } from "./keys";
import {
  addProof,
  deleteProof,
  type PayoutDetail,
  type PayoutProof,
  proofFile,
} from "./payoutsApi";
import { ProofsBlock } from "./ProofsBlock";

import { ApiError } from "@/lib/api";

vi.mock("./payoutsApi", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  addProof: vi.fn(),
  deleteProof: vi.fn(),
  proofFile: vi.fn(),
}));

const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
const wrap = (node: ReactNode) => <QueryClientProvider client={qc}>{node}</QueryClientProvider>;

const PROOF: PayoutProof = {
  id: "p-1",
  name: "чек Humo.png",
  content_type: "image/png",
  size: 245_760,
  uploaded_by: { id: "admin-1", display_name: "Owner" },
  created_at: "2026-10-26T09:00:00Z",
  delete_until: "2999-01-01T00:00:00Z",
};
const PAID: PayoutDetail = {
  ...PAYOUT_DETAIL,
  can_decide: false,
  request: { ...PAYOUT_DETAIL.request, status: "paid" },
  proofs: [],
};

const pick = (file: File) => {
  fireEvent.change(screen.getByLabelText("Загрузить файл"), { target: { files: [file] } });
};

describe("ProofsBlock", () => {
  beforeEach(() => {
    vi.mocked(addProof).mockReset();
    vi.mocked(deleteProof).mockReset();
    vi.mocked(proofFile).mockReset();
  });

  it("stays away from a payout that is not paid and has no receipts", () => {
    const { container } = render(wrap(<ProofsBlock detail={PAYOUT_DETAIL} />));
    expect(container).toBeEmptyDOMElement();
  });

  it("uploads a picked file and shows it with who and when", async () => {
    vi.mocked(addProof).mockResolvedValue({ ...PAID, proofs: [PROOF] });
    render(wrap(<ProofsBlock detail={PAID} />));
    expect(screen.getByText(/Необязательно/)).toBeInTheDocument();
    const file = new File([new Uint8Array(10)], "чек Humo.png", { type: "image/png" });
    pick(file);
    await waitFor(() => {
      expect(addProof).toHaveBeenCalledWith(
        PAID.request.id,
        file,
        expect.stringMatching(/^admin-proof-/),
      );
    });
    expect(qc.getQueryData(payoutKey(PAID.request.id))).toEqual({ ...PAID, proofs: [PROOF] });
  });

  it("refuses a file over 5 MB before sending it", () => {
    render(wrap(<ProofsBlock detail={PAID} />));
    pick(new File([new Uint8Array(5 * 1024 * 1024 + 1)], "big.pdf", { type: "application/pdf" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Файл больше 5 МБ.");
    expect(addProof).not.toHaveBeenCalled();
  });

  it("says why the API refused the file", async () => {
    vi.mocked(addProof).mockRejectedValue(
      new ApiError(422, "Unprocessable", { code: "proof_type", detail: "x" }),
    );
    render(wrap(<ProofsBlock detail={PAID} />));
    pick(new File(["<svg/>"], "x.svg", { type: "image/svg+xml" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Подходят только JPG, PNG, WebP или PDF.",
    );
  });

  it("lists receipts, hides the upload at three and deletes within the window", async () => {
    const old = { ...PROOF, id: "p-2", name: "старый.pdf", delete_until: null };
    const three = { ...PAID, proofs: [PROOF, old, { ...old, id: "p-3" }] };
    vi.mocked(deleteProof).mockResolvedValue({ ...PAID, proofs: [old] });
    render(wrap(<ProofsBlock detail={three} />));
    expect(screen.queryByLabelText("Загрузить файл")).toBeNull();
    expect(screen.getAllByText(/240 КБ/)).toHaveLength(3);
    expect(screen.getAllByText(/Owner/)).toHaveLength(3);
    expect(screen.getAllByRole("button", { name: /Удалить/ })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Удалить чек Humo.png" }));
    fireEvent.click(screen.getByRole("button", { name: "Да, удалить" }));
    await waitFor(() => {
      expect(deleteProof).toHaveBeenCalledWith(PAID.request.id, "p-1", expect.any(String));
    });
  });

  it("opens a receipt from the API, never by a public link", async () => {
    const win = { location: { href: "" }, close: vi.fn() };
    vi.spyOn(window, "open").mockReturnValue(win as unknown as Window);
    URL.createObjectURL = vi.fn(() => "blob:receipt");
    URL.revokeObjectURL = vi.fn();
    vi.mocked(proofFile).mockResolvedValue(new Blob(["x"], { type: "image/png" }));
    render(wrap(<ProofsBlock detail={{ ...PAID, proofs: [PROOF] }} />));
    fireEvent.click(screen.getByRole("button", { name: "чек Humo.png" }));
    await waitFor(() => {
      expect(win.location.href).toBe("blob:receipt");
    });
    expect(proofFile).toHaveBeenCalledWith(PAID.request.id, "p-1");
  });
});
