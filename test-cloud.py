import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

scripts = Path(__file__).parent / 'skills/pod-creative-loop/scripts'
sys.path.insert(0, str(scripts))
spec = importlib.util.spec_from_file_location('creative', scripts / 'creative.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
ev = c.ev


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.old_key = os.environ.get('ARK_API_KEY')
        os.environ['ARK_API_KEY'] = 'test-key-not-a-real-credential'
        self.tmp = tempfile.TemporaryDirectory()
        self.old_root = c.ROOT
        c.ROOT = Path(self.tmp.name)

    def tearDown(self):
        c.ROOT = self.old_root
        self.tmp.cleanup()
        if self.old_key is None:
            os.environ.pop('ARK_API_KEY', None)
        else:
            os.environ['ARK_API_KEY'] = self.old_key

    def rubric(self):
        return [
            {'id':'delivery','description':'Deliver the requested standalone asset','source_requirement':'Provide this asset','required':True,'priority':1,'weight':1,'asset_refs':['design']},
            {'id':'style','description':'Preferred visual style','source_requirement':'Prefer this style','required':False,'priority':2,'weight':1,'asset_refs':['mockup','video']}
        ]

    def report(self, status='pass'):
        return {'summary':'Actual media inspection','checks':[
            {'id':'delivery','status':status,'score':4.7,'evidence':'Observed deliverable','improvement':'Correct the requested asset'},
            {'id':'style','status':'pass','score':4.7,'evidence':'Observed style','improvement':'Refine style'}
        ],'uncovered_requirements':[],'release_checks':[]}

    def audit(self, conflict=False):
        return {'conflicts':[{'id':'delivery','reason':'The evidence says missing but the verdict says pass'}] if conflict else [],'uncovered_requirements':[]}

    def response(self, value):
        return {'id':'test-response','output':[{'content':[{'type':'output_text','text':json.dumps(value)}]}]}

    def init(self, rounds=2, target=4.5, watermark=True):
        c.execute('init',{'brief':'Provide this asset. Prefer this style.','criteria':self.rubric(),'max_rounds':rounds,'target_score':target,'watermark':watermark,'prompts':dict.fromkeys(['design','mockup','video'],'CREATOR_PRIVATE_REASONING')})

    def test_watermark_rejects_non_boolean(self):
        for value in ('false', 0, None):
            with self.assertRaisesRegex(ValueError, 'watermark'):
                self.init(watermark=value)

    def test_limit_prefers_highest_passing_gate_over_failed_higher_score(self):
        s={'status':'max_rounds','target_score':4.9,'rounds':[
            {'number':1,'review':{'score':4.8,'quality_gate':'blocked','checks':[{'status':'fail','id':'missing'}],'uncovered_requirements':[]}},
            {'number':2,'review':{'score':4.7,'quality_gate':'passed','checks':[],'uncovered_requirements':[]}}]}
        self.assertEqual(c.selected_round(s)['number'],2)
        summary=c.result_summary(s)
        self.assertFalse(summary['met_target'])
        self.assertEqual(summary['failed_checks'],[])
        self.assertEqual(summary['score_gap'],0.2)

    def test_limit_falls_back_to_highest_score_when_all_gates_fail(self):
        s={'status':'max_rounds','rounds':[{'number':1,'review':{'score':4.8,'quality_gate':'blocked'}}, {'number':2,'review':{'score':4.4,'quality_gate':'blocked'}}]}
        self.assertEqual(c.selected_round(s)['number'],1)

    def test_early_pass_returns_current_passing_round(self):
        s={'status':'completed','rounds':[{'number':1,'review':{'score':4.9}}, {'number':2,'review':{'score':4.6}}]}
        self.assertEqual(c.selected_round(s)['number'],2)

    def test_equal_scores_keep_earliest_round(self):
        s={'status':'max_rounds','rounds':[{'number':1,'review':{'score':4,'quality_gate':'blocked'}}, {'number':2,'review':{'score':4,'quality_gate':'blocked'}}]}
        self.assertEqual(c.selected_round(s)['number'],1)

    def test_watermark_is_frozen(self):
        self.init(watermark=False)
        s=c.load();s['watermark']=True;c.save(s)
        with self.assertRaisesRegex(ValueError,'Frozen'):
            c.execute('step')

    def test_watermark_false_reaches_both_images_and_video(self):
        self.init(watermark=False)
        with patch.object(c,'api',side_effect=[{'data':[{'url':'https://example.com/design'}]}, {'data':[{'url':'https://example.com/mockup'}]}, {'id':'test-task'}, {'status':'succeeded','content':{'video_url':'https://example.com/video'}}]) as api:
            for _ in range(3):
                c.execute('step')
            for call in api.call_args_list[:3]:
                self.assertIs(call.args[1]['watermark'], False)

    def test_watermark_true_reaches_image_api(self):
        self.init()
        with patch.object(c,'api',return_value={'data':[{'url':'https://example.com/design'}]}) as api:
            c.execute('step')
            self.assertIs(api.call_args.args[1]['watermark'], True)

    def media(self):
        s=c.load();r=s['rounds'][-1]
        r.update(task='fixture-task',submitted_at=c.time.time())
        for phase in ('design','mockup','video'):
            r[phase]={'url':'https://example.com/'+phase}
        c.save(s)
        return s

    def test_dynamic_contract_accepts_different_criteria_counts(self):
        rubric=self.rubric()
        rubric.append({'id':'something-else','description':'Another requirement','source_requirement':'Another request','required':True,'priority':3,'weight':2,'asset_refs':['video']})
        self.assertEqual(len(ev.criteria(rubric)),3)
        with self.assertRaises(ValueError):
            ev.criteria(rubric+[rubric[0]])

    def test_frozen_contract_cannot_change_during_revision(self):
        self.init();s=c.load();s['criteria'][0]['description']='Relaxed requirement';c.save(s)
        with self.assertRaisesRegex(ValueError,'Frozen'):
            c.execute('step')

    def test_creator_cannot_submit_own_score(self):
        self.init()
        with self.assertRaisesRegex(ValueError,'Manual review'):
            c.execute('review',self.report())

    def test_conflict_4_7_revises_then_second_round_passes(self):
        self.init();self.media()
        first=self.report();first['checks'][0]['evidence']='Required deliverable is missing'
        resolution=self.report('fail');resolution['resolutions']=[{'id':'delivery','resolved':True,'reason':'Actual asset lacks the deliverable'}]
        with patch.object(c,'api',side_effect=[self.response(first),self.response(self.audit(True)),self.response(resolution)]) as api:
            self.assertEqual(c.execute('step')['status'],'needs_audit')
            self.assertEqual(c.execute('step')['status'],'needs_adjudication')
            result=c.execute('step')
            self.assertEqual(result['status'],'needs_revision')
            self.assertEqual(result['review']['score'],4.7)
            self.assertEqual(result['review']['blocking_checks'],['delivery'])
            self.assertEqual(api.call_count,3)
        contract=c.load()['contract_hash']
        c.execute('revise',dict.fromkeys(['design','mockup','video'],'improved prompt'))
        self.media()
        with patch.object(c,'api',side_effect=[self.response(self.report()),self.response(self.audit())]):
            c.execute('step')
            self.assertEqual(c.execute('step')['status'],'completed')
        exported=c.execute('export')
        self.assertEqual(exported['best_round'],2)
        self.assertEqual(exported['contract_hash'],contract)
        self.assertEqual(exported['rounds'][0]['review']['quality_gate'],'blocked')
        self.assertEqual(exported['rounds'][1]['review']['quality_gate'],'passed')

    def test_evaluator_context_excludes_creator_prompts_and_history(self):
        self.init();self.media()
        with patch.object(c,'api',return_value=self.response(self.report())) as api:
            c.execute('step')
            body=api.call_args.args[1]
            self.assertNotIn('CREATOR_PRIVATE_REASONING',json.dumps(body))
            self.assertNotIn('previous_response_id',body)
            self.assertEqual(len(body['input']),1)
            self.assertEqual(len(body['input'][0]['content']),4)

    def test_optional_failure_affects_score_not_required_gate(self):
        r=self.report();r['checks'][1].update(status='fail',score=4.5)
        review=ev.effective_review(self.rubric(),r,self.audit())
        self.assertEqual(review['quality_gate'],'passed')
        self.assertEqual(review['score'],4.6)

    def test_required_unverified_blocks_even_high_score(self):
        r=self.report('unverified')
        self.assertEqual(ev.effective_review(self.rubric(),r,self.audit())['quality_gate'],'blocked')

    def test_unresolved_conflict_cannot_pass(self):
        r=self.report();r['resolutions']=[{'id':'delivery','resolved':False,'reason':'Not enough evidence'}]
        result=ev.effective_review(self.rubric(),self.report(),self.audit(True),r)
        self.assertEqual(result['checks'][0]['status'],'unverified')
        self.assertEqual(result['quality_gate'],'blocked')

    def test_conflict_requires_complete_adjudication(self):
        with self.assertRaises(ValueError):
            ev.effective_review(self.rubric(),self.report(),self.audit(True))
        r=self.report();r['resolutions']=[]
        with self.assertRaises(ValueError):
            ev.effective_review(self.rubric(),self.report(),self.audit(True),r)

    def test_omitted_requirements_block_instead_of_mutating_contract(self):
        self.init();self.media()
        audit=self.audit();audit['uncovered_requirements']=['Another explicit user deliverable']
        with patch.object(c,'api',side_effect=[self.response(self.report()),self.response(audit)]):
            c.execute('step')
            self.assertEqual(c.execute('step')['status'],'blocked')
        self.assertEqual(c.execute('export')['status'],'blocked')

    def test_round_limit_preserves_failed_evaluation(self):
        self.init(rounds=1);self.media()
        with patch.object(c,'api',side_effect=[self.response(self.report('fail')),self.response(self.audit())]):
            c.execute('step')
            self.assertEqual(c.execute('step')['status'],'max_rounds')
        self.assertEqual(c.execute('export')['rounds'][0]['review']['quality_gate'],'blocked')
        with self.assertRaises(ValueError):
            c.execute('revise',dict.fromkeys(['design','mockup','video'],'new'))

    def test_bad_evaluation_is_bounded_and_fail_closed(self):
        self.init();self.media()
        with patch.object(c,'api',return_value=self.response({'summary':'looks good'})) as api:
            for _ in range(2):
                with self.assertRaises(ValueError):
                    c.execute('step')
            with self.assertRaisesRegex(RuntimeError,'exhausted'):
                c.execute('step')
            self.assertEqual(api.call_count,2)

    def test_export_rejects_fabricated_review(self):
        self.init();self.media()
        with patch.object(c,'api',side_effect=[self.response(self.report()),self.response(self.audit())]):
            c.execute('step');c.execute('step')
        s=c.load();s['rounds'][0]['review']['score']=5;c.save(s)
        with self.assertRaises(ValueError):
            c.execute('export')

    def test_report_rejects_missing_duplicate_unknown_ids_and_scores(self):
        for mutation in ('missing','duplicate','unknown','score'):
            r=self.report()
            if mutation=='missing': r['checks'].pop()
            elif mutation=='duplicate': r['checks'][1]['id']='delivery'
            elif mutation=='unknown': r['checks'][1]['id']='other'
            else: r['checks'][0]['score']=float('nan')
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                ev.validate_report(r,self.rubric())

    def test_weighted_score_uses_contract_not_reviewer_weights(self):
        rubric=self.rubric();rubric[0]['weight']=3
        r=self.report();r['checks'][0]['score']=4;r['checks'][1]['score']=5
        self.assertEqual(ev.effective_review(rubric,r,self.audit())['score'],4.25)

    def test_stream_requires_completed(self):
        with self.assertRaises(RuntimeError):
            c.response_stream([b'data: [DONE]\n',b'\n'])
        with self.assertRaises(RuntimeError):
            c.response_stream([b'data: {"type":"response.incomplete"}\n',b'\n'])
        event={'type':'response.completed','response':{'status':'completed','id':'r'}}
        self.assertEqual(c.response_stream([('data: '+json.dumps(event)+'\n').encode(),b'\n'])['id'],'r')

    def test_state_edit_detected(self):
        self.init()
        (c.ROOT/'state.json').write_text('{"status":"completed"}')
        with self.assertRaises(RuntimeError):
            c.load()

    def test_transient_video_retries_are_bounded_and_persisted(self):
        self.init();s=self.media();r=s['rounds'][0];del r['video'];c.save(s)
        with patch.object(c,'api',return_value={'status':'failed','error':{'code':'InternalError'}}):
            for retry in (1,2):
                self.assertEqual(c.advance(s),'retrying_video')
                s=c.load();r=s['rounds'][0]
                self.assertEqual(r['video_retries'],retry)
                self.assertEqual(r['design']['url'],'https://example.com/design')
                r.update(task='replacement',submitted_at=c.time.time())
            with self.assertRaises(RuntimeError): c.advance(s)
            self.assertEqual(len(c.load()['rounds'][0]['failed_tasks']),2)

    def test_policy_failure_not_retried(self):
        self.init();s=self.media();del s['rounds'][0]['video']
        with patch.object(c,'api',return_value={'status':'failed','error':{'code':'OutputAudioSensitiveContentDetected.PolicyViolation'}}):
            with self.assertRaises(RuntimeError): c.advance(s)
        self.assertNotIn('video_retries',c.load()['rounds'][0])

    def test_uncertain_video_submit_never_repeated(self):
        self.init();s=self.media();r=s['rounds'][0];del r['video'];del r['task']
        with patch.object(c,'api',side_effect=RuntimeError('transport failure')) as api:
            with self.assertRaises(RuntimeError): c.advance(s)
            with self.assertRaises(RuntimeError): c.advance(c.load())
            self.assertEqual(api.call_count,1)

    def test_get_retries_but_post_does_not(self):
        for body,count in [(None,3),({'prompt':'test'},1)]:
            with patch.object(c.urllib.request,'urlopen',side_effect=c.urllib.error.HTTPError('https://example.com',503,'unavailable',{},None)) as request, patch.object(c.time,'sleep'):
                with self.assertRaises(RuntimeError): c.api('/test',body)
                self.assertEqual(request.call_count,count)


if __name__=='__main__':
    unittest.main()
