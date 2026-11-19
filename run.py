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
    parser = argparse.ArgumentParser(description='Audit GRID access before building match discovery.')
    commands = parser.add_subparsers(dest='command', required=True)
    series = commands.add_parser('series', help='List accessible series within a date window')
    series.add_argument('--start', required=True)
    series.add_argument('--end', required=True)
    series.add_argument('--pages', type=int, default=1, help='Maximum pages this run, default 1')
    series.add_argument('--after', help='Resume using endCursor from the previous response')
    state = commands.add_parser('state', help='Inspect one actual series or test Loopfeed ID 3')
    state.add_argument('--id', required=True)
    schema = commands.add_parser('schema', help='Save authenticated GraphQL schema documentation')
    schema.add_argument('--api', choices=('central', 'state'), required=True)
    fields = commands.add_parser('fields', help='Summarize observed response fields offline')
    fields.add_argument('response', type=Path)
    for command in (series, state, schema):
        command.add_argument('--output-dir', type=Path, default=ROOT / 'data' / 'raw')
    args = parser.parse_args()
    try:
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
                save_response(args.output_dir, api, 'series', data)
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
            if args.command == 'state' and data.get('seriesState') is None:
                raise GridError('Series state is null. Check coverage, series ID and account access.')
        return 0
    except (GridError, ValueError, OSError, KeyError) as error:
        # No headers, key values or raw HTTP error bodies are logged.
        print(f'Error: {error}', file=sys.stderr)
        return 1


def save_response(directory, api, operation, data):
    now = datetime.now(timezone.utc)
    path = directory / f'{operation}-{api}-{now:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}.json'
    save_json(path, {'source': 'GRID', 'api': api, 'operation': operation,
                     'retrieved_at': now.isoformat(), 'data': data})
    print(f'Saved {path}')


if __name__ == '__main__':
    sys.exit(main())
