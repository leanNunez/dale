// The page's view of contract v1: the generated types under their readable names. The shapes are
// generated (npm run gen:contract); only the aliases below are authored.
import type { ResponseEnvelope } from "./generated/ResponseEnvelope";

export type { CancelProposal } from "./generated/CancelProposal";
export type { ContractInfo, DemoInfo } from "./generated/ContractInfo";
export type { PressDale } from "./generated/PressDale";
export type { SendMessage } from "./generated/SendMessage";
export type { StartConversation } from "./generated/StartConversation";
export type {
  AssistantTextEvent,
  ErrorBody,
  ErrorCode,
  HandoffNoticeEvent,
  OrderConfirmedEvent,
  OrderRejectedEvent,
  ProposalSummaryEvent,
  ResponseEnvelope,
  StoredOrder,
  SystemNoticeEvent,
  ToolCalledEvent,
  VerdictIssuedEvent,
} from "./generated/ResponseEnvelope";
export { COMPONENTS } from "./generated/components";
export type { ComponentName, EventType } from "./generated/components";

/** Every event the host emits, discriminated on `type`. */
export type WebEvent = ResponseEnvelope["events"][number];
export type ErrorCodeName = NonNullable<ResponseEnvelope["error"]>["code"];
