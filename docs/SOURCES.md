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

## Candidate shorter-history inputs

- [NFL Next Gen Stats via nflverse](https://github.com/nflverse/nflverse-data/releases/tag/nextgen_stats): passing, rushing, and receiving data from 2016 with minimum-volume publication thresholds.
- nflverse advanced passing/rushing/receiving statistics and FTN charting.
- [Kalshi event candlesticks](https://docs.kalshi.com/api-reference/events/get-event-candlesticks): timestamped price, bid/ask, volume, and open-interest histories.
- [Polymarket developer API](https://docs.polymarket.com/): market metadata and CLOB price history.

Kalshi and Polymarket coverage is not assumed. An availability audit must first
measure NFL player-prop history, stable player/stat identifiers, liquidity, and
the fraction of fantasy-relevant player-games with a usable pre-kickoff quote.

