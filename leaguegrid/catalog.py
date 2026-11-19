"""Transactional final-state catalog. Source JSON preserves field availability."""
import json
import math
import re
from collections import Counter
from datetime import date
from pathlib import Path

import duckdb

ECONOMY = ('money', 'netWorth', 'loadoutValue', 'totalMoneyEarned', 'moneyDifference')
STATS = ('kills', 'deaths', 'killAssistsGiven', *ECONOMY, 'moneyPerMinute',
         'experiencePoints', 'damageDealt', 'damageTaken', 'damagePerMinute',
         'kdaRatio', 'killParticipation', 'visionScore', 'visionScorePerMinute')
# Fixed units, not learned/validated: these cap the influence of large magnitudes.
FEATURE_SCALES = {'total_kills': 20, 'duration_seconds': 600,
                  'slayDragon': 4, 'slayBaron': 2, 'destroyTower': 10}
TABLES = ('objectives', 'unit_kills', 'structures', 'draft_actions',
          'game_players', 'game_teams', 'games', 'series')


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute('''CREATE TABLE IF NOT EXISTS series (
        series_id VARCHAR PRIMARY KEY, tournament_id VARCHAR, tournament_name VARCHAR,
        scheduled_at VARCHAR, started_at VARCHAR, updated_at VARCHAR, finished BOOLEAN,
        valid BOOLEAN, duration VARCHAR, discovery_file VARCHAR, source_file VARCHAR,
        retrieved_at VARCHAR, source_json JSON, discovery_json JSON)''')
    con.execute('''CREATE TABLE IF NOT EXISTS games (
        series_id VARCHAR, game_id VARCHAR, sequence_number INTEGER, started_at VARCHAR,
        finished BOOLEAN, valid BOOLEAN, duration VARCHAR, duration_seconds DOUBLE,
        clock_seconds INTEGER, clock_json JSON, source_file VARCHAR, retrieved_at VARCHAR,
        source_json JSON, PRIMARY KEY(series_id, game_id))''')
    stat_sql = ', '.join('"'+s+'" '+('BIGINT' if s in ('kills', 'deaths', 'killAssistsGiven', *ECONOMY, 'experiencePoints', 'damageDealt', 'damageTaken') else 'DOUBLE') for s in STATS)
    con.execute(f'''CREATE TABLE IF NOT EXISTS game_teams (
        series_id VARCHAR, game_id VARCHAR, team_id VARCHAR, name VARCHAR, side VARCHAR,
        won BOOLEAN, {stat_sql}, source_json JSON, PRIMARY KEY(series_id, game_id, team_id))''')
    con.execute(f'''CREATE TABLE IF NOT EXISTS game_players (
        series_id VARCHAR, game_id VARCHAR, player_id VARCHAR, team_id VARCHAR, name VARCHAR,
        champion_id VARCHAR, champion_name VARCHAR, roles_json JSON,
        {stat_sql}, source_json JSON, PRIMARY KEY(series_id, game_id, player_id))''')
    con.execute('''CREATE TABLE IF NOT EXISTS draft_actions (
        series_id VARCHAR, game_id VARCHAR, action_id VARCHAR, sequence_number VARCHAR,
        type VARCHAR, drafter_id VARCHAR, draftable_id VARCHAR, draftable_name VARCHAR,
        draftable_type VARCHAR, source_json JSON, PRIMARY KEY(series_id, game_id, action_id))''')
    for table, label, count in [('objectives', 'type', 'completion_count'), ('unit_kills', 'unit_name', 'count')]:
        con.execute(f'''CREATE TABLE IF NOT EXISTS {table} (
            series_id VARCHAR, game_id VARCHAR, owner_kind VARCHAR, owner_id VARCHAR,
            source_id VARCHAR, {label} VARCHAR, {count} BIGINT, source_json JSON,
            PRIMARY KEY(series_id, game_id, owner_kind, owner_id, source_id))''')
    con.execute('''CREATE TABLE IF NOT EXISTS structures (
        series_id VARCHAR, game_id VARCHAR, structure_id VARCHAR, type VARCHAR,
        team_id VARCHAR, destroyed BOOLEAN, source_json JSON,
        PRIMARY KEY(series_id, game_id, structure_id))''')
    con.execute('''CREATE TABLE IF NOT EXISTS ingestion_attempts (
        attempt_id VARCHAR PRIMARY KEY, series_id VARCHAR, attempted_at VARCHAR,
        status VARCHAR, detail VARCHAR, source_file VARCHAR)''')
    con.execute('''CREATE OR REPLACE VIEW catalog AS
        SELECT g.*, s.tournament_id, s.tournament_name, s.scheduled_at,
          coalesce(g.started_at, s.started_at, s.scheduled_at) AS game_date,
          (SELECT CASE WHEN count(*) >= 2 AND count(kills)=count(*) THEN sum(kills) END
           FROM game_teams t WHERE t.series_id=g.series_id AND t.game_id=g.game_id) AS total_kills
        FROM games g JOIN series s USING(series_id)
        WHERE g.finished IS TRUE AND g.valid IS TRUE
          AND s.finished IS TRUE AND s.valid IS TRUE''')
    return con


