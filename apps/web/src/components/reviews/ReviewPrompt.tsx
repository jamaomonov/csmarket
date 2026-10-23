"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { usePathname } from "next/navigation";
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

/** Pages with their own sticky bottom bar («Купить», «Продать»): the strip waits off them. */
const OWN_BOTTOM_BAR = /(^|\/)(item|sell)(\/|$)/;
/** Pages where a buy, a sale or a top-up is under way: a deal that succeeds there waits on the
 * strip instead of covering them with a modal. */
const BUSY = /(^|\/)(item|sell|deposit)(\/|$)/;
/** Room the strip takes at the bottom of the page, so it never hides the page's last line. */
const STRIP_ROOM = "6rem";

/**
 * The site-wide review prompt (spec «Storefront»). The pending deal is read once per page load
 * and again on each socket nudge (`useOrderSocket` invalidates it). The deal pending at load
 * gets the bottom strip, once per visit; a deal that succeeds during the visit opens the modal
 * at once, on whatever page the user is — unless a payment is under way or another dialog is
 * open: then it waits on the strip. The strip stays off the deal's own page, which has its own
 * «Оставить отзыв».
 */
export function ReviewPrompt() {
  const { status } = useAuth();
  const qc = useQueryClient();
  const [visitStartMs] = useState(() => Date.now());
  const initial = useRef<{ number: string | null } | null>(null);
  const opened = useRef(new Set<string>());
  const [strip, setStrip] = useState<PendingDeal | null>(null);
  const [modal, setModal] = useState<{ deal: PendingDeal; rating: number | null } | null>(null);
  // An open modal is never swapped for the next deal: its «Спасибо» would vanish unread.
  const modalOpen = useRef(false);
  modalOpen.current = modal !== null;
  const pending = useQuery({
    queryKey: REVIEW_PENDING_KEY,
    queryFn: getPendingReview,
    enabled: status === "signed_in",
    staleTime: Infinity,
    retry: false,
  });
  const deal = pending.data?.deal ?? null;
  const pathname = usePathname();
  // read inside the effect, which runs on each read of the deal, not on navigation
  const pathRef = useRef(pathname);
  pathRef.current = pathname;
  const signedIn = status === "signed_in";

  // Sign-out: drop what was shown for the previous user and the cached deal (a new sign-in
  // starts a fresh visit for the prompt).
  useEffect(() => {
    if (signedIn) return;
    initial.current = null;
    opened.current.clear();
    setStrip(null);
    setModal(null);
    qc.removeQueries({ queryKey: REVIEW_PENDING_KEY });
  }, [signedIn, qc]);

  const showStrip =
    signedIn &&
    strip !== null &&
    !OWN_BOTTOM_BAR.test(pathname) &&
    !pathname.split("/").includes(strip.number);
  useEffect(() => {
    if (!showStrip) return;
    document.body.style.paddingBottom = STRIP_ROOM;
    return () => {
      document.body.style.paddingBottom = "";
    };
  }, [showStrip]);

  useEffect(() => {
    if (pending.data === undefined) return;
    if (initial.current === null) {
      initial.current = { number: deal?.number ?? null };
      if (deal !== null && takeStripTurn()) setStrip(deal);
      return;
    }
    const check = { initialNumber: initial.current.number, opened: opened.current, visitStartMs };
    if (!modalOpen.current && shouldOpenLive(deal, check)) {
      opened.current.add(deal.number);
      if (BUSY.test(pathRef.current) || document.querySelector("dialog[open]") !== null) {
        setStrip(deal);
        return;
      }
      setStrip(null);
      setModal({ deal, rating: null });
    }
    // every read counts, even an unchanged one: a deal held back by an open modal opens on the
    // next nudge after it closes
  }, [pending.data, pending.dataUpdatedAt, deal, visitStartMs]);

  const answer = useMutation({
    mutationFn: ({ deal: d, verb }: { deal: PendingDeal; verb: Answer }) =>
      (verb === "snooze" ? snoozeReview : dismissReview)(d.kind, d.number, mintReviewKey()),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: REVIEW_PENDING_KEY });
    },
  });

  return (
    <>
      {showStrip ? (
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
      {signedIn && modal !== null ? (
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
