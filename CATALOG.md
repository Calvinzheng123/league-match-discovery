# Catalog model and baseline

The access audit describes the initial probe. This catalog extends it by retrieving
all twelve November League esports series. It does not turn the Loopfeeds into
catalog matches. `data/` and all DuckDB files are ignored by Git.

## Ingestion and recovery

`run.py ingest` uses the complete saved November discovery connection, or queries
Central Data sequentially until pagination is exhausted. A new discovery includes
its request dates, cursor, and response provenance. The original audit connection
predates request metadata and is accepted for the default November window only;
`--discovery PATH` explicitly selects another complete saved connection. Partial
pages are rejected as explicit discovery inputs. Fresh paginated discovery saves
each page and then saves a combined complete connection; incomplete discovery is
not treated as complete coverage. If interrupted during discovery, rerunning
restarts discovery; successful pages remain available for inspection.

Selection requires `title.id == "3"` and `type == "ESPORTS"`, plus a scheduled
start in the requested inclusive timestamp window. Actual State title must also
be `lol` and its ID must match discovery before normalization. Series State is
fetched with the existing single client, 10.1-second pacing and retry logic. Raw
JSON is saved atomically before normalization, including requested series ID and
retrieval time. No request headers are stored.

Each selected series gets an `ingestion_attempts` entry. Outcomes are `success`,
`unavailable_omitted`, `unavailable_null`, `unfinished`, `error`, or
`normalization_error`. `running` and `downloaded` are intermediate recovery states
that can remain after interruption. Only completed series enter normalized tables;
search additionally requires explicit series and game validity and completion.
Unavailable or unfinished responses are retained in raw files, not normalized as
completed games. Coverage reports historical failures and the latest attempt per
series; a listed series alone never counts as a successful retrieval. Network and
normalization errors produce a nonzero ingest exit after processing other series.
Unavailable and unfinished states are reported outcomes, not CLI failures.

Reruns reuse completed raw downloads by default, then rebuild that series in one
transaction. This recovers an interrupted or failed normalization without another
API request and can rebuild a lost database. `--refresh` fetches all selected states
again. Unavailable, unfinished, and failed downloads are retried on each run.
The audit's old state samples lack per-game `valid`; those receive a one-time
fresh download rather than assuming game validity from series validity. Future
completed downloads with per-game validity are reusable. Keep expanded raw files
in the same `--output-dir` for recovery. An unsuccessful refresh retains the last
successful normalized snapshot; its original retrieval timestamp remains visible,
alongside the latest failed attempt. This is a local CLI for sequential use; do
not run multiple ingestions against the same DB or API quota concurrently.

## Tables, keys and relationships

IDs are GRID strings, not generated sequential catalog IDs. Column names from
GRID statistics retain their original camel case. SQL identifiers for those
columns should be quoted. Child keys include series and game IDs so games from
different series cannot collide.

| Table / view | Primary key | Relationship and contents |
| --- | --- | --- |
| `series` | `series_id` | Discovery tournament ID/name and scheduled time; state completion/validity, timestamps, duration; provenance and source objects. |
| `games` | `(series_id, game_id)` | Belongs to series. State sequence number, started time, completion/validity, original ISO duration, parsed duration seconds, clock seconds. |
| `game_teams` | `(series_id, game_id, team_id)` | Belongs to game. Team name, side, winner, economy and statistics. |
| `game_players` | `(series_id, game_id, player_id)` | Belongs to game and `team_id` identifies its game team. Player name, character ID/name, roles JSON, economy and statistics. |
| `draft_actions` | `(series_id, game_id, action_id)` | Belongs to game. Source action ID, sequence string, action type, drafter ID, draftable ID/name/type. Picks and bans stay separate. |
| `objectives` | `(series_id, game_id, owner_kind, owner_id, source_id)` | Owner kind is team or player; owner ID references the corresponding game entity. Exact objective type/count; `completedFirst` remains in source JSON. |
| `unit_kills` | `(series_id, game_id, owner_kind, owner_id, source_id)` | Same ownership model; original unit label and count. |
| `structures` | `(series_id, game_id, structure_id)` | Belongs to game; owning team, type and destruction state; health/side preserved in source JSON. |
| `ingestion_attempts` | `attempt_id` | Local UUID per attempt, selected series ID, attempt timestamp, status, safe error type/detail, raw path when available. Attempts can exist without normalized series. |
| `catalog` (view) | logical `(series_id, game_id)` | Completed, valid game joined to completed, valid series; date/tournament and total kills. CLI adds readable team/player/champion records and objective features. |

