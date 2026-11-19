"""Bounded, sequential GRID ingestion with durable raw files and per-series outcomes."""
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

from leaguegrid.catalog import insert, is_league_esports, normalize
from leaguegrid.client import GridError

START = '2026-11-01T00:00:00Z'
END = '2026-11-30T23:59:59.999999Z'


def state_status(data):
    if 'seriesState' not in data: return 'unavailable_omitted'
    if data['seriesState'] is None: return 'unavailable_null'
    state = data['seriesState']
    if not isinstance(state, dict): raise ValueError('Malformed seriesState')
    return 'completed' if state.get('finished') is True else 'unfinished'


def cached_states(directory):
    """Reuse completed downloads with per-game validity selected by the new query."""
    found = {}
    for path in sorted(Path(directory).glob('*.json')):
        try:
            doc = json.loads(path.read_text())
            if doc.get('api') != 'state': continue
            state = doc['data'].get('seriesState')
            if not isinstance(state,dict) or state.get('finished') is not True: continue
            games = state.get('games')
            if not isinstance(games,list) or not games or any('valid' not in g for g in games): continue
            sid = state['id']
            if sid not in found or (doc.get('retrieved_at') or '') > (found[sid][1].get('retrieved_at') or ''):
                found[sid] = (path,doc)
        except (ValueError, KeyError, TypeError):
            continue
    return found


def discovery(directory, client_factory, save, build_query, start=START, end=END, explicit=None):
    candidates = [Path(explicit)] if explicit else sorted(Path(directory).glob('series-central-*.json'),reverse=True)
    for path in candidates:
        doc = json.loads(path.read_text())
        request = doc.get('request')
        # Legacy audit response was the complete November window, before request metadata existed.
        compatible = (request and request.get('start')==start and request.get('end')==end) or (not request and start==START and end==END)
        if not compatible and not explicit: continue
        connection = doc['data'].get('allSeries') or {}
        if connection.get('pageInfo',{}).get('hasNextPage') is False and len(connection.get('edges',[]))==connection.get('totalCount'):
            return [(edge['node'],path) for edge in connection['edges']], {'source':'saved','complete':True,'file':str(path)}
        if explicit:
            raise ValueError('Discovery file must contain the complete connection, not a partial page')
    client = client_factory()
    edges, cursor, seen = [], None, set()
    while True:
        data = client.query('central',build_query(start,end,cursor))
        save(directory,'central','series-page',data,{'start':start,'end':end,'after':cursor})
        connection = data.get('allSeries')
        if not isinstance(connection,dict): raise GridError('Discovery omitted allSeries')
        edges.extend(connection['edges'])
        page=connection['pageInfo']
        if not page['hasNextPage']: break
        cursor=page['endCursor']
        if not cursor or cursor in seen: raise GridError('Discovery cursor did not advance')
        seen.add(cursor)
    if len(edges)!=connection['totalCount'] or len({e['node']['id'] for e in edges})!=len(edges):
        raise GridError('Discovery changed during pagination; retry to establish complete coverage')
    data={'allSeries':dict(connection,edges=edges)}
    path=save(directory,'central','series',data,{'start':start,'end':end})
    return [(e['node'],path) for e in edges], {'source':'live','complete':True,'file':str(path)}


def ingest(con, directory, client_factory, save, read_query, build_query,
           start=START, end=END, refresh=False, discovery_file=None):
    if datetime.fromisoformat(start.replace('Z','+00:00')) >= datetime.fromisoformat(end.replace('Z','+00:00')):
        raise ValueError('Start must precede end')
    # One client across discovery and state calls preserves the account pacing.
    client = None
    def get_client():
        nonlocal client
        if client is None: client=client_factory()
        return client
    entries, info = discovery(directory,get_client,save,build_query,start,end,discovery_file)
    lo,hi = (datetime.fromisoformat(v.replace('Z','+00:00')) for v in (start,end))
    selected=[]
    for node,path in entries:
        if not is_league_esports(node): continue
        when=datetime.fromisoformat(node['startTimeScheduled'].replace('Z','+00:00'))
        if lo<=when<=hi: selected.append((node,path))
    cached=cached_states(directory)
    outcomes=[]
    for node, discovery_path in selected:
        sid=node['id']
        aid=uuid.uuid4().hex
        insert(con,'ingestion_attempts',dict(attempt_id=aid,series_id=sid,
               attempted_at=datetime.now(timezone.utc).isoformat(),status='running',detail=None,source_file=None))
        path=None
        reused=not refresh and sid in cached
        try:
            if reused:
                path,document=cached[sid]
                data=document['data']
            else:
                data=get_client().query('state',read_query('state').replace('__SERIES_ID__',json.dumps(sid)))
                path=save(directory,'state','state',data,{'series_id':sid})
                document=json.loads(Path(path).read_text())
            status=state_status(data)
            con.execute('UPDATE ingestion_attempts SET status=?,source_file=? WHERE attempt_id=?',['downloaded' if status=='completed' else status,str(path),aid])
            if status=='completed':
                state=data['seriesState']
                if state.get('id')!=sid: raise ValueError('State identity mismatch')
                try:
                    normalize(con,node,document,path,discovery_path)
                except Exception as error:
                    con.execute('UPDATE ingestion_attempts SET status=?,detail=? WHERE attempt_id=?', ['normalization_error',type(error).__name__,aid])
                    outcomes.append({'series_id':sid,'status':'normalization_error','detail':type(error).__name__})
                    continue
                status='success'
            con.execute('UPDATE ingestion_attempts SET status=? WHERE attempt_id=?',[status,aid])
            outcomes.append({'series_id':sid,'status':status,'reused_download':reused,'source_file':str(path)})
        except (GridError,ValueError,KeyError,TypeError,OSError) as error:
            # Only GridError has a credential-safe contract. Never serialize response objects in errors.
            detail=str(error) if isinstance(error,GridError) else type(error).__name__
            con.execute('UPDATE ingestion_attempts SET status=?,detail=?,source_file=? WHERE attempt_id=?',['error',detail,str(path) if path else None,aid])
            outcomes.append({'series_id':sid,'status':'error','detail':detail})
    return {'discovery':info,'listed_series':len(entries),'selected_league_esports':len(selected),'outcomes':outcomes}
