"""Market Rush: fill market orders from memory; customers change their minds."""

import random
from typing import Literal, cast

from pydantic import BaseModel, Field

from backend.contracts.common import Contract
from backend.generation.generators.base import TextRequest, count
from backend.generation.schemas import MarketOrder, MarketRushContent, MarketScene, OrderChange
from backend.generation.vocab import stall_items, themes

SCENES = 4
Theme = Literal["fruit", "spices", "bakery", "pottery", "mixed"]
THEMES: tuple[Theme, ...] = ("fruit", "spices", "bakery", "pottery", "mixed")


class MarketLines(BaseModel):
    lines: list[str] = Field(description="One friendly line per order, in order")


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def order_line(items: list[str], rng: random.Random) -> str:
    quantities: list[str] = themes()["market_quantities"]
    return "I'd like " + _join([f"{rng.choice(quantities)} {i}" for i in items]) + "."


class MarketRushGenerator:
    game_id = "market_rush"
    schema = MarketRushContent

    def build(
        self, knobs: dict[str, float], rng: random.Random, theme: str | None
    ) -> MarketRushContent:
        chosen: Theme = theme if theme in THEMES else rng.choice(THEMES)
        vocab = stall_items(chosen)
        customers = count(knobs, "customers", 2, 1, 4)
        per_order = count(knobs, "items_per_order", 3, 1, 6)
        changes_wanted = round(knobs.get("change_rate", 0.0) * customers * per_order / 2)
        names: list[str] = themes()["customer_names"]
        scenes = []
        for _ in range(SCENES):
            people = rng.sample(names, customers)
            orders = []
            for person in people:
                items = rng.sample(vocab, per_order)
                orders.append(
                    MarketOrder(customer=person, items=items, line=order_line(items, rng))
                )
            changes = []
            for order in rng.sample(orders, min(changes_wanted, len(orders))):
                remove = rng.choice(order.items)
                add = rng.choice([v for v in vocab if v not in order.items])
                changes.append(
                    OrderChange(
                        customer=order.customer,
                        remove=remove,
                        add=add,
                        line=f"Actually, {order.customer} wants {add} instead of {remove}.",
                    )
                )
            scenes.append(MarketScene(orders=orders, changes=changes))
        return MarketRushContent(theme=chosen, scenes=scenes)

    def text_request(self, content: Contract) -> TextRequest:
        c = cast(MarketRushContent, content)
        orders = [o.items for s in c.scenes for o in s.orders]
        return TextRequest("market_rush", {"theme": c.theme, "orders": orders}, MarketLines)

    def apply_text(self, content: Contract, text: BaseModel) -> MarketRushContent:
        c = cast(MarketRushContent, content)
        lines = iter(cast(MarketLines, text).lines)
        scenes = []
        for scene in c.scenes:
            orders = [o.model_copy(update={"line": next(lines, o.line)}) for o in scene.orders]
            scenes.append(scene.model_copy(update={"orders": orders}))
        return c.model_copy(update={"scenes": scenes})

    def check(self, content: Contract, knobs: dict[str, float]) -> list[str]:
        c = cast(MarketRushContent, content)
        errors: list[str] = []
        vocab = set(stall_items(c.theme))
        customers = count(knobs, "customers", 2, 1, 4)
        per_order = count(knobs, "items_per_order", 3, 1, 6)
        for i, scene in enumerate(c.scenes):
            if len(scene.orders) != customers:
                errors.append(f"scene {i}: {len(scene.orders)} orders, expected {customers}")
            names = [o.customer for o in scene.orders]
            if len(set(names)) != len(names):
                errors.append(f"scene {i}: repeated customer")
            by_name = {o.customer: o for o in scene.orders}
            for order in scene.orders:
                if len(order.items) != per_order:
                    errors.append(f"scene {i}: {order.customer} has {len(order.items)} items")
                if len(set(order.items)) != len(order.items):
                    errors.append(f"scene {i}: {order.customer} has a duplicate item")
                unknown = [x for x in order.items if x not in vocab]
                if unknown:
                    errors.append(f"scene {i}: items not in the {c.theme} list: {unknown}")
                missing = [x for x in order.items if x.lower() not in order.line.lower()]
                if missing:
                    errors.append(f"scene {i}: line for {order.customer} leaves out {missing}")
            for change in scene.changes:
                target = by_name.get(change.customer)
                if (
                    target is None
                    or change.remove not in target.items
                    or change.add in target.items
                ):
                    errors.append(f"scene {i}: change for {change.customer} doesn't fit the order")
                if change.add not in change.line or change.remove not in change.line:
                    errors.append(f"scene {i}: change line must name both items")
        return errors

    def signature(self, content: Contract) -> str:
        c = cast(MarketRushContent, content)
        return " | ".join(o.line for s in c.scenes for o in s.orders)