Parent links are logical relationships enforced by the normalizer's construction
and per-series transaction, not DuckDB foreign-key constraints. Primary keys are
database constraints. A replacement deletes children and parents for one series,
inserts all its rows, then commits; any error rolls back the entire replacement,
including restoring its previous version. Other series are unaffected. Attempt
logging is outside that transaction so failures remain inspectable.

New downloads select source IDs for actions, objectives and unit breakdowns.
Legacy objects without these IDs use stable `sequence:<sequenceNumber>` for draft
actions or `label:<original label>` for owner breakdowns. Duplicate keys fail and
roll back instead of silently merging records.

## Exact source mapping and missing data

The local authenticated schema exposes `GameState.valid` as Boolean and
`duration` as the GRID Duration scalar; `sequenceNumber` is Int. Draft sequence
numbers are Strings. Kills, money and objective/unit counts are Int; ratios and
per-minute statistics are Float. These mappings were checked against local schema
responses and the expanded completed-series files. League-only fields are selected
via `GameTeamStateLol` and `GamePlayerStateLol` fragments.

Paths below are under `data.seriesState` in each raw wrapper:

| Source path | Normalized destination |
| --- | --- |
| `id`, `startedAt`, `updatedAt`, `finished`, `valid`, `duration` | `series`; discovery `node.tournament` and `node.startTimeScheduled` provide tournament and scheduling metadata. |
| `games[].id`, `sequenceNumber`, `startedAt`, `finished`, `valid`, `duration` | `games`, including parsed `duration_seconds`. |
| `games[].clock.currentSeconds` | `games.clock_seconds`; original clock object retained separately. |
| `games[].teams[]` | `game_teams`, including `money`, `netWorth`, `loadoutValue`, `totalMoneyEarned`, `moneyDifference` as five independent columns. |
| `games[].teams[].players[]` | `game_players`; `character.id/name` are played champion fields. `roles` stays JSON; empty means no positional role known. |
| `games[].draftActions[]` | `draft_actions`; `type=ban` never makes a champion count as played. |
| Team/player `objectives[]` and `unitKills[]` | Owner-specific child tables; no cross-owner or subtype merging. |
| `games[].structures[]` | `structures`. |
| Wrapper `retrieved_at` and file path | `series` and `games`; children inherit provenance through their game. Discovery file path and discovery JSON live on `series`. |

Every entity table also retains its corresponding `source_json`. Typed columns
use SQL NULL for a missing or explicitly null scalar; source JSON distinguishes
an omitted key from a present JSON null. Empty lists remain `[]` in source JSON;
null lists remain JSON null; missing lists have no key. A child table with zero
rows must be interpreted together with the parent's source JSON, never as proof
of an observed zero. Explicit numeric zeros are stored as zeros. `coverage`
reports `omitted`, `null`, `empty_list`, `zero`, and `populated` for selected
source paths. An omitted field may simply not have been requested for that entity;
it does not establish an entitlement denial. Roles are not inferred from champions,
player names, or team composition. No lane matchups are produced.

`money` means cash held, `netWorth` cash plus inventory value, `loadoutValue`
inventory/loadout value, `totalMoneyEarned` cumulative earned money, and
`moneyDifference` the team's earned-money difference to its opponent. Damage is
stored under the source names; champion-only damage is not assumed. Unit labels
remain `minion`, `neutralMinion`, `ward`, etc.; a synthetic CS field is not invented.

## Search and counting semantics

All search conditions are ANDed. Champion, team and tournament filters are exact,
case-sensitive matches against source ID or full source name. Champion filters
read player `character`, not the draft table. Dates are inclusive UTC calendar
dates using game `startedAt`, then series `startedAt`, then scheduled time as
fallback; `game_date` shows the chosen value. An unknown date fails an active date
filter. `--min-duration`/`--max-duration` use **parsed GRID `games[].duration` in
seconds**, not `clock.currentSeconds`. Both remain available for inspection.

Total kills is the sum of non-null game-team kills when at least two team rows
exist. A missing team's kill value yields an unknown total. Numerical bounds are
inclusive; unknown values fail an active bound instead of becoming zero.

Objective bounds require `--objective EXACT_SOURCE_LABEL`, such as `slayDragon`.
Only team-level entries with that exact label are summed. Player objectives are
not added to team totals; `slayInfernalDrake` is not added to `slayDragon`.
Conservatively, a total is known only when each team's list explicitly contains
the label and a count. An absent label (including in an empty list) is unknown,
not an invented zero. Explicit counts of zero remain zero. This costs coverage
but avoids assuming that a sparse label list guarantees a zero. Search output
includes null objective totals and coverage reports their known/unknown counts.

