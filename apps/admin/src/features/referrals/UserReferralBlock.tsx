/** The user card's «Партнёрка»: who brought the account, or the way to make it a partner. */
import { Button } from "@csmarket/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { getUserReferral, PARTNERS_KEY } from "./api";
import { PartnerForm } from "./PartnerForm";

import { Modal } from "@/components/Modal";
import { Section } from "@/components/Section";
import { LINK } from "@/components/TextLink";

export function UserReferralBlock({ userId }: { userId: string }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const q = useQuery({
    queryKey: [...PARTNERS_KEY, "user", userId],
    queryFn: () => getUserReferral(userId),
  });
  if (q.data === undefined) return null;
  const { partner, is_partner } = q.data;
  return (
    <Section title="Партнёрка">
      <p className="text-sm">
        {partner === null ? (
          "Пришёл сам"
        ) : (
          <>
            Привёл:{" "}
            <Link to={`/partners/${partner.user_id}`} className={LINK}>
              {partner.display_name ?? "Без имени"} ({partner.code})
            </Link>
          </>
        )}
      </p>
      {is_partner ? (
        <Link to={`/partners/${userId}`} className={LINK}>
          Страница партнёра
        </Link>
      ) : (
        <Button
          variant="secondary"
          size="sm"
          className="self-start"
          onClick={() => {
            setOpen(true);
          }}
        >
          Сделать партнёром
        </Button>
      )}
      {open ? (
        <Modal
          title="Сделать партнёром"
          onClose={() => {
            setOpen(false);
          }}
        >
          <PartnerForm
            userId={userId}
            onDone={() => {
              setOpen(false);
              void qc.invalidateQueries({ queryKey: PARTNERS_KEY });
              void navigate(`/partners/${userId}`);
            }}
          />
        </Modal>
      ) : null}
    </Section>
  );
}
