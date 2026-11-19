# GRID access audit — November 19, 2026

Authenticated read queries ran at 21:04–21:06 UTC (16:04–16:06 America/New_York). The key was read locally and never printed or placed in response artifacts. Raw responses remain in ignored `data/raw/`. Findings describe this account and these retrievals.

## Confirmed access and date coverage

Both Central Data and Series State introspection succeeded. The completed series and an alternate League Loopfeed returned populated state without GraphQL errors. Schema visibility and Central Data product service levels alone do not prove access to other products or every series.

The discovery window was November 1, 2026 00:00:00 through November 30, 2026 23:59:59.999999 UTC. Central Data returned `totalCount: 19`, 19 edges, and `hasNextPage: false`. There were 12 League esports series, one Valorant esports series, five League Loopfeeds, and one Valorant Loopfeed. The non-test League dates span November 3–14. No other series in this window were returned for this account at retrieval; this does not establish worldwide coverage or future scheduling completeness. Dates outside November were not tested. Loopfeed scheduled times can change between cycles.

| Tournament ID | Tournament | Title / type | Series | Observed scheduled dates (UTC) |
| --- | --- | --- | ---: | --- |
| 831635 | Worlds - 2026 (Knockouts: Knockouts) | League esports | 7 | November 3–8 and 14 |
| 833869 | LCP P&R - 2026 (Regional Qualifier: Regional Qualifier) | League esports | 5 | November 10–13 |
| 830805 | Game Changers Championship - 2026 (Knockouts: Knockouts) | Valorant esports | 1 | November 1 |
| 26 | GRID-TEST | Five League and one Valorant Loopfeed | 6 | November 19 at this retrieval |

These tournaments were observed through accessible series; an exhaustive tournament catalog was not queried. All 19 series advertised `liveDataFeed: FULL`; only the two populated Series State responses below confirm actual state retrieval.

## November series list

| Series ID | Scheduled start (UTC) | Title / type | Tournament ID | Teams |
| --- | --- | --- | --- | --- |
| 3003317 | 2026-11-01T18:00:00Z | Valorant / ESPORTS | 830805 | VISA KRÜ Blaze vs Gentle Mates (2) |
| 3012976 | 2026-11-03T22:00:00Z | League of Legends / ESPORTS | 831635 | TOP ESPORTS vs Invictus Gaming |
| 3012977 | 2026-11-04T22:00:00Z | League of Legends / ESPORTS | 831635 | Gen.G Esports vs LYON |
| 3012974 | 2026-11-05T22:00:00Z | League of Legends / ESPORTS | 831635 | Dplus KIA vs BILIBILI GAMING |
| 3012975 | 2026-11-06T22:00:00Z | League of Legends / ESPORTS | 831635 | T1 vs Karmine Corp |
| 3012979 | 2026-11-07T22:00:00Z | League of Legends / ESPORTS | 831635 | Gen.G Esports vs Invictus Gaming |
| 3012978 | 2026-11-08T22:00:00Z | League of Legends / ESPORTS | 831635 | T1 vs BILIBILI GAMING |
| 3018394 | 2026-11-10T05:00:00Z | League of Legends / ESPORTS | 833869 | FENNEL vs Nothin'Here |
| 3018395 | 2026-11-10T08:00:00Z | League of Legends / ESPORTS | 833869 | Saigon Warrior vs Team Gromp  |
| 3025851 | 2026-11-11T09:00:00Z | League of Legends / ESPORTS | 833869 | Ground Zero Gaming vs Frank Esports |
| 3018397 | 2026-11-12T06:00:00Z | League of Legends / ESPORTS | 833869 | Saigon Warrior vs Nothin'Here |
| 3018398 | 2026-11-13T06:00:00Z | League of Legends / ESPORTS | 833869 | Saigon Warrior vs DetonatioN FocusMe |
| 3012986 | 2026-11-14T19:00:00Z | League of Legends / ESPORTS | 831635 | Gen.G Esports vs BILIBILI GAMING |
| 3 | 2026-11-19T17:59:05Z | League of Legends / LOOPFEED | 26 | KT Rolster vs T1 |
| 71 | 2026-11-19T18:40:34Z | League of Legends / LOOPFEED | 26 | Cloud9 Kia vs Karmine Corp |
| 6 | 2026-11-19T19:19:22Z | Valorant / LOOPFEED | 26 | VAL-1 vs VAL-2 |
| 74 | 2026-11-19T19:41:23Z | League of Legends / LOOPFEED | 26 | Saigon Warrior vs Nothin'Here |
| 73 | 2026-11-19T19:48:05Z | League of Legends / LOOPFEED | 26 | Gen.G Esports vs Invictus Gaming |
| 72 | 2026-11-19T20:46:46Z | League of Legends / LOOPFEED | 26 | Dplus KIA vs BILIBILI GAMING |

## State samples

