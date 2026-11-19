"""Small, read-only GraphQL client with conservative sequential request pacing."""
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ENDPOINTS = {
    'central': 'https://api-op.grid.gg/central-data/graphql',
    'state': 'https://api-op.grid.gg/live-data-feed/series-state/graphql',
}


class GridError(RuntimeError):
    """Safe diagnostic that never includes request headers or the API key."""


class GridClient:
    def __init__(self, key):
        if not key or not key.strip():
            raise GridError('Set GRID_API_KEY in your environment or local .env file.')
        self.key = key.strip()
        self.last_request = None

    def query(self, api, document, variables=None):
        if api not in ENDPOINTS:
            raise GridError('Choose central or state.')
        for attempt in range(3):
            # Ten seconds between requests is below both documented OA limits.
            # Single-process use only. Multiple processes share the same account quota.
            if self.last_request is not None:
                time.sleep(max(0, 10.1 - (time.monotonic() - self.last_request)))
            request = Request(ENDPOINTS[api],
                              data=json.dumps({'query': document, 'variables': variables or {}}).encode(),
                              headers={'Content-Type': 'application/json', 'x-api-key': self.key},
                              method='POST')
            self.last_request = time.monotonic()
            try:
                with urlopen(request, timeout=30) as response:
                    result = json.load(response)
            except HTTPError as error:
                if error.code in (429, 500, 502, 503, 504) and attempt < 2:
                    try:
                        retry_after = float(error.headers.get('Retry-After', 0))
                    except (ValueError, TypeError):
                        retry_after = 0
                    if retry_after > 120:
                        raise GridError('Rate limited. Retry later as directed by the server.') from None
                    time.sleep(max(retry_after, 2 ** attempt))
                    continue
                raise GridError(f'GRID returned HTTP {error.code}. Check access, query and request limits.') from None
            except (URLError, TimeoutError):
                if attempt < 2:
                    continue
                raise GridError('GRID network request failed after three attempts.') from None
            except (ValueError, UnicodeDecodeError):
                raise GridError('GRID returned an invalid JSON response.') from None
            if not isinstance(result, dict):
                raise GridError('GRID returned an unexpected response shape.')
            if result.get('errors'):
                # GraphQL can return partial data with HTTP 200. Fail explicitly.
                messages = [str(e.get('message', 'GraphQL error')) for e in result['errors']]
                safe = ' | '.join(messages).replace(self.key, '[REDACTED]')
                raise GridError('GraphQL errors: ' + safe[:1000])
            if result.get('data') is None:
                raise GridError('Response has no GraphQL data.')
            return result['data']
