"""Synthetic fixtures only: no credentials or GRID response samples in Git."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from leaguegrid import catalog as c
from leaguegrid.client import GridError
from leaguegrid.ingest import ingest, state_status
from leaguegrid.storage import save_json


def fixture(sid='s1', gid='g1'):
    node={'id':sid,'title':{'id':'3','name':'League of Legends'},'type':'ESPORTS',
          'startTimeScheduled':'2026-11-03T22:00:00Z','tournament':{'id':'t1','name':'Synthetic Cup'}}
    def player(pid,champion):
        return {'id':pid,'name':pid,'character':{'id':champion,'name':champion},'roles':[],
                'kills':0,'deaths':1,'killAssistsGiven':0,'money':0,'netWorth':1000,
                'loadoutValue':1000,'totalMoneyEarned':1200,'unitKills':[], 'objectives':None}
    def team(tid,champion):
        return {'id':tid,'name':tid,'players':[player('p'+tid,champion)],'kills':0,'money':0,
                'netWorth':1000,'loadoutValue':1000,'totalMoneyEarned':1200,'moneyDifference':0,
                'unitKills':[{'id':'u'+tid,'unitName':'minion','count':0}],
                'objectives':[{'id':'o'+tid,'type':'slayDragon','completionCount':2,'completedFirst':True},
                              {'id':'e'+tid,'type':'slayInfernalDrake','completionCount':2}]}
    game={'id':gid,'sequenceNumber':1,'started':True,'finished':True,'valid':True,
          'startedAt':'2026-11-03T22:15:00Z','duration':'PT30M0.5S',
          'clock':{'currentSeconds':1700,'ticking':False},'teams':[team('a','Ahri'),team('b','Vi')],
          'structures':[{'id':'tower1','type':'tower','teamId':'a','destroyed':False}],
          'draftActions':[{'id':'d1','type':'ban','sequenceNumber':'1','drafter':{'id':'a'},
                           'draftable':{'id':'Garen','name':'Garen','type':'character'}}]}
    state={'id':sid,'title':{'nameShortened':'lol'},'finished':True,'valid':True,'games':[game]}
    return node, {'api':'state','retrieved_at':'2026-11-19T21:00:00Z','data':{'seriesState':state}}


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.con=c.connect(self.root/'test.duckdb')
        self.node,self.doc=fixture()

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def load(self,node=None,doc=None):
        c.normalize(self.con,node or self.node,doc or self.doc,'raw.json','discovery.json')

    def test_normalization_grains_provenance_and_economy(self):
        self.load()
        self.assertEqual(c.rows(self.con,'SELECT * FROM series')[0]['source_file'],'raw.json')
        self.assertEqual(self.con.execute('SELECT count(*) FROM game_players').fetchone()[0],2)
        row=c.rows(self.con,'SELECT * FROM game_teams ORDER BY team_id')[0]
        self.assertEqual([row[k] for k in c.ECONOMY],[0,1000,1000,1200,0])
        game=c.rows(self.con,'SELECT * FROM games')[0]
        self.assertEqual(game['duration'],'PT30M0.5S')
        self.assertEqual(game['duration_seconds'],1800.5)
        self.assertEqual(game['clock_seconds'],1700)
        self.assertEqual(self.con.execute('SELECT count(*) FROM structures').fetchone()[0],1)

    def test_idempotence_and_stable_composite_game_keys(self):
        self.load();self.load()
        self.assertEqual(self.con.execute('SELECT count(*) FROM objectives').fetchone()[0],4)
        node,doc=fixture('s2','g1');self.load(node,doc)
        self.assertEqual(self.con.execute('SELECT count(*) FROM games').fetchone()[0],2)

    def test_transaction_rolls_back_after_partial_write(self):
        self.load()
        bad=copy.deepcopy(self.doc)
        game=bad['data']['seriesState']['games'][0]
        game['teams'][0]['money']=999
        game['teams'].append(copy.deepcopy(game['teams'][0]))
        with self.assertRaises(c.duckdb.ConstraintException): self.load(doc=bad)
        self.assertEqual(self.con.execute('SELECT money FROM game_teams WHERE team_id=\'a\'').fetchone()[0],0)
        self.assertEqual(self.con.execute('SELECT count(*) FROM game_players').fetchone()[0],2)

    def test_missing_null_empty_and_zero_remain_distinct(self):
        game=self.doc['data']['seriesState']['games'][0]
        a,b=game['teams'][0]['players'][0],game['teams'][1]['players'][0]
        a['damageDealt']=None
        b['damageDealt']=0
        self.load()
        report=c.coverage(self.con)['field_coverage']['game_players']
        self.assertEqual(report['damageDealt'],{'null':1,'zero':1})
        self.assertEqual(report['experiencePoints'],{'omitted':2})
        self.assertEqual(report['roles'],{'empty_list':2})
        self.assertEqual(report['objectives'],{'null':2})
        self.assertEqual(c.rows(self.con,'SELECT roles_json FROM game_players')[0]['roles_json'],'[]')

    def test_champion_played_is_separate_from_bans_and_exact_filters(self):
        self.load()
        self.assertEqual(len(c.search(self.con,champion='Ahri',team='a',tournament='Synthetic Cup',start='2026-11-03',end='2026-11-03',min_kills=0,max_kills=0)),1)
        self.assertEqual(c.search(self.con,champion='Garen'),[])
        self.assertEqual(c.search(self.con,champion='ahri'),[])
        self.assertEqual(c.search(self.con,team='unknown'),[])
        self.assertEqual(len(c.display_game(self.con,'s1:g1')['draft_actions']),1)

    def test_exact_objectives_do_not_sum_elements_or_player_counts(self):
        self.load()
        self.assertEqual(c.objective_count(self.con,'s1','g1','slayDragon'),4)
        self.assertEqual(c.objective_count(self.con,'s1','g1','slayInfernalDrake'),4)
        self.assertIsNone(c.objective_count(self.con,'s1','g1','slayBaron'))
        self.assertEqual(len(c.search(self.con,objective='slayDragon',min_objectives=4,max_objectives=4)),1)
        self.assertEqual(c.search(self.con,objective='slayDragon',min_objectives=5),[])
        with self.assertRaises(ValueError): c.search(self.con,min_objectives=1)
        coverage=c.coverage(self.con)['search_feature_coverage']
        self.assertEqual(coverage['slayDragon']['known'],1)
        self.assertEqual(coverage['slayBaron']['unknown'],1)
        for team in self.doc['data']['seriesState']['games'][0]['teams']:
            team['objectives']=[{'id':'z','type':'slayDragon','completionCount':0}]
        self.load()
        self.assertEqual(c.objective_count(self.con,'s1','g1','slayDragon'),0)
        self.doc['data']['seriesState']['games'][0]['teams'][0]['objectives']=[]
        self.load()
        self.assertIsNone(c.objective_count(self.con,'s1','g1','slayDragon'))

    def test_game_validity_must_be_explicit_not_inferred_from_series(self):
        game=self.doc['data']['seriesState']['games'][0]
        del game['valid'];self.load()
        self.assertEqual(c.search(self.con),[])
        game['valid']=False;self.load()
        self.assertEqual(c.search(self.con),[])
        game['valid']=True;game['finished']=False;self.load()
        self.assertEqual(c.search(self.con),[])

    def test_loopfeeds_valorant_and_unfinished_series_are_rejected(self):
        self.node['type']='LOOPFEED'
        with self.assertRaises(ValueError): self.load()
        self.node['type']='ESPORTS';self.node['title']['id']='6'
        with self.assertRaises(ValueError): self.load()
        self.node['title']['id']='3';self.doc['data']['seriesState']['finished']=False
        with self.assertRaises(ValueError): self.load()

    def test_deterministic_similarity_components_and_missing_features(self):
        self.load()
        for sid in ('s3','s2'):
            node,doc=fixture(sid)
            self.load(node,doc)
        result=c.similar(self.con,'s1:g1')
        self.assertEqual([r['key'] for r in result],['s2:g1','s3:g1'])
        self.assertEqual(result[0]['score'],1)
        self.assertEqual(result[0]['shared_champions'],['Ahri','Vi'])
        self.assertEqual(result[0]['numeric_features_used'],3)  # kills, duration, dragons
        self.assertNotIn('money',str(result[0]['numerical_comparisons']))
        self.assertEqual(c.similar(self.con,'s1:g1'),result)
        with self.assertRaises(ValueError): c.similar(self.con,'s1:g1',0,0)
        node,doc=fixture('s4')
        game=doc['data']['seriesState']['games'][0]
        game.pop('duration')
        game['teams'][0]['players'][0].pop('character')
        self.load(node,doc)
        r=next(r for r in c.similar(self.con,'s1:g1',limit=10) if r['series_id']=='s4')
        self.assertIsNone(r['champion_score'])
        self.assertEqual(r['numeric_features_used'],2)
        self.assertEqual(r['score'],1)

    def test_duration_and_numeric_filter_missing_does_not_become_zero(self):
        self.doc['data']['seriesState']['games'][0].pop('duration')
        self.doc['data']['seriesState']['games'][0]['teams'][0].pop('kills')
        self.load()
        self.assertEqual(c.search(self.con,min_duration=0),[])
        self.assertEqual(c.search(self.con,min_kills=0),[])
        self.assertEqual(c.duration_seconds('PT0S'),0)
        self.assertEqual(c.duration_seconds('P1DT1H'),90000)
        with self.assertRaises(ValueError): c.duration_seconds('bogus')
        with self.assertRaises(ValueError): c.search(self.con,min_duration=float('nan'))
        with self.assertRaises(ValueError): c.search(self.con,min_kills=10,max_kills=1)


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.con=c.connect(self.root/'test.duckdb');self.node,self.doc=fixture()
        self.calls=[]

    def tearDown(self):
        self.con.close();self.tmp.cleanup()

    def save(self,directory,api,operation,data,metadata=None):
        path=Path(directory)/(operation+'-'+api+'-'+str(len(list(Path(directory).glob('*.json'))))+'.json')
        save_json(path,dict(api=api,data=data,retrieved_at=datetime.now(timezone.utc).isoformat(),request=metadata))
        return path

    def discover(self,nodes):
        path=self.root/'series-central-test.json'
        save_json(path,{'data':{'allSeries':{'totalCount':len(nodes),'edges':[{'node':n} for n in nodes],
                    'pageInfo':{'hasNextPage':False,'endCursor':'end'}}}})
        return path

    def run_ingest(self,results,refresh=False):
        outer=self
        class Client:
            def query(self,api,query):
                outer.calls.append((api,query))
                result=results.pop(0)
                if isinstance(result,Exception):raise result
                return result
        return ingest(self.con,self.root,Client,self.save,lambda _: '__SERIES_ID__',lambda *args:'discovery',refresh=refresh)

    def test_resumable_ingestion_reuses_download_and_refreshes_explicitly(self):
        self.discover([self.node])
        self.assertEqual(self.run_ingest([self.doc['data']])['outcomes'][0]['status'],'success')
        self.assertEqual(self.run_ingest([])['outcomes'][0]['reused_download'],True)
        self.assertEqual(len(self.calls),1)
        self.run_ingest([self.doc['data']],refresh=True)
        self.assertEqual(len(self.calls),2)
        self.assertEqual(self.con.execute('SELECT count(*) FROM games').fetchone()[0],1)

    def test_outcomes_are_separate_and_loopfeeds_excluded(self):
        nodes=[]
        for sid in ('s1','s2','s3','s4','s5','s6'):
            node,_=fixture(sid);nodes.append(node)
        loop=copy.deepcopy(self.node);loop['id']='71';loop['type']='LOOPFEED'
        val=copy.deepcopy(self.node);val['id']='v';val['title']['id']='6'
        self.discover(nodes+[loop,val])
        unfinished=fixture('s3')[1]['data'];unfinished['seriesState']['finished']=False
        malformed=fixture('s6')[1]['data'];malformed['seriesState']['games'][0]['duration']='bad'
        results=[{}, {'seriesState':None},unfinished,GridError('network failure'),fixture('s5')[1]['data'],malformed]
        out=self.run_ingest(results)
        self.assertEqual(out['selected_league_esports'],6)
        self.assertEqual([o['status'] for o in out['outcomes']],['unavailable_omitted','unavailable_null','unfinished','error','success','normalization_error'])
        self.assertEqual(self.con.execute('SELECT count(*) FROM series').fetchone()[0],1)
        report=c.coverage(self.con)
        self.assertEqual(len(report['retrieval_failures']),4)
        self.assertEqual(len(report['latest_retrievals']),6)
        self.assertEqual(state_status({}),'unavailable_omitted')
        self.assertEqual(state_status({'seriesState':None}),'unavailable_null')

    def test_raw_saved_before_normalization_failure_and_resume_without_network(self):
        self.discover([self.node])
        with patch('leaguegrid.ingest.normalize',side_effect=ValueError('synthetic failure')):
            self.assertEqual(self.run_ingest([self.doc['data']])['outcomes'][0]['status'],'normalization_error')
        self.assertEqual(self.run_ingest([])['outcomes'][0]['status'],'success')
        self.assertEqual(len(self.calls),1)

    def test_legacy_cache_without_game_validity_requires_upgrade(self):
        self.discover([self.node])
        old=copy.deepcopy(self.doc);del old['data']['seriesState']['games'][0]['valid']
        save_json(self.root/'old.json',old)
        self.run_ingest([self.doc['data']])
        self.assertEqual(len(self.calls),1)
        self.assertEqual(c.coverage(self.con)['catalog_games'],1)

    def test_discovery_pagination_and_reuse(self):
        second,_=fixture('s2')
        pages=[{'allSeries':{'totalCount':2,'edges':[{'node':self.node}],
                'pageInfo':{'hasNextPage':True,'endCursor':'cursor'}}},
               {'allSeries':{'totalCount':2,'edges':[{'node':second}],
                'pageInfo':{'hasNextPage':False,'endCursor':'end'}}}]
        result=self.run_ingest(pages+[self.doc['data'],fixture('s2')[1]['data']])
        self.assertEqual(result['discovery']['source'],'live')
        self.assertEqual(result['selected_league_esports'],2)
        result=self.run_ingest([])
        self.assertEqual(result['discovery']['source'],'saved')
        self.assertEqual(len(self.calls),4)


if __name__=='__main__':unittest.main()