def insert(con, table, values):
    cols = ','.join('"'+key+'"' for key in values)
    con.execute(f'INSERT INTO {table} ({cols}) VALUES ({",".join("?" for _ in values)})', list(values.values()))


def encoded(value):
    return json.dumps(value, ensure_ascii=False)


def duration_seconds(value):
    if value is None:
        return None
    match = re.fullmatch(r'P(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?', value)
    if not match or not any(match.groups()):
        raise ValueError('Unsupported GRID duration')
    return sum(float(n or 0)*scale for n, scale in zip(match.groups(), (86400, 3600, 60, 1)))


def is_league_esports(node):
    return (node.get('title') or {}).get('id') == '3' and node.get('type') == 'ESPORTS'


def normalize(con, node, document, source_file, discovery_file=None):
    """Replace a whole completed series atomically. Any malformed row rolls back."""
    state = document['data']['seriesState']
    if not is_league_esports(node) or state['id'] != node['id']:
        raise ValueError('Series identity or League esports classification mismatch')
    if (state.get('title') or {}).get('nameShortened') != 'lol':
        raise ValueError('Series State title is not confirmed League')
    if state.get('finished') is not True:
        raise ValueError('Only completed series can be normalized')
    sid = state['id']
    con.execute('BEGIN TRANSACTION')
    try:
        for table in TABLES:
            con.execute(f'DELETE FROM {table} WHERE series_id=?', [sid])
        tournament = node.get('tournament') or {}
        insert(con, 'series', dict(series_id=sid, tournament_id=tournament.get('id'),
               tournament_name=tournament.get('name'), scheduled_at=node.get('startTimeScheduled'),
               started_at=state.get('startedAt'), updated_at=state.get('updatedAt'),
               finished=state.get('finished'), valid=state.get('valid'), duration=state.get('duration'),
               discovery_file=str(discovery_file) if discovery_file else None,
               source_file=str(source_file), retrieved_at=document.get('retrieved_at'),
               source_json=encoded(state), discovery_json=encoded(node)))
        for game in state.get('games') or []:
            gid = game['id']
            base = dict(series_id=sid, game_id=gid)
            clock = game.get('clock') or {}
            insert(con, 'games', dict(base, sequence_number=game.get('sequenceNumber'),
                   started_at=game.get('startedAt'), finished=game.get('finished'), valid=game.get('valid'),
                   duration=game.get('duration'), duration_seconds=duration_seconds(game.get('duration')),
                   clock_seconds=clock.get('currentSeconds'), clock_json=encoded(game.get('clock')) if 'clock' in game else None,
                   source_file=str(source_file), retrieved_at=document.get('retrieved_at'), source_json=encoded(game)))
            for action in game.get('draftActions') or []:
                # Old audited responses predate selecting action IDs. Sequence is stable within game.
                action_id = action.get('id') or 'sequence:'+action['sequenceNumber']
                draftable, drafter = action.get('draftable') or {}, action.get('drafter') or {}
                insert(con, 'draft_actions', dict(base, action_id=action_id, sequence_number=action.get('sequenceNumber'),
                       type=action.get('type'), drafter_id=drafter.get('id'), draftable_id=draftable.get('id'),
                       draftable_name=draftable.get('name'), draftable_type=draftable.get('type'), source_json=encoded(action)))
            for structure in game.get('structures') or []:
                insert(con, 'structures', dict(base, structure_id=structure['id'], type=structure.get('type'),
                       team_id=structure.get('teamId'), destroyed=structure.get('destroyed'), source_json=encoded(structure)))
            for team in game.get('teams') or []:
                tid = team['id']
                insert(con, 'game_teams', dict(base, team_id=tid, name=team.get('name'), side=team.get('side'),
                       won=team.get('won'), **{s: team.get(s) for s in STATS}, source_json=encoded(team)))
                breakdowns(con, base, 'team', tid, team)
                for player in team.get('players') or []:
                    character = player.get('character') or {}
                    insert(con, 'game_players', dict(base, player_id=player['id'], team_id=tid,
                           name=player.get('name'), champion_id=character.get('id'), champion_name=character.get('name'),
                           roles_json=encoded(player.get('roles')) if 'roles' in player else None,
                           **{s: player.get(s) for s in STATS}, source_json=encoded(player)))
                    breakdowns(con, base, 'player', player['id'], player)
        con.execute('COMMIT')
    except Exception:
        con.execute('ROLLBACK')
        raise


