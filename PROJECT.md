# Project plan

## Question

Can structured gameplay features and retrieval help a viewer find professional
League games that match what they want to watch or study?

## Milestone 1 — Access audit

- Save the authenticated Central Data and Series State schemas locally.
- List a small date window and record accessible tournaments and title IDs.
- Query one completed series and the League test Loopfeed.
- Document available fields for games, teams, players, champions, clocks and
  objectives. Distinguish unavailable, null and observed values.
- Record coverage without treating generic GRID commercial coverage as account access.

## Milestone 2 — Searchable match catalog

Build normalized local tables once the source fields are confirmed:

| Table | Intended grain |
| --- | --- |
| series | One matchup, possibly containing multiple games |
| games | One game within a series |
| game_teams | One team within one game |
| game_players | One player within one game |
| snapshots | One observed series state at a retrieval time |

Keep source IDs stable. Store the original response separately from normalized
tables. Use idempotent upserts for final-state entities. Keep missing values as
null, not zero. Preserve retrieval time and any source timestamp or game clock
as separate fields. Source-specific fields should be documented after inspection.

Start with Python and DuckDB when normalized tables are needed. Add a small
Streamlit interface after a useful catalog exists. DuckDB is now used by the catalog CLI; the web interface remains planned. See
`CATALOG.md` for the implemented table grains, field mappings and baseline.
The November 2026 catalog contains 43 completed, valid games from twelve
successfully retrieved series; it does not include test Loopfeeds.

## Milestone 3 — Retrieval and recommendation

Begin with exact team/date/tournament filters and keyword search over factual
game descriptions. Add standardized numerical similarities for available game
characteristics. Keep raw numerical features alongside transformed features so
ranking explanations can show evidence. Match duration, champions, objectives
and patch filters remain conditional on schema and coverage verification.

Compare content similarity with a simple recency baseline. Add embeddings only
after judging a representative set of queries. Do not infer a player's role or
champion matchup solely from two champion names without supporting fields.

## Milestone 4 — Observed timelines

After checking storage terms, add bounded, restartable snapshot polling for future
matches. Detect changes between observed states and represent uncertain event
times as intervals. Track missing polls and feed resets. A final score does not
prove a comeback. Loopfeed resets must never produce false lead changes or new
independent training matches. Finding footage requires separately verified VOD
links and game-clock-to-video alignment.

## Evaluation

Create manually judged search queries for the actual available catalog. Compare
filters plus keyword retrieval with numerical reranking and later semantic
retrieval. Report Precision@5, NDCG@5 and latency, with dataset size and field
coverage. Keep the final evaluation query set separate from ranking development.
For timeline labels, inspect evidence from complete observed games and report
sampling intervals and missing observations. A tiny initial catalog supports
functionality checks; it cannot substantiate personalization quality.
