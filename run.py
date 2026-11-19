"""Run `python3 run.py --help` from the extracted repository."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import uuid

from leaguegrid.client import GridClient, GridError
from leaguegrid.storage import load_env, save_json

ROOT = Path(__file__).resolve().parent


def read_query(name):
    return (ROOT / 'queries' / f'{name}.graphql').read_text(encoding='utf-8')


def build_series_query(start, end, after=None, first=20):
    # GraphQL input objects have unquoted field names. Values use JSON escaping.
    filters = '{startTimeScheduled: {gte: ' + json.dumps(start) + ', lte: ' + json.dumps(end) + '}}'
    return (read_query('series').replace('__FILTER__', filters)
            .replace('__FIRST__', str(first)).replace('__AFTER__', json.dumps(after)))


def paths_in(value, prefix=''):
    """Report observed JSON paths, including explicit nulls, without inventing schema fields."""
    found = set()
    if isinstance(value, dict):
        for name, child in value.items():
            path = f'{prefix}.{name}' if prefix else name
            found.add(path + (' [null]' if child is None else ''))
            found.update(paths_in(child, path))
    elif isinstance(value, list):
        for child in value:
            found.update(paths_in(child, prefix + '[]'))
    return found


def parse_date(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Use timezone-aware dates, for example 2026-11-01T00:00:00Z.')
    return result


def main():
    parser = argparse.ArgumentParser(description='Audit GRID access and search a local League match catalog.')
    commands = parser.add_subparsers(dest='command', required=True)
    series = commands.add_parser('series', help='List accessible series within a date window')
    series.add_argument('--start', required=True)
    series.add_argument('--end', required=True)
    series.add_argument('--pages', type=int, default=1, help='Maximum pages this run, default 1')
    series.add_argument('--after', help='Resume using endCursor from the previous response')
    state = commands.add_parser('state', help='Inspect one actual series or test Loopfeed ID 71')
    state.add_argument('--id', required=True)
    schema = commands.add_parser('schema', help='Save authenticated GraphQL schema documentation')
    schema.add_argument('--api', choices=('central', 'state'), required=True)
    fields = commands.add_parser('fields', help='Summarize observed response fields offline')
    fields.add_argument('response', type=Path)
    ingest = commands.add_parser('ingest', help='Download and normalize completed League esports series')
    ingest.add_argument('--start', default='2026-11-01T00:00:00Z')
    ingest.add_argument('--end', default='2026-11-30T23:59:59.999999Z')
    ingest.add_argument('--discovery', type=Path, help='Complete saved Central Data connection')
    ingest.add_argument('--refresh', action='store_true', help='Fetch state even for completed cached downloads')
    ingest.add_argument('--output-dir', type=Path, default=ROOT / 'data' / 'raw')
    coverage = commands.add_parser('coverage', help='Show tables, availability and retrieval outcomes')
    search = commands.add_parser('search', help='Search completed valid games using exact filters')
    for name in ('champion', 'team', 'tournament', 'start', 'end', 'objective'):
        search.add_argument('--'+name)
    for name in ('min-kills', 'max-kills', 'min-objectives', 'max-objectives'):
        search.add_argument('--'+name, type=int)
    for name in ('min-duration', 'max-duration'):
        search.add_argument('--'+name, type=float, help='GRID duration in seconds, not game clock')
    search.add_argument('--limit', type=int, default=20)
    game = commands.add_parser('game', help='Display all normalized rows and provenance for one game')
    game.add_argument('--id', required=True, help='SERIES_ID:GAME_ID from search')
    similar = commands.add_parser('similar', help='Inspect champion and numerical similarity baseline')
    similar.add_argument('--id', required=True, help='SERIES_ID:GAME_ID from search')
    similar.add_argument('--champion-weight', type=float, default=0.6)
    similar.add_argument('--numeric-weight', type=float, default=0.4)
    similar.add_argument('--limit', type=int, default=5)
    for command in (ingest, coverage, search, game, similar):
        command.add_argument('--db', type=Path, default=ROOT / 'data' / 'catalog.duckdb')
    for command in (series, state, schema):
        command.add_argument('--output-dir', type=Path, default=ROOT / 'data' / 'raw')
    args = parser.parse_args()
    try:
        if args.command in ('ingest', 'coverage', 'search', 'game', 'similar'):
            return catalog_command(args)
        if args.command == 'fields':
            document = json.loads(args.response.read_text(encoding='utf-8'))
            print('\n'.join(sorted(paths_in(document.get('data', document)))))
            return 0
        if args.command == 'series':
            if parse_date(args.start) >= parse_date(args.end):
                raise ValueError('--start must precede --end.')
            if args.pages < 1:
                raise ValueError('--pages must be positive.')
        load_env(ROOT / '.env')
        client = GridClient(os.environ.get('GRID_API_KEY', ''))
        if args.command == 'series':
            api, cursor = 'central', args.after
            seen = set()
            for _ in range(args.pages):
                data = client.query(api, build_series_query(args.start, args.end, cursor))
                save_response(args.output_dir, api, 'series', data,
                              {'start': args.start, 'end': args.end, 'after': cursor})
                connection = data.get('allSeries')
                if not isinstance(connection, dict):
                    raise GridError('allSeries unavailable. Inspect access and authenticated schema.')
                for edge in connection.get('edges', []):
                    print(json.dumps(edge['node'], ensure_ascii=False))
                page = connection['pageInfo']
                print('pageInfo=' + json.dumps(page))
                if not page['hasNextPage']:
                    break
                cursor = page['endCursor']
                if not cursor or cursor in seen:
                    raise GridError('Pagination cursor did not advance. Stopping safely.')
                seen.add(cursor)
        else:
            api = 'state' if args.command == 'state' else args.api
            query = read_query('schema') if args.command == 'schema' else read_query('state').replace('__SERIES_ID__', json.dumps(args.id))
            data = client.query(api, query)
            save_response(args.output_dir, api, args.command, data)
            if args.command == 'state':
                validate_state_response(data)
        return 0
    except (GridError, ValueError, OSError, KeyError) as error:
        # No headers, key values or raw HTTP error bodies are logged.
        print(f'Error: {error}', file=sys.stderr)
        return 1


def validate_state_response(data):
    if 'seriesState' not in data:
        raise GridError('Response omitted seriesState. State access and coverage are unconfirmed for this ID.')
    if data['seriesState'] is None:
        raise GridError('Series state is explicitly null. Check coverage, series ID and account access.')


def catalog_command(args):
    try:
        from leaguegrid import catalog
        from leaguegrid.ingest import ingest
    except ImportError:
        raise GridError('Install catalog dependencies: python -m pip install -r requirements.txt') from None
    if getattr(args, 'limit', 1) < 1:
        raise ValueError('--limit must be positive')
    con = catalog.connect(args.db)
    try:
        if args.command == 'ingest':
            parse_date(args.start)
            parse_date(args.end)
            def client_factory():
                load_env(ROOT / '.env')
                return GridClient(os.environ.get('GRID_API_KEY', ''))
            result = ingest(con, args.output_dir, client_factory, save_response, read_query,
                            build_series_query, args.start, args.end, args.refresh, args.discovery)
        elif args.command == 'coverage':
            result = catalog.coverage(con)
        elif args.command == 'search':
            names = ('champion', 'team', 'tournament', 'start', 'end', 'min_kills', 'max_kills',
                     'min_duration', 'max_duration', 'objective', 'min_objectives', 'max_objectives', 'limit')
            result = catalog.search(con, **{name: getattr(args, name) for name in names})
        elif args.command == 'game':
            result = catalog.display_game(con, args.id)
        else:
            result = catalog.similar(con, args.id, args.champion_weight, args.numeric_weight, args.limit)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if args.command == 'ingest' and any(o['status'] in ('error', 'normalization_error') for o in result['outcomes']):
            return 1
        return 0
    except catalog.duckdb.Error as error:
        raise GridError('Catalog database operation failed ('+type(error).__name__+').') from None
    finally:
        con.close()


def save_response(directory, api, operation, data, metadata=None):
    now = datetime.now(timezone.utc)
    path = directory / f'{operation}-{api}-{now:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}.json'
    save_json(path, {'source': 'GRID', 'api': api, 'operation': operation,
                     'retrieved_at': now.isoformat(), 'data': data,
                     **({'request': metadata} if metadata else {})})
    print(f'Saved {path}')
    return path


if __name__ == '__main__':
    sys.exit(main())
