import type { OrderConfirmedEvent } from "../contract";
import { dateLabel, pesos, shortId } from "../i18n/format";
import { es } from "../i18n/es";

interface Props {
  data: OrderConfirmedEvent["data"];
  /** The product's name from the proposal the page showed, or null: the short id shows instead. */
  nameOf: (productId: string) => string | null;
}

/** What the host says it confirmed. The database's own record is the verdict's, not this one. */
export function OrderConfirmation({ data, nameOf }: Props) {
  return (
    <article
      aria-label={es.confirmation.title}
      className="rounded-lg border-2 border-emerald-800 bg-emerald-50 p-4"
    >
      <h3 className="text-base font-semibold text-emerald-950">
        <span aria-hidden="true">✔ </span>
        {es.confirmation.title}
      </h3>
      <p className="mb-3 text-sm text-slate-900">{data.message}</p>
      <ul className="mb-3 flex flex-col gap-1">
        {data.lines.map((line, index) => (
          <li key={`${line.product_id}-${index}`} className="text-sm text-slate-900">
            <span className="font-semibold">{line.quantity} ×</span>{" "}
            {nameOf(line.product_id) ?? shortId(line.product_id)}: {pesos(line.line_total.cents)}
          </li>
        ))}
      </ul>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-slate-700">{es.confirmation.order}</dt>
        <dd className="font-medium text-slate-900">{shortId(data.order_id)}</dd>
        <dt className="text-slate-700">{es.confirmation.delivery}</dt>
        <dd className="font-medium text-slate-900">{dateLabel(data.delivery_date)}</dd>
        <dt className="text-slate-700">{es.confirmation.total}</dt>
        <dd className="font-semibold text-slate-900">{pesos(data.total.cents)}</dd>
      </dl>
    </article>
  );
}