def breakdowns(con, base, kind, owner_id, source):
    for key, table, label, count in [('objectives', 'objectives', 'type', 'completion_count'),
                                    ('unitKills', 'unit_kills', 'unit_name', 'count')]:
        for item in source.get(key) or []:
            name = item.get('type' if key == 'objectives' else 'unitName')
            insert(con, table, dict(base, owner_kind=kind, owner_id=owner_id,
                   source_id=item.get('id') or 'label:'+name, **{label: name,
                   count: item.get('completionCount' if key == 'objectives' else 'count')}, source_json=encoded(item)))


def rows(con, sql, params=()):
    result = con.execute(sql, params)
    columns = [col[0] for col in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]


def objective_count(con, sid, gid, label):
    """Only this exact team objective label; no summing subtypes or players."""
    teams = rows(con, 'SELECT team_id,source_json FROM game_teams WHERE series_id=? AND game_id=?', [sid, gid])
    if len(teams) < 2:
        return None
    total = 0
    for team in teams:
        source = json.loads(team['source_json'])
        if not isinstance(source.get('objectives'), list):
            return None
        matches = [x for x in source['objectives'] if x.get('type') == label]
        # Absent labels remain unknown, even in an empty observed list.
        if not matches or any(x.get('completionCount') is None for x in matches):
            return None
        total += sum(x['completionCount'] for x in matches)
    return total


def game_record(con, row):
    sid, gid = row['series_id'], row['game_id']
    row = {k: v for k,v in row.items() if k not in ('source_json', 'clock_json')}
    row['key'] = sid+':'+gid
    row['teams'] = rows(con, 'SELECT team_id,name,side,won,kills,"totalMoneyEarned","moneyDifference" FROM game_teams WHERE series_id=? AND game_id=? ORDER BY team_id', [sid, gid])
    row['players'] = rows(con, 'SELECT player_id,team_id,name,champion_name,kills,deaths,"killAssistsGiven" FROM game_players WHERE series_id=? AND game_id=? ORDER BY player_id', [sid, gid])
    row['played_champions'] = sorted({p['champion_name'] for p in row['players'] if p['champion_name']})
    row['objectives'] = {label: objective_count(con, sid, gid, label) for label in ('slayDragon','slayBaron','destroyTower')}
    return row


