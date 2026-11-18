# 0002. The confirm key (Dale key)

Date: 2026-11-13
Status: accepted (tmux and Zellij checked)

## Context

Design decision D5 binds the Dale key to `F2` with prompt_toolkit key bindings, outside the
text buffer and active only while a proposal is pending. A typed "dale" is plain text and never
confirms (R4). Terminal multiplexers can intercept keys before the app sees them: Zellij
reserves several Ctrl chords, so the key is an F-key. Task 11.6 asks to check that `F2` reaches
the app inside tmux and inside Zellij.

`F3` drops the pending proposal (`KeyPress(CANCEL)`). It confirms nothing and calls nothing in
the brain.

## Check

| Multiplexer | Version | Result | How |
|---|---|---|---|
| tmux | 3.4 (`default-terminal tmux-256color`) | `F2` reaches the app | Automated, 2026-11-13 (re-run after B83) |
| Zellij | 0.46.0, in Alacritty | `F2` reaches the app | Manual, real keyboard, live model, 2026-11-18 |

The tmux check ran a probe with the real `dale.channels.terminal.keys.TerminalInput` in a
detached tmux session, with each key sent by its own `send-keys`:

- With a pending proposal, `F2` at an empty prompt returned
  `KeyPress(key=DALE, proposal_id=…)`.
- With a pending proposal, `dale`, `F2`, `Enter` printed the hint (send or clear the text
  first) above the prompt, kept `dale` in the buffer, and returned `CustomerText(text='dale')`.
  `F2` with text in the buffer never confirms (B83).
- With nothing pending, `dale`, `F2`, `Enter` returned `CustomerText(text='dale')`: `F2` did
  nothing and left no characters in the buffer.
- Typed ahead (B83): `quiero coca`, `Enter`, then `F2` while the next prompt was 3 s away (a turn
  running), then a proposal became pending and `hola`, `Enter` were sent. The second read
  returned `CustomerText(text='hola')`: the `F2` was thrown away before the prompt. With the
  terminal flush (`tcflush`) turned off, the same run returned `KeyPress(key=DALE, …)`, a
  confirmation of a proposal the customer had not seen. The flush is what stops it on a real
  terminal.

Limit: `send-keys` injects the key inside tmux, so this proves that tmux delivers `F2` to the
pane. It does not prove that the outer terminal emulator delivers `F2` to tmux. Some desktop
terminals bind F-keys (for example, to a menu), so the manual check below covers that path.

## Manual check (Zellij, and tmux from a real keyboard)

1. Seed the database, set `DALE_APP_DATABASE_URL` and `DALE_VERIFIER_DATABASE_URL`, and run
   `DALE_TERMINAL_COMPANY=el-hornero python -m dale.apps.terminal --customer C-001` inside the
   multiplexer. This calls the live model, so it spends from the workspace limit.
   The key itself can be checked without the model: the probe above only needs
   `TerminalInput`.
2. Ask for an order until the summary appears, then press `F2`.
3. Expected: management's confirmation message, then the verifier's verdict.

If `F2` is intercepted, do not change the key here: record it and decide with the user (D5).

## Zellij result (2026-11-18)

The user ran `python -m dale.apps.terminal --customer C-001` inside Zellij 0.46.0
in Alacritty, ordered until the proposal appeared (14 x cola 1,5 L and 2 x cola
2,25 L, total $ 30.800,00), and pressed `F2` at an empty prompt from a real keyboard. The app
printed management's confirmation and the verifier's verdict `VERIFICADO`. Zellij and the
terminal emulator both let `F2` through, so this also covers the outer-emulator path that the
tmux probe did not.

## Decision

Keep `F2` for confirm and `F3` for cancel.
