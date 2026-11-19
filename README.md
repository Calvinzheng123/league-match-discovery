# League Match Discovery

A noncommercial League of Legends esports search and recommendation project
using official Riot GRID data. The CLI audits access, ingests completed League
series into a local DuckDB catalog, searches exact match fields, and ranks an
inspectable champion/numerical similarity baseline.

## Quick start

Python 3.10+ is required. The audit commands use the standard library; catalog
commands and the full test suite also require DuckDB.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
# If .env does not exist yet, copy .env.example to .env and set GRID_API_KEY.
```

On Windows use `.venv\Scripts\Activate.ps1`. Keep an existing configured `.env`.
Set `GRID_API_KEY` inside `.env` locally. The CLI reads that file automatically;
existing environment variables take precedence. Keep the key private.

Inspect the authenticated schemas first:

```bash
python3 run.py schema --api central
python3 run.py schema --api state
```

List entitled series for a small window, then inspect a series ID from the output:

```bash
python3 run.py series --start 2026-11-01T00:00:00Z --end 2026-11-30T23:59:59.999999Z --pages 20
python3 run.py state --id YOUR_SERIES_ID
```

This initial query lists whatever series your account can access in the window.
Verify title and entitlement in the schema before adding a League-only filter.
An empty response establishes neither complete coverage nor a broken key.

`series` defaults to one page of 20 entries. Increase `--pages` deliberately.
Every successful page is saved before the next request. If interrupted, resume
using `--after` with the last saved page's `pageInfo.endCursor`.

Inspect a repeating LoL test series separately (ID 71 returned state in the
November 19 audit; the original starter ID 3 returned an empty data object):

```bash
python3 run.py state --id 71
```

Run it again later to collect a second snapshot. Loopfeed repeats a test series;
repeated cycles are not independent matches. This starter performs single
snapshots, so no unattended polling process is started.

Responses are saved in ignored `data/raw/` with source, API name, and UTC retrieval
time. Generate an offline list of observed fields from one saved response:

```bash
python3 run.py fields data/raw/YOUR_RESPONSE_FILE.json
python3 -m unittest discover -s tests -v
```

## Searchable catalog

With the virtual environment active, these commands use the local configured key
for ingestion. Coverage, search, game inspection and similarity run offline:

```bash
# Defaults to the full November 2026 window; reuses complete saved discovery.
python run.py ingest
python run.py coverage

# Exact, case-sensitive champion/team/tournament names or source IDs.
python run.py search --champion Rell --team 'Invictus Gaming' --start 2026-11-01 --end 2026-11-30
python run.py search --tournament 831635 --min-kills 30 --max-duration 2400
python run.py search --objective slayDragon --min-objectives 5 --limit 5

# Copy a SERIES_ID:GAME_ID key from search; this example is in the audited data.
python run.py game --id 3012976:66d77ca4-b755-4fee-9170-ff4cc909efec
python run.py similar --id 3012976:66d77ca4-b755-4fee-9170-ff4cc909efec --limit 3
python run.py similar --id 3012976:66d77ca4-b755-4fee-9170-ff4cc909efec --champion-weight 0.8 --numeric-weight 0.2

