"""The terminal's input (design §8, D5; R4). Enter sends the typed text as `CustomerText`, so a
typed "dale" is only text (S4.2). F2 is bound outside the text buffer and only while a proposal
is pending: it emits `KeyPress(DALE, proposal_id)` and never submits the buffer; with nothing
pending it does nothing (S4.3). F3 drops the pending proposal and confirms nothing.

An F2 counts only when the customer pressed it at a prompt that already showed the proposal
(B83). Before each prompt, input that arrived while a turn, a confirm or the verifier ran is
thrown away. At the prompt, F2 is ignored when it comes in one input batch with other keys (a
paste, a burst, keys typed ahead), within `PASTE_QUIET` seconds after a bracketed paste ended,
and while the buffer holds text, which stays where it is."""

import time
from collections.abc import Callable
from os import isatty
from termios import TCIFLUSH, tcflush

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.input import Input
from prompt_toolkit.input.typeahead import clear_typeahead
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.key_binding import KeyPress as Stroke
from prompt_toolkit.key_binding.key_processor import KeyProcessor
from prompt_toolkit.keys import Keys
from prompt_toolkit.output import Output

from dale.channels.terminal.pending import Pending
from dale.shared.customer_input import CustomerInput, CustomerText, Key, KeyPress

PROMPT = "vos> "
PASTE_QUIET = 1.0  # seconds after a paste ends
TEXT_FIRST = "F2 no confirma con texto escrito: mandalo con Enter o borralo primero."


class DaleGate:
    """Sees every input batch the prompt processes, and says whether an F2 in the last one
    counts. Its clock is `time.monotonic` outside tests."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock, self._lone, self._at = clock, False, 0.0
        self._paste_ended: float | None = None

    def batch(self, strokes: list[Stroke]) -> None:
        strokes = [s for s in strokes if s.key != Keys.CPRResponse]  # the terminal's replies
        if not strokes:
            return
        self._at, self._lone = self._clock(), len(strokes) == 1
        if any(s.key == Keys.BracketedPaste for s in strokes):
            self._paste_ended = self._at

    def counts(self) -> bool:
        pasted = self._paste_ended is not None and self._at - self._paste_ended < PASTE_QUIET
        return self._lone and not pasted


def watch_batches(processor: KeyProcessor, gate: DaleGate) -> None:
    """prompt_toolkit 3.0.53 hands every batch to `feed_multiple` before it processes it: the
    stored typeahead when a prompt starts, each read from the input, and each flush."""
    feed = processor.feed_multiple

    def feed_seen(key_presses: list[Stroke], first: bool = False) -> None:
        gate.batch(key_presses)
        feed(key_presses, first)

    processor.feed_multiple = feed_seen  # type: ignore[method-assign]


def discard_typed_ahead(input: Input) -> None:
    """Throws away what arrived before the prompt: a partial escape sequence the parser holds,
    keys read together with the last Enter (prompt_toolkit stores them for the next prompt),
    and, on a real terminal, bytes the terminal holds that nothing has read yet."""
    input.flush_keys()
    clear_typeahead(input)
    try:
        fd = input.fileno()
    except NotImplementedError:  # an input with no file descriptor
        return
    if isatty(fd):
        tcflush(fd, TCIFLUSH)


def key_bindings(pending: Pending, gate: DaleGate, notify: Callable[[str], None]) -> KeyBindings:
    bindings, is_pending = KeyBindings(), Condition(lambda: pending.proposal_id is not None)

    @bindings.add(Keys.F2, filter=is_pending)
    def _dale(event: KeyPressEvent) -> None:
        if not gate.counts() or (proposal_id := pending.proposal_id) is None:
            return
        if event.current_buffer.text:
            notify(TEXT_FIRST)  # the text stays, and nothing is confirmed
            return
        event.app.exit(result=KeyPress(Key.DALE, proposal_id))

    @bindings.add(Keys.F3, filter=is_pending)
    def _cancel(event: KeyPressEvent) -> None:
        event.app.exit(result=KeyPress(Key.CANCEL))

    @bindings.add(Keys.ControlC)
    def _clear(event: KeyPressEvent) -> None:
        event.current_buffer.reset()  # only Ctrl-D leaves

    return bindings


class TerminalInput:
    def __init__(
        self,
        pending: Pending,
        input: Input | None = None,
        output: Output | None = None,
        notify: Callable[[str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        def say(text: str) -> None:  # printed above the prompt while it runs
            print_formatted_text(FormattedText([("", text)]), output=output)

        gate = DaleGate(clock)
        self._prompt = PromptSession[str | KeyPress](
            key_bindings=key_bindings(pending, gate, notify or say), input=input, output=output
        )
        watch_batches(self._prompt.app.key_processor, gate)

    def read(self) -> CustomerInput:
        """The next input; Ctrl-C clears the line and Ctrl-D raises EOFError."""
        discard_typed_ahead(self._prompt.app.input)
        got = self._prompt.prompt(PROMPT)
        return got if isinstance(got, KeyPress) else CustomerText(got)
