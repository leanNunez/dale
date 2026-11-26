import type { StoredOrder, VerdictIssuedEvent } from "../contract";
import { es } from "../i18n/es";
import { dateLabel, pesos, shortId } from "../i18n/format";
import { nameFinder, type ChatItem } from "../state/reducer";

interface Props {
  verdicts: VerdictIssuedEvent[];
  /** Where the product names come from: the summary the page showed for each order's proposal. */
  chat: ChatItem[];
}

interface OrderProps {
  order: StoredOrder;
  chat: ChatItem[];
  /** The proposal the latest verdict judged: an order of another proposal says so. */
  subject: string | null;
}

function StoredOrderView({ order, chat, subject }: OrderProps) {
  const nameOf = nameFinder(chat, order.proposal_id);
  return (
    <li className="rounded-lg border-2 border-slate-700 bg-white p-3 text-sm">
      <h3 className="font-semibold text-slate-900">
        {es.panels.order.order} {shortId(order.order_id)}
      </h3>
      <p className="text-slate-700">
        {order.proposal_id === subject
          ? `${es.panels.order.fromProposal}: ${shortId(order.proposal_id)}`
          : `${es.panels.order.otherProposal}: ${shortId(order.proposal_id)}`}
      </p>
      <ul className="my-2 flex flex-col gap-1">
        {order.lines.map((line, index) => (
          <li key={`${line.product_id}-${index}`} className="text-slate-900">
            <span className="font-semibold">{line.quantity} ×</span>{" "}
            {nameOf(line.product_id) ?? shortId(line.product_id)}
            <span className="block text-slate-700">
              {pesos(line.unit_price.cents)} {es.panels.order.each} = {pesos(line.line_total.cents)}
            </span>
          </li>
        ))}
      </ul>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
        <dt className="text-slate-700">{es.panels.order.delivery}</dt>
        <dd className="font-medium text-slate-900">{dateLabel(order.delivery_date)}</dd>
        <dt className="text-slate-700">{es.panels.order.total}</dt>
        <dd className="font-semibold text-slate-900">{pesos(order.total.cents)}</dd>
      </dl>
    </li>
  );
}

/** What to say when the latest verdict carries no stored order, true to what the verifier did. */
function absence(latest: VerdictIssuedEvent["data"] | undefined): string {
  if (latest === undefined) return es.panels.order.noVerdict;
  // An unverifiable run did not read the base: "no order stored" would be a claim nobody made.
  return latest.verdict === "unverifiable" ? es.panels.order.unreadable : es.panels.order.none;
}

/**
 * The order as the verifier read it in the database (D19), never as the chat showed it. It is
 * what the latest verdict read, whatever that verdict's subject: a press with nothing pending
 * names none and still reads the database, and an unverifiable one read nothing, so no order of
 * an older read is kept on screen.
 */
export function OrderPanel({ verdicts, chat }: Props) {
  const latest = verdicts.at(-1)?.data;
  const subject = latest?.subject_proposal_id ?? null;
  const orders = [...(latest?.stored_orders ?? [])].sort(
    (a, b) => Number(b.proposal_id === subject) - Number(a.proposal_id === subject),
  );
  return (
    <section
      aria-labelledby="order-title"
      className="rounded-lg border border-slate-300 bg-slate-50 p-4"
    >
      <h2 id="order-title" className="mb-1 text-lg font-semibold">
        {es.panels.order.title}
      </h2>
      <p className="mb-2 text-sm text-slate-700">{es.panels.order.lead}</p>
      {orders.length === 0 ? (
        <p className="text-sm text-slate-900">{absence(latest)}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {orders.map((order) => (
            <StoredOrderView key={order.order_id} order={order} chat={chat} subject={subject} />
          ))}
        </ul>
      )}
    </section>
  );
}