def catalog_records(con):
    return [game_record(con, row) for row in rows(con, 'SELECT * FROM catalog ORDER BY series_id,sequence_number,game_id')]


def exact(value, identity, name):
    return value is None or value in (identity, name)


def search(con, champion=None, team=None, tournament=None, start=None, end=None,
           min_kills=None, max_kills=None, min_duration=None, max_duration=None,
           objective=None, min_objectives=None, max_objectives=None, limit=20):
    numeric = (min_kills, max_kills, min_duration, max_duration, min_objectives, max_objectives)
    if any(v is not None and not math.isfinite(v) for v in numeric):
        raise ValueError('Numerical filter values must be finite')
    for low, high in ((min_kills, max_kills), (min_duration, max_duration), (min_objectives, max_objectives)):
        if low is not None and high is not None and low > high:
            raise ValueError('Minimum filter value must not exceed maximum')
    for value in (start, end):
        if value: date.fromisoformat(value)
    if start and end and start > end:
        raise ValueError('Start date must precede end date')
    if (min_objectives is not None or max_objectives is not None) and not objective:
        raise ValueError('Objective count filters require --objective with an exact source label')
    found = []
    for row in catalog_records(con):
        sid,gid = row['series_id'],row['game_id']
        if champion and not any(exact(champion,p['champion_id'],p['champion_name']) for p in rows(con,'SELECT champion_id,champion_name FROM game_players WHERE series_id=? AND game_id=?',[sid,gid])):
            continue
        if team and not any(exact(team,t['team_id'],t['name']) for t in row['teams']): continue
        if not exact(tournament,row['tournament_id'],row['tournament_name']): continue
        day = (row['game_date'] or '')[:10]
        if (start and (not day or day < start)) or (end and (not day or day > end)): continue
        checks = [(row['total_kills'],min_kills,max_kills), (row['duration_seconds'],min_duration,max_duration)]
        if objective:
            value = objective_count(con,sid,gid,objective)
            row['objectives'][objective] = value
            checks.append((value,min_objectives,max_objectives))
        if any((lo is not None or hi is not None) and (v is None or (lo is not None and v<lo) or (hi is not None and v>hi)) for v,lo,hi in checks): continue
        found.append(row)
    return sorted(found,key=lambda r:(r['game_date'] or '',r['key']))[:limit]


def display_game(con, key):
    sid, separator, gid = key.partition(':')
    if not separator: raise ValueError('Use a game key SERIES_ID:GAME_ID from search')
    records = rows(con, 'SELECT * FROM games WHERE series_id=? AND game_id=?',[sid,gid])
    if not records: raise ValueError('Game not found')
    result = {}
    for table in reversed(TABLES):
        result[table] = rows(con, f'SELECT * FROM {table} WHERE series_id=?'+(' AND game_id=?' if table!='series' else ''), [sid,gid] if table!='series' else [sid])
    return result


