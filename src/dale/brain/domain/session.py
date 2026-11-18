"""Who the brain serves (D2) and which product ids tools returned (design §7). Code sets both."""

from collections.abc import Iterable
from dataclasses import dataclass

from dale.shared.ids import CompanyId, ConversationId, CustomerId, ProductId


@dataclass(frozen=True, slots=True)
class SessionContext:
    """Injected by the composition root. No tool input names a company or a customer."""

    company_id: CompanyId
    customer_id: CustomerId
    conversation_id: ConversationId


class GroundingLedger:
    """Product ids that `search_products` and `get_prices` returned in one conversation."""

    def __init__(self) -> None:
        self._returned: set[ProductId] = set()

    def record(self, product_ids: Iterable[ProductId]) -> None:
        self._returned.update(product_ids)

    def grounds(self, product_id: ProductId) -> bool:
        return product_id in self._returned