- Completed League series `3012976`: TOP ESPORTS vs Invictus Gaming, Worlds. `started=true`, `finished=true`, `valid=true`, data model version `3.50`. Invictus won 3–1; four finished games and ten players per game. Actual series start: November 3 at 22:07:41.135 UTC; last update: November 4 at 02:51:24.220 UTC.
- League Loopfeed `71`: Cloud9 Kia vs Karmine Corp. `started=true`, `finished=false`, `valid=true`. Three games returned, first two finished; game three had `clock.currentSeconds=430`, `ticking=true`. Last update was 21:00:38.413 UTC at retrieval. This confirms a populated snapshot with a ticking flag; advancement between snapshots was not tested. Repeating test cycles are not independent matches.
- Original Loopfeed `3`: both the expanded query and a minimal `{ seriesState(id: "3") { id started finished } }` query returned `data: {}` with no GraphQL errors. The field was omitted, not explicitly null. Central Data listed it as League / LOOPFEED, but Series State access or coverage for it is unconfirmed; the API supplied no reason. This is not evidence of an invalid key or a League-wide denial.

## Fields verified against the authenticated schema and responses

Paths below are relative to `seriesState`. Game team and player fields are under `games[].teams[]` and `games[].teams[].players[]` respectively. Every field named in this table was requested and returned populated values in the completed series and Loopfeed 71, except the empty role arrays noted below.

| Category | Actual fields | Observations / limits |
| --- | --- | --- |
| Champions and draft | Player `character { id name }`; game `draftActions { type sequenceNumber drafter { id type } draftable { id type name } }` | Champion IDs/names and picks/bans populated. Completed game one includes Rell for Zhuo and Gnar for TheShy. |
| Gold / economy | Team and player `money`, `netWorth`, `loadoutValue`; League fragments `totalMoneyEarned`, `moneyPerMinute`; League team `moneyDifference` | `money` means cash held; `netWorth` means cash plus inventory value; `totalMoneyEarned` means cumulative earned gold. Team `moneyDifference` compares total earned money. Completed game one: TES 52,754 vs IG 67,953 earned gold, difference ±15,199. |
| Objectives | Team/player `objectives { type completionCount completedFirst }`; game `structures { id type side teamId destroyed currentHealth maxHealth }` | Observed dragon aggregate and element-specific objectives, Baron, Rift Herald, Void Grubs, towers, plates, fortifier and Nexus. Preserve source labels such as `destroyFortifier`; do not assume every objective appears in each game or sum dragon aggregates and subtypes together. |
| Game clocks | `games[].clock { currentSeconds ticking ticksBackwards type }`, `games[].duration`, `games[].startedAt`; series `startedAt`, `updatedAt`, `duration` | Clocks and ISO duration strings populated. Completed game one clock is 1,858 seconds while duration is `PT32M43.343S`; they differ, so retain both. No historical clock trajectory was retrieved. |
| Player statistics | `kills`, `deaths`, `killAssistsGiven`; `unitKills { unitName count }`; League fragment `experiencePoints`, `damageDealt`, `damageTaken`, `damagePerMinute`, `kdaRatio`, `killParticipation`, `visionScore`, `visionScorePerMinute` | Per-game values populated; series player kill/death/assist aggregates also populated. Unit kills distinguish minion, neutralMinion and ward when present. The schema describes damage generically; champion-only damage and exact CS semantics were not established. |
| Player roles | `roles { id }` | All 70 player-game role lists across both populated samples were `[]`; positional roles were not available in these samples. |

League-only fields require inline fragments on `GameTeamStateLol` and `GamePlayerStateLol`, because `teams` and `players` use interfaces. Schema fields that were not requested are schema-visible only, not confirmed populated. No explicit null values occurred anywhere in the two expanded populated snapshots. Empty lists, zero values, omitted `seriesState`, and explicit nulls are distinct; zeros in the active Loopfeed are valid observed values.

Only final state aggregates were retrieved for the completed match. Timeline events, gold at an arbitrary historical minute, historical objective timestamps, Series Events, File Download, and other API products were not tested or confirmed.

## Changes and validation

- Fixed the series starter with `orderDirection: ASC`; added title, series type and product service levels so League and test feeds are identifiable.
- Expanded state selection to audit champions, drafts, economy, objectives, structures, clocks and player statistics using authenticated League types.
- Corrected the CLI diagnostic to distinguish omitted `seriesState` from explicit null; responses are saved before either diagnostic.
- Updated README with the full November window, audited Loopfeed ID and these results.
- Ran `python3 -m unittest discover -s tests -v` after changes: **9 tests passed**, including missing-versus-null response regression coverage and existing credential redaction tests.
- Live validation: both schema commands succeeded; corrected series query succeeded with complete pagination; expanded completed-series and Loopfeed 71 queries succeeded; Loopfeed 3 was unavailable with expanded and minimal queries.

## Local evidence

- `data/raw/schema-central-20261119T210413-206df473.json`
- `data/raw/schema-state-20261119T210419-0b92bccd.json`
- `data/raw/series-central-20261119T210446-ab63e872.json`
- `data/raw/state-state-20261119T210457-e7248c0e.json`
- `data/raw/state-state-20261119T210513-8df32df9.json`
- `data/raw/state-state-20261119T210539-23e12532.json`
- `data/raw/loopfeed-minimal-state-20261119T210602-6172ded0.json`