def similar(con, key, champion_weight=0.6, numeric_weight=0.4, limit=5):
    if any(not math.isfinite(w) or w < 0 for w in (champion_weight,numeric_weight)) or champion_weight+numeric_weight==0:
        raise ValueError('Weights must be finite, nonnegative, and have a positive sum')
    records = catalog_records(con)
    target = next((r for r in records if r['key']==key),None)
    if target is None: raise ValueError('Selected game is not in the completed, valid catalog')
    def champion_ids(row):
        return {p['champion_id'] for p in rows(con, 'SELECT champion_id FROM game_players WHERE series_id=? AND game_id=?',[row['series_id'],row['game_id']]) if p['champion_id']}
    def complete_champions(row):
        roster = rows(con, 'SELECT champion_id FROM game_players WHERE series_id=? AND game_id=?', [row['series_id'], row['game_id']])
        return bool(roster) and all(p['champion_id'] for p in roster)
    def features(row):
        return {k:row.get(k) if k in ('total_kills','duration_seconds') else row['objectives'].get(k) for k in FEATURE_SCALES}
    a, af = champion_ids(target), features(target)
    results=[]
    for candidate in records:
        if candidate['key']==key: continue
        b,bf = champion_ids(candidate), features(candidate)
        cs = len(a&b)/len(a|b) if a|b else None
        # Missing champions never establish a complete set; suppress overlap if any player is missing one.
        if not complete_champions(target) or not complete_champions(candidate): cs=None
        components=[]
        for name,scale in FEATURE_SCALES.items():
            if af[name] is not None and bf[name] is not None:
                components.append({'feature':name,'selected':af[name],'candidate':bf[name],
                                   'scale':scale,'score':math.exp(-abs(af[name]-bf[name])/scale)})
        ns=sum(c['score'] for c in components)/len(components) if components else None
        denominator=(champion_weight if cs is not None else 0)+(numeric_weight if ns is not None else 0)
        score=((champion_weight*(cs or 0)+numeric_weight*(ns or 0))/denominator) if denominator else None
        candidate.update(score=score,champion_score=cs,numeric_score=ns,
                         shared_champions=sorted(set(target['played_champions'])&set(candidate['played_champions'])),
                         numerical_comparisons=components,numeric_features_used=len(components),
                         weights={'champions':champion_weight,'numeric':numeric_weight})
        results.append(candidate)
    return sorted(results,key=lambda r:(r['score'] is None,-(r['score'] or 0),r['key']))[:limit]


def field_status(obj, path):
    for part in path.split('.'):
        if not isinstance(obj,dict) or part not in obj: return 'omitted'
        obj=obj[part]
        if obj is None: return 'null'
    if obj==[]: return 'empty_list'
    if isinstance(obj,(int,float)) and not isinstance(obj,bool) and obj==0: return 'zero'
    return 'populated'


def coverage(con):
    report={'tables':{t:con.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in TABLES},
            'catalog_games':con.execute('SELECT count(*) FROM catalog').fetchone()[0],
            'attempts_by_status':rows(con,'SELECT status,count(*) AS count FROM ingestion_attempts GROUP BY status ORDER BY status'),
            'latest_retrievals':rows(con,'''SELECT * EXCLUDE(attempt_id) FROM ingestion_attempts
                QUALIFY row_number() OVER(PARTITION BY series_id ORDER BY attempted_at DESC, attempt_id DESC)=1 ORDER BY series_id'''),
            'date_coverage':rows(con,'SELECT min(game_date) AS earliest,max(game_date) AS latest FROM catalog'),
            'tournaments':rows(con,'SELECT tournament_id,tournament_name,count(*) AS games FROM catalog GROUP BY ALL ORDER BY tournament_id'),
            'field_coverage':{}}
    fields={'series':['valid','finished','startedAt','games'],
            'games':['valid','duration','clock.currentSeconds','teams','draftActions','structures'],
            'game_teams':['objectives','unitKills',*STATS],
            'game_players':['character.id','character.name','roles','objectives','unitKills',*STATS]}
    for table,paths in fields.items():
        sources=[json.loads(r[0]) for r in con.execute(f'SELECT source_json FROM {table}').fetchall()]
        report['field_coverage'][table]={path:dict(Counter(field_status(s,path) for s in sources)) for path in paths}
    report['retrieval_failures']=rows(con,"SELECT * EXCLUDE(attempt_id) FROM ingestion_attempts WHERE status IN ('error','normalization_error','unavailable_omitted','unavailable_null') ORDER BY attempted_at,series_id")
    records = catalog_records(con)
    report['search_feature_coverage'] = {}
    for name in FEATURE_SCALES:
        values = [r.get(name) if name in ('total_kills', 'duration_seconds') else r['objectives'].get(name) for r in records]
        report['search_feature_coverage'][name] = {
            'known': sum(v is not None for v in values),
            'unknown': sum(v is None for v in values),
            'zero': sum(v == 0 for v in values)}
    return report
