import { useEffect, useRef } from "react";

import { proposalStatus, type ChatEvent, type ChatItem } from "../state/reducer";
import { es } from "../i18n/es";
import { ChatText } from "./ChatText";
import { HandoffNotice } from "./HandoffNotice";
import { Notice } from "./Notice";
import { OrderConfirmation } from "./OrderConfirmation";
import { OrderSummary } from "./OrderSummary";

interface Props {
  chat: ChatItem[];
  /** The host's pending proposal id: the summary with this id is the one Dale would confirm. */
  pendingProposalId: string | null;
  /** Proposals this page cancelled and the host cleared. */
  cancelledProposalIds: string[];
}

/** A product's name from the summary the page showed for that proposal, if it showed one. */
function nameFinder(chat: ChatItem[], proposalId: string) {
  return (productId: string): string | null => {
    for (const item of chat) {
      if (item.kind !== "event" || item.event.type !== "ProposalSummary") continue;
      if (item.event.data.proposal_id !== proposalId) continue;
      const line = item.event.data.lines.find((candidate) => candidate.product_id === productId);
      if (line) return line.name;
    }
    return null;
  };
}

function EventView({
  event,
  chat,
  pendingProposalId,
  cancelledProposalIds,
}: { event: ChatEvent } & Props) {
  switch (event.type) {
    case "AssistantText":
      return <ChatText who="assistant" text={event.data.text} />;
    case "ProposalSummary":
      return (
        <OrderSummary
          data={event.data}
          status={proposalStatus(
            { chat, pendingProposalId, cancelledProposalIds },
            event.data.proposal_id,
          )}
        />
      );
    case "OrderConfirmed":
      return (
        <OrderConfirmation data={event.data} nameOf={nameFinder(chat, event.data.proposal_id)} />
      );
    case "OrderRejected":
    case "SystemNotice":
      // The log announces what is added to it, so a notice here adds no live region of its own.
      return <Notice kind="notice" message={event.data.message} live={false} />;
    case "HandoffNotice":
      return <HandoffNotice message={event.data.message} />;
  }
}

/** The conversation in the order it happened: the customer's lines and the host's events. */
export function ChatPane({ chat, pendingProposalId, cancelledProposalIds }: Props) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const pane = end.current;
    if (pane) pane.scrollTop = pane.scrollHeight;
  }, [chat.length]);
  return (
    <div
      ref={end}
      role="log"
      aria-label={es.chat.title}
      className="flex min-h-64 flex-1 flex-col gap-3 overflow-y-auto rounded-lg border border-slate-300 bg-slate-50 p-4"
    >
      {chat.length === 0 && <p className="text-slate-700">{es.chat.empty}</p>}
      {chat.map((item) =>
        item.kind === "customer" ? (
          <ChatText key={`customer-${item.id}`} who="customer" text={item.text} />
        ) : (
          <EventView
            key={`event-${item.event.seq}`}
            event={item.event}
            chat={chat}
            pendingProposalId={pendingProposalId}
            cancelledProposalIds={cancelledProposalIds}
          />
        ),
      )}
    </div>
  );
}
