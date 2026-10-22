"""Generators by game id. A game listed here needs content in its exercise spec."""

from backend.generation.generators.base import Generator
from backend.generation.generators.custom_blocks import CustomBlocksGenerator
from backend.generation.generators.market_list import MarketListGenerator
from backend.generation.generators.market_rush import MarketRushGenerator
from backend.generation.generators.pattern_gap import PatternGapGenerator
from backend.generation.generators.spot_the_mistake import SpotMistakeGenerator

GENERATORS: dict[str, Generator] = {
    g.game_id: g
    for g in (
        MarketRushGenerator(),
        MarketListGenerator(),
        PatternGapGenerator(),
        SpotMistakeGenerator(),
        CustomBlocksGenerator(),
    )
}