# Reuses completed downloads by default; refresh explicitly requests new state.
python run.py ingest
python run.py ingest --refresh
python -m unittest discover -s tests -v
```

Every catalog command accepts `--db PATH` (default `data/catalog.duckdb`). Ingestion
also accepts `--output-dir`, `--discovery PATH` for a complete saved connection,
and timezone-aware `--start`/`--end` timestamps. Duration bounds mean parsed GRID
game duration in seconds, kept separate from the game clock. Date bounds use UTC
calendar dates. Team and champion filters independently match the whole game.

The November 19 ingestion retrieved **12 of 12 selected League esports series**
and normalized **43 completed, valid games**: 25 Worlds games and 18 LCP P&R games.
An offline rerun reused all twelve downloads without duplicating rows. **24 tests
passed**. All 430 player role lists were empty, so positional roles remain unknown.
Coverage shows table counts, field availability, feature coverage, latest retrieval
status per series and historical failures. Omitted state, explicit null, unfinished
state and errors are separate outcomes; successful listing is not successful state
retrieval. Failed refreshes preserve the prior successful snapshot and provenance.

`leaguegrid/ingest.py` coordinates saved discovery, the existing throttled client,
atomic raw storage, attempt logging and normalization. `leaguegrid/catalog.py`
replaces one series transactionally, builds a completed/valid catalog view, and
implements exact filters and deterministic similarity. All derived data stays in
ignored local files. Gold measures remain separate; objective labels are never
summed with their subtypes. Missing counts are not silently zero-filled.

See [CATALOG.md](CATALOG.md) for table keys and source paths, missing-data policy,
scoring equations and weights, and a reproducible walkthrough from one raw game
to tables, search and its actual top-ranked similar game. Timeline collection,
comeback detection, VOD alignment, embeddings and a web interface are later work.

## Current verification status

Authenticated Central Data and Series State calls succeeded on November 19, 2026.
See [ACCESS_AUDIT.md](ACCESS_AUDIT.md) for the November series list, tournament
and date coverage, confirmed fields, and the unavailable state for Loopfeed 3.
The series query now supplies `orderDirection: ASC`; the state query includes
League-specific statistics through inline fragments on the authenticated types.
Offline tests cover HTTP behavior, query rendering, storage, and missing versus
explicitly null state. Query templates live in `queries/`. Tokens
such as `__SERIES_ID__` are safely rendered by `run.py`; these template files are
not standalone GraphQL requests until rendered. Introspection can be unavailable
for some deployments; use GRID's authenticated Playground if access is denied.

The client sends read queries to the two fixed Open Access endpoints. It spaces
requests at least 10.1 seconds apart per process and retries transient HTTP
errors up to three total attempts. This conservative pacing supports an initial
audit. Avoid running several CLI processes concurrently because quotas are shared.
Partial GraphQL responses fail explicitly. Saved outputs contain response data,
never request headers.

## Layout

| File | Responsibility |
| --- | --- |
| `run.py` | CLI, query rendering, pagination and response summaries |
| `leaguegrid/client.py` | Authentication, HTTP, pacing, retries and GraphQL errors |
| `leaguegrid/storage.py` | Local configuration and atomic JSON writes |
| `leaguegrid/ingest.py` | Resumable discovery, state downloads and attempt outcomes |
| `leaguegrid/catalog.py` | DuckDB tables, normalization, search, coverage and similarity |
| `CATALOG.md` | Keys, relationships, source mappings and baseline equations |
| `queries/` | Discovery, state and schema query templates |
| `PROJECT.md` | Planned data model, features and evaluation |
| `tests/` | Synthetic offline client, ingestion, normalization and ranking checks |
| `.github/workflows/tests.yml` | Run tests on pushes and pull requests |

## Data access and documentation

GRID Open Access is for noncommercial experimentation. Confirm your account's
current terms before retaining, sharing or redistributing data. Raw responses and
credentials are excluded from Git. No license grant over GRID data is implied.

The public docs describe Central Data and Series State access. Series Events and
File Download require different access. Completed Series State responses contain
final aggregates; historical gameplay trajectories require a separate source or
snapshots collected over time.

- [Open Access overview](https://grid.gg/riot-open-access/)
- [Quick start and endpoint examples](https://grid.helpjuice.com/client-help/open-access-quickstart)
- [Open Access API availability](https://grid.helpjuice.com/client-help/what-apis-does-an-open-access-developer-have-access-to)
- [Authenticated schema documentation](https://grid.helpjuice.com/how-to-get-the-gql-api-documentation)
- [Documented request limits](https://grid.helpjuice.com/rate-limits-for-products)
- [Loopfeed test IDs](https://grid.helpjuice.com/what-are-the-ids-that-we-can-use-for-the-test-loop-series)
