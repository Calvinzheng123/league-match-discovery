import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from leaguegrid.client import GridClient, GridError
from leaguegrid.storage import save_json, load_env
from run import build_series_query, paths_in, validate_state_response


class ClientTests(unittest.TestCase):
    def test_success_sends_header_and_variables(self):
        with patch('leaguegrid.client.urlopen', return_value=io.BytesIO(b'{"data":{"ok":true}}')) as call:
            data = GridClient('test-key').query('state', 'query Q { x }', {'id': '3'})
        request = call.call_args.args[0]
        self.assertEqual(request.get_header('X-api-key'), 'test-key')
        self.assertEqual(json.loads(request.data)['variables'], {'id': '3'})
        self.assertTrue(data['ok'])

    def test_partial_graphql_errors_fail_and_redact_key(self):
        payload = b'{"data":{"ok":true},"errors":[{"message":"test-key rejected"}]}'
        with patch('leaguegrid.client.urlopen', return_value=io.BytesIO(payload)):
            with self.assertRaises(GridError) as caught:
                GridClient('test-key').query('state', 'query { x }')
        self.assertNotIn('test-key', str(caught.exception))

    def test_unauthorized_is_not_retried_or_body_logged(self):
        error = HTTPError('https://api-op.grid.gg', 401, 'Unauthorized', {}, io.BytesIO(b'secret body'))
        with patch('leaguegrid.client.urlopen', side_effect=error) as call:
            with self.assertRaisesRegex(GridError, 'HTTP 401'):
                GridClient('test-key').query('central', 'query { x }')
        self.assertEqual(call.call_count, 1)

    def test_rate_limit_retries_read_request(self):
        error = HTTPError('https://api-op.grid.gg', 429, 'Slow down', {'Retry-After': '1'}, None)
        with patch('leaguegrid.client.urlopen', side_effect=[error, io.BytesIO(b'{"data":{}}')]) as call, patch('leaguegrid.client.time.sleep'):
            GridClient('test-key').query('central', 'query { x }')
        self.assertEqual(call.call_count, 2)

    def test_missing_key(self):
        with self.assertRaises(GridError):
            GridClient('')

    def test_pagination_cursor_is_escaped(self):
        query = build_series_query('start', 'end', 'cursor"bad')
        self.assertIn('after: "cursor\\"bad"', query)
        self.assertNotIn('__FILTER__', query)

    def test_atomic_storage_and_env_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'raw' / 'response.json'
            save_json(target, {'data': {'x': None}})
            self.assertEqual(json.loads(target.read_text())['data']['x'], None)
            env = Path(directory) / '.env'
            env.write_text('GRID_API_KEY="file-key"\n')
            with patch.dict('os.environ', {'GRID_API_KEY': 'existing-key'}):
                load_env(env)
                import os
                self.assertEqual(os.environ['GRID_API_KEY'], 'existing-key')

    def test_field_summary_retains_null_and_array_paths(self):
        paths = paths_in({'games': [{'id': '1', 'clock': None}]})
        self.assertIn('games[].clock [null]', paths)
        self.assertIn('games[].id', paths)

    def test_missing_state_is_distinct_from_explicit_null(self):
        with self.assertRaisesRegex(GridError, 'omitted seriesState'):
            validate_state_response({})
        with self.assertRaisesRegex(GridError, 'explicitly null'):
            validate_state_response({'seriesState': None})
        validate_state_response({'seriesState': {'id': '3'}})


if __name__ == '__main__':
    unittest.main()
