"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { ReviewDialog } from "./ReviewDialog";
import { ReviewStrip } from "./ReviewStrip";

import { useAuth } from "@/lib/auth";
import {
  dismissReview,
  getPendingReview,
  mintReviewKey,
  REVIEW_PENDING_KEY,
  shouldOpenLive,
  snoozeReview,
  takeStripTurn,
  type PendingDeal,
} from "@/lib/reviews";

type Answer = "snooze" | "dismiss";

/**
 * The site-wide review prompt (spec «Storefront»). The pending deal is read once per page load
 * and again on each socket nudge (`useOrderSocket` invalidates it). The deal pending at load
 * gets the bottom strip, once per visit; a deal that succeeds during the visit opens the modal
 * at once, on whatever page the user is.
 */
export function ReviewPrompt() {
  const { status } = useAuth();
  const qc = useQueryClient();
  const [visitStartMs] = useState(() => Date.now());
  const initial = useRef<{ number: string | null } | null>(null);
  const opened = useRef(new Set<string>());
  const [strip, setStrip] = useState<PendingDeal | null>(null);
  const [modal, setModal] = useState<{ deal: PendingDeal; rating: number | null } | null>(null);
  const pending = useQuery({
    queryKey: REVIEW_PENDING_KEY,
    queryFn: getPendingReview,
    enabled: status === "signed_in",
    staleTime: Infinity,
    retry: false,
  });
  const deal = pending.data?.deal ?? null;

  useEffect(() => {
    if (pending.data === undefined) return;
    if (initial.current === null) {
      initial.current = { number: deal?.number ?? null };
      if (deal !== null && takeStripTurn()) setStrip(deal);
      return;
    }
    const check = { initialNumber: initial.current.number, opened: opened.current, visitStartMs };
    if (shouldOpenLive(deal, check)) {
      opened.current.add(deal.number);
      setStrip(null);
      setModal({ deal, rating: null });
    }
  }, [pending.data, deal, visitStartMs]);

  const answer = useMutation({
    mutationFn: ({ deal: d, verb }: { deal: PendingDeal; verb: Answer }) =>
      (verb === "snooze" ? snoozeReview : dismissReview)(d.kind, d.number, mintReviewKey()),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: REVIEW_PENDING_KEY });
    },
  });

  return (
    <>
      {strip !== null ? (
        <ReviewStrip
          deal={strip}
          onRate={(rating) => {
            opened.current.add(strip.number);
            setStrip(null);
            setModal({ deal: strip, rating });
          }}
          onLater={() => {
            setStrip(null);
            answer.mutate({ deal: strip, verb: "snooze" });
          }}
          onDismiss={() => {
            setStrip(null);
            answer.mutate({ deal: strip, verb: "dismiss" });
          }}
        />
      ) : null}
      {modal !== null ? (
        <ReviewDialog
          deal={modal.deal}
          initialRating={modal.rating}
          onClose={() => {
            setModal(null);
          }}
          onLater={() => {
            answer.mutate({ deal: modal.deal, verb: "snooze" });
            setModal(null);
          }}
        />
      ) : null}
    </>
  );
}
