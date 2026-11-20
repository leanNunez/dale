"""The shared wiring (D11): each channel's conversation row names its channel, and the terminal's
`compose` is the shared one for the terminal channel."""

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from dale.apps import terminal
from dale.apps.compose import Channel, ChannelBackend, compose
from dale.brain.infrastructure import tables as t
from dale.shared.clock import FrozenClock
from dale.shared.customer_input import CustomerText
from dale.shared.errors import Ok, Result
from tests.integration.test_proposals import NOW
from tests.unit.brain.test_loop import ScriptedModel, says

pytestmark = pytest.mark.integration


def stored_channel(db: Engine, composed: Result[ChannelBackend]) -> str:
    assert isinstance(composed, Ok)
    composed.value.take_turn(CustomerText("hola"))
    row = t.conversation.c.id == composed.value.session.conversation_id
    with db.connect() as conn:
        return str(conn.execute(sa.select(t.conversation.c.channel).where(row)).scalar_one())


@pytest.mark.parametrize("channel", ["terminal", "web"])
def test_the_conversation_row_names_its_channel(db: Engine, channel: Channel) -> None:
    model = lambda: ScriptedModel(says("Hola."))  # noqa: E731
    composed = compose(db, "el-hornero", "C-001", model, FrozenClock(NOW), channel=channel)
    assert stored_channel(db, composed) == channel


def test_the_terminal_composes_terminal_conversations(db: Engine) -> None:
    composed = terminal.compose(
        db, "el-hornero", "C-001", lambda: ScriptedModel(says("Hola.")), FrozenClock(NOW)
    )
    assert stored_channel(db, composed) == "terminal"
