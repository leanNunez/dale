import { useEffect, useId, useRef, useState } from "react";

import { es } from "../i18n/es";

/** The most the host takes in one message (contract v1 `SendMessage.text`). */
const MAX_LENGTH = 2000;

interface Props {
  /** True while a request is running: nothing is sent until the host answers. */
  disabled: boolean;
  /** Resolves true once the host took the message; false when it did not, and the text stays. */
  onSend: (text: string) => Promise<boolean>;
}

/** Sends the customer's words to the model. Whatever is typed here can never confirm an order. */
export function Composer({ disabled, onSend }: Props) {
  const [text, setText] = useState("");
  const labelId = useId();
  const hintId = useId();
  const sendable = !disabled && text.trim() !== "";
  // An IME composition is still open: its Enter picks a candidate and must not send.
  const composing = useRef(false);
  const closing = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(closing.current), []);

  function submit() {
    if (!sendable) return;
    const typed = text;
    // The text leaves the field only once the host took it; words typed meanwhile stay.
    onSend(typed.trim()).then(
      (accepted) => {
        if (accepted) setText((now) => (now === typed ? "" : now));
      },
      () => undefined,
    );
  }

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <label id={labelId} htmlFor={`${labelId}-field`} className="text-sm font-semibold">
        {es.composer.label}
      </label>
      <div className="flex items-end gap-2">
        <textarea
          id={`${labelId}-field`}
          value={text}
          rows={2}
          maxLength={MAX_LENGTH}
          aria-describedby={hintId}
          onChange={(event) => setText(event.target.value)}
          onCompositionStart={() => {
            clearTimeout(closing.current);
            composing.current = true;
          }}
          onCompositionEnd={() => {
            // Safari ends the composition before the Enter that confirmed it, in the same tick
            // and with `isComposing` already false: the flag drops one tick later.
            closing.current = setTimeout(() => {
              composing.current = false;
            }, 0);
          }}
          onKeyDown={(event) => {
            // Enter sends and Shift+Enter breaks the line, unless the key belongs to an IME: Chrome
            // flags it `isComposing` or gives it keyCode 229, Safari sends it just after `compositionend`.
            const ime =
              composing.current ||
              event.nativeEvent.isComposing ||
              event.nativeEvent.keyCode === 229;
            if (event.key === "Enter" && !event.shiftKey && !ime) {
              event.preventDefault();
              submit();
            }
          }}
          className="min-h-12 flex-1 resize-y rounded-lg border-2 border-slate-500 bg-white px-3 py-2 text-slate-900 focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
        />
        <button
          type="submit"
          disabled={!sendable}
          className="rounded-lg border-2 border-slate-900 bg-white px-4 py-2 font-semibold text-slate-900 hover:bg-slate-100 focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-slate-900 active:bg-slate-200 disabled:cursor-not-allowed disabled:border-dashed disabled:border-slate-500 disabled:bg-slate-200 disabled:text-slate-700"
        >
          {es.composer.send}
        </button>
      </div>
      <p id={hintId} className="text-sm text-slate-700">
        {es.composer.hint}
      </p>
    </form>
  );
}
