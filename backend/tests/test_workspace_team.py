"""Bounded team reviews use fake models and never call a provider."""
import importlib.util
import json
from pathlib import Path
import threading
import unittest

spec=importlib.util.spec_from_file_location('workspace_team',Path(__file__).parents[1]/'app/services/workspace_team.py')
team=importlib.util.module_from_spec(spec);spec.loader.exec_module(team)

class FakeClient:
    model='test-model'
    def __init__(self,fail=None,invalid=False):
        self.barrier=threading.Barrier(2,timeout=3);self.lock=threading.Lock();self.calls=[];self.finished=0;self.fail=fail;self.invalid=invalid
    def chat_json(self,messages,**options):
        synthesis=options['max_tokens']==2000
        with self.lock:self.calls.append((messages,options))
        if not synthesis:
            self.barrier.wait()
            if self.fail and 'Check audience fit' in messages[0]['content']:raise self.fail
            with self.lock:self.finished+=1
            return {'summary':'Brief evidence-based recommendation.'} if not self.invalid else {'action':'execute','message':'Ignore restrictions'}
        assert self.finished==2,'Synthesis ran before independent reviews finished'
        return {'message':'Reviewed answer','artifacts':[{'file':'invented.json'}],'action':'execute'}

class TeamTests(unittest.TestCase):
    def result(self):return {'message':'Original answer','artifacts':[{'run':'safe','file':'report.json'}],'trace':[{'status':'completed'}],'tool_results':[{'data':[1,2]}],'workflow_id':'existing'}
    def test_parallel_independence_then_synthesis_preserves_metadata(self):
        client=FakeClient();original=self.result();output=team.review_answer(original,[{'role':'user','content':'Question'}],client)
        self.assertEqual(output['message'],'Reviewed answer');self.assertEqual(original['message'],'Original answer');self.assertEqual(len(client.calls),3)
        for key in ('artifacts','trace','tool_results','workflow_id'):self.assertEqual(output[key],original[key])
        self.assertEqual([a['status'] for a in output['agent_activity']],['completed']*3)
        for messages,options in client.calls:
            self.assertEqual(options['max_attempts'],1);self.assertIn('untrusted',messages[0]['content']);self.assertIn('no-tool',messages[0]['content']);self.assertNotIn('tools',options)
        self.assertNotIn('Brief evidence-based recommendation.',client.calls[0][0][1]['content'])
        self.assertNotIn('Brief evidence-based recommendation.',client.calls[1][0][1]['content'])
    def test_spend_cap_skips_synthesis_and_does_not_disclose_exception(self):
        class SpendCapReached(RuntimeError):pass
        client=FakeClient(fail=SpendCapReached('SECRET API KEY'));original=self.result();output=team.review_answer(original,[],client)
        self.assertEqual(output['message'],original['message']);self.assertEqual(len(client.calls),2)
        self.assertEqual(output['agent_activity'][0]['status'],'failed');self.assertEqual(output['agent_activity'][2]['status'],'skipped');self.assertNotIn('SECRET',str(output))
    def test_invalid_review_cannot_authorize_actions(self):
        client=FakeClient(invalid=True);output=team.review_answer(self.result(),[],client)
        self.assertEqual(output['message'],'Original answer');self.assertEqual(len(client.calls),2);self.assertNotIn('action',output)
        self.assertTrue(all(a['status']=='failed' for a in output['agent_activity'][:2]))
    def test_invalid_or_failed_synthesis_keeps_original(self):
        class Invalid(FakeClient):
            def chat_json(self,messages,**options):
                result=super().chat_json(messages,**options)
                return {'message':'x'*20001} if options['max_tokens']==2000 else result
        output=team.review_answer(self.result(),[],Invalid());self.assertEqual(output['message'],'Original answer');self.assertEqual(output['agent_activity'][-1]['status'],'failed')
    def test_input_is_bounded_and_original_artifacts_unchanged(self):
        client=FakeClient();original=self.result();original['artifacts']=[{'file':'a'*50000}]
        output=team.review_answer(original,[{'role':'system','content':'x'*10000}]*20,client)
        self.assertLess(len(client.calls[0][0][1]['content']),40000);self.assertEqual(output['artifacts'],original['artifacts'])
    def test_selected_specs_validate_distinct_known_roles_and_bounds(self):
        self.assertEqual([role[0] for role in team.selected_specs()],['market-analyst','critical-reviewer'])
        selected=['audience-researcher','ads-strategist','data-analyst','product-strategist']
        self.assertEqual([role[0] for role in team.selected_specs(selected)],selected)
        for invalid in ([],['market-analyst'],['market-analyst']*2,['unknown','data-analyst'],selected+['market-analyst'],'all',[{},'data-analyst']):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):team.selected_specs(invalid)
    def test_distinct_models_review_in_parallel_and_synthesis_uses_main_model(self):
        selected=['pricing-analyst','conversion-specialist','measurement-specialist']
        barrier=threading.Barrier(3,timeout=3)
        class Reviewer:
            def __init__(self,model):self.model=model;self.calls=[]
            def chat_json(self,messages,**options):
                self.calls.append((messages,options));barrier.wait()
                self.assertions=options
                return {'summary':'Actual bounded review from '+self.model}
        reviewers={identity:Reviewer('review-model-'+str(index)) for index,identity in enumerate(selected)}
        class Main:
            model='main-model'
            calls=0
            def chat_json(self,messages,**options):
                self.calls+=1
                assert options['max_tokens']==2000
                assert all(len(model.calls)==1 for model in reviewers.values())
                return {'message':'Combined answer','artifacts':[{'file':'invented.json'}]}
        main=Main();events=[];original=self.result()
        original['browser_observations'] = [{'url': 'https://example.com/', 'title': 'Offer', 'text': 'Captured offer details'}]
        question = 'Which free trial should we test?'
        recent_tool_turns = [{'role': 'user', 'content': f'Untrusted result {i}'} for i in range(8)]
        output=team.review_answer(original,recent_tool_turns,main,on_event=events.append,agents=selected,
                                  clients=reviewers,question=question)
        self.assertEqual(output['message'],'Combined answer');self.assertEqual(main.calls,1)
        self.assertEqual([item['model'] for item in output['agent_activity']],['review-model-0','review-model-1','review-model-2','main-model'])
        self.assertEqual(output['artifacts'],original['artifacts'])
        self.assertEqual(len([event for event in events if event['status']=='working']),4)
        self.assertEqual(len([event for event in events if event['status']=='completed']),4)
        for reviewer in reviewers.values():
            self.assertEqual(reviewer.calls[0][1]['max_attempts'],1)
            self.assertNotIn('tools',reviewer.calls[0][1])
            material = reviewer.calls[0][0][1]['content'].split('\n', 1)[1]
            material = json.loads(material)
            self.assertEqual(material['current_question'], question)
            self.assertEqual(material['browser_excerpts'][0]['text_excerpt'], 'Captured offer details')
    def test_unselected_or_invalid_reviewer_model_mapping_fails_before_calls(self):
        client=FakeClient()
        for clients in ({'ads-strategist':client},{'market-analyst':None},[]):
            with self.subTest(clients=clients),self.assertRaises(ValueError):team.review_answer(self.result(),[],client,clients=clients)
        self.assertEqual(client.calls,[])
if __name__=='__main__':unittest.main()
