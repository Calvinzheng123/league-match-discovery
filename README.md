# League Match Discovery

A noncommercial League of Legends esports search and recommendation project
using official Riot GRID data. The first milestone audits account access and
collects small samples. Match search and recommendation follow after the
available fields and historical coverage are verified.

## Quick start

Python 3.10+ and the standard library are sufficient.

```bash
python3 -m venv .venv
source .venv/bin/activate
cp .env.example .env
```

On Windows use `.venv\Scripts\Activate.ps1` and copy `.env.example` to `.env`.
Set `GRID_API_KEY` inside `.env` locally. The CLI reads that file automatically;
existing environment variables take precedence. Keep the key private.

Inspect the authenticated schemas first:

```bash
python3 run.py schema --api central
python3 run.py schema --api state
```

List entitled series for a small window, then inspect a series ID from the output:

```bash
python3 run.py series --start 2026-11-01T00:00:00Z --end 2026-11-20T00:00:00Z --pages 1
python3 run.py state --id YOUR_SERIES_ID
```

This initial query lists whatever series your account can access in the window.
Verify title and entitlement in the schema before adding a League-only filter.
An empty response establishes neither complete coverage nor a broken key.

`series` defaults to one page of 20 entries. Increase `--pages` deliberately.
Every successful page is saved before the next request. If interrupted, resume
using `--after` with the last saved page's `pageInfo.endCursor`.

Inspect the repeating LoL test series separately:

```bash
python3 run.py state --id 3
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

## Current verification status

The CLI and HTTP behavior are covered by offline tests. Authenticated GRID calls
have not been run for this repository. The starter queries draw on public GRID
examples and must be checked against the schema returned for your key. Query
templates live in `queries/` so field corrections are easy to review. Tokens
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
| `queries/` | Discovery, state and schema query templates |
| `PROJECT.md` | Planned data model, features and evaluation |
| `tests/test_client.py` | Offline regression checks |
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