## Inspectable similarity baseline

Only searchable games participate; the selected game is excluded. Champion sets
use source character IDs with **Jaccard overlap** `intersection / union`. If a
player lacks a character ID or the roster is empty, this component is unavailable.
Bans never participate. Numerical features use fixed documented scales:

| Feature | Scale |
| --- | ---: |
| Total team kills | 20 kills |
| Parsed GRID duration | 600 seconds |
| Exact `slayDragon` team total | 4 |
| Exact `slayBaron` team total | 2 |
| Exact `destroyTower` team total | 10 |

For each feature known in both games, score = `exp(-abs(a-b)/scale)`. Numerical
score is the equal-weight mean of those feature scores. Missing features are
excluded from that pair's mean; no comparable features means an unavailable
numerical component. Gold values are retained for inspection/search records but
are not ranking features, so their magnitude cannot dominate counts.

Defaults are 0.6 champion score and 0.4 numerical score, configurable with
`--champion-weight` and `--numeric-weight`. Weights must be finite, nonnegative,
and have positive sum. Available components are weighted and divided by their
available weight sum. No available component with positive weight yields a null
score sorted last. Thus games with less feature coverage can still score highly;
inspect `numeric_features_used` and `numerical_comparisons`. These are chosen
baseline weights and scales, not validated relevance estimates.

Ranking is descending score, then ascending `SERIES_ID:GAME_ID` as a deterministic
string tie-break. Output shows both component scores, actual shared champion
names, selected/candidate values, scale and score for each comparable numerical
feature, and configured weights. This supports inspection rather than claims of
personalized recommendation quality.

## Verified local run and one game's path

On November 19, 2026 at 21:22–21:24 UTC, ingestion used the saved 19-series
Central Data connection and selected 12 League esports series. **All twelve
state downloads succeeded**, yielding **43 games, all completed and valid**, 86
game teams, 430 game players, 860 draft actions, 1,290 structures, 3,582 objective
rows and 1,355 unit-kill rows. Worlds contributes 25 games and LCP P&R 18.
Game-start coverage spans November 3 at 22:15:00.559 UTC through November 14 at
23:18:16.650 UTC. No retrieval failures or unfinished states occurred in this run;
that does not promise access beyond the selected window. All 430 role lists were
empty. All 43 games have kill and duration features; exact-label objective totals
are known for dragons in 35 games, Baron in 6 and towers in 39 under the policy
above. Other totals remain unknown, even where one team has a populated entry.

An offline rerun reused all 12 downloads and kept exactly 43 game rows. The test
suite passed 24 tests, including rollback after a partially written series,
idempotence, outcome separation, exclusions, missing values and deterministic ranks.

For a reproducible example, use the first audited game's key:
`3012976:66d77ca4-b755-4fee-9170-ff4cc909efec`.

1. Discovery identifies League series `3012976`, Worlds, TOP ESPORTS vs Invictus
   Gaming. Its upgraded raw file is locally
   `data/raw/state-state-20261119T212237-d35f8307.json`, retrieved at 21:22:37 UTC.
2. `data.seriesState` becomes one `series` row. Its first `games[]` object becomes
   the keyed `games` row; its teams, players, drafts, objectives, unit kills and
   structures become related rows in the same transaction. The source file and
   exact retrieval timestamp link the rows back to that original wrapper.
3. The `catalog` view admits the game because both it and its series are explicitly
   complete and valid. The game has 39 kills, parsed duration 1,963.343 seconds,
   and a separate clock of 1,858 seconds. Its known exact dragon total is 5 and
   tower total is 11. Baron total is unknown under the explicit-label policy.
4. `search --champion Rell --team 'Invictus Gaming'` finds the game: Rell was played
   by TES's Zhuo, while IG participated as the other team. Team and champion
   filters independently match the game, not necessarily the same team. Use the
   returned player/team IDs to inspect that relationship.
5. With default weights, the top similar result was
   `3012975:db4b9652-b5e4-4d4a-ab06-c0349c2b32b9` (Worlds, November 6).
   They share Ambessa, Cassiopeia, Kai'Sa, Nautilus and Rell: Jaccard `5/15 = 0.3333`.
   The candidate has 29 kills, duration 1,778.791 seconds, 5 dragons and 11 towers.
   The numerical mean is `0.835437`; weighted total is `0.534175`. Both games have
   unknown Baron totals for ranking, so that feature is excluded for this pair.

Raw responses, database and demonstration outputs in `data/` stay local. No
credentials or raw GRID records are included in tests; fixtures are synthetic.
