# Data Sources

## Deployed development inputs

- [nflverse player summary stats](https://github.com/nflverse/nflverse-data/releases/tag/stats_player): weekly official-style box-score summaries back to 1999.
- [nflverse weekly rosters](https://github.com/nflverse/nflverse-data/releases/tag/weekly_rosters): week-level roster membership back to 2002.
- [nflverse snap counts](https://github.com/nflverse/nflverse-data/releases/tag/snap_counts): game-level PFR snap counts from 2012.
- [nflverse injuries](https://github.com/nflverse/nflverse-data/releases/tag/injuries): weekly reports from 2009.
- [nflverse schedules](https://github.com/nflverse/nfldata/blob/master/data/games.csv): schedule, result, rest, weather, surface, and consensus closing-line fields.
- [nflverse player identifiers](https://github.com/nflverse/nflverse-data/releases/tag/players): GSIS, PFR, ESPN, PFF, and other cross-source IDs.

nflverse publishes these automated assets in Parquet and other formats. Player
stats update daily during the season, rosters update daily, and snap counts are
polled multiple times per day. The project retains source attribution required
by nflverse and upstream providers.

## Shadow-deployed market inputs

- [Kalshi historical data API](https://docs.kalshi.com/getting_started/historical_data): public series discovery plus partitioned live/historical markets and candlesticks.
- [Polymarket market-data API](https://docs.polymarket.com/market-data/overview): NFL-tagged event metadata and CLOB price history.

Both connectors are implemented, point-in-time constrained, and available to
the opt-in `player_market` layer. They are not active official forecast features.
The August 31, 2026 audit found 3,584 Kalshi passing-yard, 4,746 rushing-yard,
and 10,376 receiving-yard catalog contracts, all with history beginning October
6, 2025. Polymarket exposed 948 recognized anytime-touchdown contracts from
September 2024 onward, but only one recognized passing-yard contract. Catalog
counts precede player/game mapping, liquidity filters, and common-support tests.

## Candidate shorter-history inputs

- [NFL Next Gen Stats via nflverse](https://github.com/nflverse/nflverse-data/releases/tag/nextgen_stats): passing, rushing, and receiving data from 2016 with minimum-volume publication thresholds.
- nflverse advanced passing/rushing/receiving statistics and FTN charting.

Further admission work must measure stable player/game identifier matches,
liquidity, and the fraction of fantasy-relevant player-games with a usable
pre-kickoff quote.
