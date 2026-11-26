// The only container (D21): it owns the conversation through the hook and hands plain values and
// callbacks to presentational components. It decides nothing about orders; the Dale button's
// state is `canPress`, the reducer's rule, shown as it is.
import type { Api } from "../api/client";
import { CancelButton } from "../components/CancelButton";
import { ChatPane } from "../components/ChatPane";
import { Composer } from "../components/Composer";
import { DaleButton } from "../components/DaleButton";
import { Notice } from "../components/Notice";
import { PendingStatus } from "../components/PendingStatus";
import { es } from "../i18n/es";
import { type ConversationState } from "../state/reducer";
import { useConversation } from "../state/useConversation";

/** The error to show above the composer, or null when the chat already shows it as a notice. */
function errorText(state: ConversationState): string | null {
  const error = state.error;
  if (error === null) return null;
  const last = state.chat.at(-1);
  if (
    last?.kind === "event" &&
    (last.event.type === "SystemNotice" || last.event.type === "OrderRejected") &&
    last.event.data.code === error.code
  ) {
    return null;
  }
  if (error.code === "conversation_not_found") return es.errors.conversation_not_found;
  if (error.message !== null) return error.message;
  return error.code === "network_error" || error.code === "malformed_response"
    ? es.errors[error.code]
    : es.errors.fallback;
}

export function ConversationContainer({ api }: { api?: Api }) {
  const { state, canPress, startedAt, start, send, press, cancel } = useConversation(api);
  const waiting = state.inFlight !== "none";
  const error = errorText(state);
  return (
    <section
      aria-labelledby="chat-title"
      className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]"
    >
      <div className="flex flex-col gap-4">
        <h2 id="chat-title" className="text-lg font-semibold">
          {es.chat.title}
        </h2>
        <ChatPane
          chat={state.chat}
          pendingProposalId={state.pendingProposalId}
          cancelledProposalIds={state.cancelledProposalIds}
        />
        {state.inFlight !== "none" && startedAt !== null && (
          <PendingStatus kind={state.inFlight} since={startedAt} />
        )}
        {error !== null && (
          <Notice kind="error" message={error}>
            {state.conversationGone && (
              <button
                type="button"
                disabled={waiting}
                onClick={start}
                className="mt-2 rounded-lg border-2 border-red-950 bg-white px-3 py-2 font-semibold text-red-950 hover:bg-red-100 focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-red-950 active:bg-red-200 disabled:cursor-not-allowed disabled:border-dashed disabled:border-slate-500 disabled:bg-slate-200 disabled:text-slate-700"
              >
                {es.newConversation}
              </button>
            )}
          </Notice>
        )}
        {/* A retired conversation takes nothing more: only "start a new one" leaves this state. */}
        <Composer disabled={waiting || state.conversationGone} onSend={send} />
        <div className="flex flex-wrap items-start gap-4">
          <DaleButton
            enabled={canPress}
            busy={waiting && state.pendingProposalId !== null}
            onPress={press}
          />
          {/* Cancel and Dale share one rule: the proposal one can reach, the other can discard. */}
          <CancelButton enabled={canPress} onCancel={cancel} />
        </div>
      </div>
    </section>
  );
}
