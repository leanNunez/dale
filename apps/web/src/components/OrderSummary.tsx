import type { ProposalSummaryEvent } from "../contract";
import { dateLabel, pesos } from "../i18n/format";
import { es } from "../i18n/es";
import type { ProposalStatus } from "../state/reducer";

interface Props {
  data: ProposalSummaryEvent["data"];
  /** Where the proposal stands on this page; only a current one can be confirmed by Dale. */
  status: ProposalStatus;
}

/** The stored proposal as the host sent it, and where it stands: current, confirmed, cancelled or older. */
export function OrderSummary({ data, status }: Props) {
  const current = status === "current";
  return (
    <article
      aria-label={es.summary.title}
      className={
        current
          ? "rounded-lg border-2 border-slate-900 bg-white p-4"
          : "rounded-lg border border-dashed border-slate-400 bg-slate-100 p-4"
      }
    >
      <h3 className="text-base font-semibold text-slate-900">{es.summary.title}</h3>
      <div className="mb-3 text-sm text-slate-700">
        <p className="font-medium">{es.summary.status[status]}</p>
        {current && <p>{es.summary.notConfirmed}</p>}
      </div>
      <ul className="mb-3 flex flex-col gap-2">
        {data.lines.map((line, index) => (
          <li key={`${line.product_id}-${index}`} className="text-sm text-slate-900">
            <span className="font-semibold">{line.quantity} ×</span> {line.name}
            <span className="block text-slate-700">
              {pesos(line.unit_price.cents)} {es.summary.each} = {pesos(line.line_total.cents)}
            </span>
          </li>
        ))}
      </ul>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-slate-700">{es.summary.delivery}</dt>
        <dd className="font-medium text-slate-900">{dateLabel(data.delivery_date)}</dd>
        <dt className="text-slate-700">{es.summary.total}</dt>
        <dd className="font-semibold text-slate-900">{pesos(data.total.cents)}</dd>
      </dl>
    </article>
  );
}
