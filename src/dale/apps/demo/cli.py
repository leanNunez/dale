"""The operator CLI (O6, design §7), run on the server as the app role:

    python -m dale.apps.demo pause [--reason operator|deploy]
    python -m dale.apps.demo resume [--if-reason operator|deploy]

It connects through `DALE_APP_DATABASE_URL` (`dale_app`, which may only read and update the
control row) and loads no web stack (import contract 13). Exit 0 when the state is as asked,
1 when the control row cannot be read or written (S6.2), 2 on bad arguments or a missing or
unusable URL, 3 when `resume --if-reason` left a pause with another reason in place. Output
holds states, reasons and error classes only, never the URL or any other value from the
environment."""

import argparse
import os
import sys
from collections.abc import Callable, Mapping, Sequence

import sqlalchemy as sa

from dale.apps.compose import app_engine
from dale.apps.demo.control import ControlError, ControlState, Outcome, SqlControl
from dale.shared.clock import Clock, SystemClock

URL_VARIABLE = "DALE_APP_DATABASE_URL"
KEPT = 3  # exit status: `resume --if-reason` found a pause with another reason and kept it
CLI_REASONS = ("operator", "deploy")  # the reset pauses from inside the host, never from here


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m dale.apps.demo")
    commands = parser.add_subparsers(dest="command", required=True)
    pause = commands.add_parser("pause", help="pause the demo (idempotent)")
    pause.add_argument("--reason", choices=CLI_REASONS, default="operator")
    resume = commands.add_parser("resume", help="resume the demo (idempotent)")
    resume.add_argument(
        "--if-reason", choices=CLI_REASONS, help="resume only a pause with this reason"
    )
    return parser


def describe(state: ControlState) -> str:
    since = state.changed_at.isoformat(timespec="seconds")
    return f"paused ({state.reason}) since {since}" if state.paused else f"running since {since}"


def main(
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
    *,
    engine_for: Callable[[str], sa.Engine] = app_engine,
    clock: Clock | None = None,
) -> int:
    try:
        args = parser().parse_args(argv)
    except SystemExit as stop:  # argparse printed the usage: 2 on bad arguments
        return stop.code if isinstance(stop.code, int) else 2
    url = (os.environ if env is None else env).get(URL_VARIABLE)
    if not url:
        print(f"{URL_VARIABLE} must be set", file=sys.stderr)
        return 2
    try:
        engine = engine_for(url)
    except Exception as error:  # a malformed URL's message holds parts of it: the class only
        print(
            f"{URL_VARIABLE} is not a usable database URL ({type(error).__name__})", file=sys.stderr
        )
        return 2
    try:
        control = SqlControl(engine, clock or SystemClock())
        try:
            done = _run(control, args)
        except ControlError as error:
            print(f"{args.command} failed: {error}", file=sys.stderr)
            return 1
        kept = args.command == "resume" and done.state.paused  # a pause with another reason
        said = "done" if done.changed else "not resumed" if kept else "no change"
        print(f"{args.command}: {said}; {describe(done.state)}")
        return KEPT if kept else 0
    finally:
        engine.dispose()


def _run(control: SqlControl, args: argparse.Namespace) -> Outcome:
    if args.command == "pause":
        return control.pause(args.reason)
    return control.resume(args.if_reason)
