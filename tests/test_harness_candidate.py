import unittest
from unittest.mock import patch
from vision_rsi.harness_candidate import validate_backend,smoke


def proposal(source=None):
    return {'hypothesis':'classification backend','expected_improvement':'measure accuracy','evaluation_plan':'fixed independent data',
            'edits':[{'path':'vision_rsi/harness_classifier.py','base_sha256':None,'content':source or
                '\n'.join('def '+name+'(request):\n    return {}\n' for name in ('load_data','train','predict','evaluate','smoke'))}]}


class HarnessCandidateTests(unittest.TestCase):
    def test_required_stages_and_import_time_effects(self):
        self.assertEqual(validate_backend(proposal()),'vision_rsi.harness_classifier')
        for text in ('def smoke(request):\n return {}',
                     'import torch\n'+proposal()['edits'][0]['content'],
                     'x=open("secret")\n'+proposal()['edits'][0]['content'],
                     proposal()['edits'][0]['content'].replace('def train(request):','def train(request=open("secret")):')):
            with self.assertRaises(ValueError):validate_backend(proposal(text))

    @patch('vision_rsi.harness_candidate.Candidates')
    def test_smoke_does_not_grant_gpu_or_quality_approval(self,candidates):
        candidates.return_value.check.return_value={'status':'executed_unverified','response':{'observation':{
            'results':[{'stages':['load_data','train','predict','evaluate'],'training_performed':False}]}}}
        candidate={'store':'store','candidate_id':'a'*64,'module':'vision_rsi.harness_classifier'}
        result=smoke(candidate,{},'.')
        self.assertEqual(result['status'],'backend_protocol_smoke_passed')
        self.assertFalse(result['gpu_dispatch_ready']);self.assertFalse(result['quality_verified'])
        first=candidates.return_value.check.call_args.args[-1]
        smoke(candidate,{},'.')
        self.assertEqual(first,candidates.return_value.check.call_args.args[-1])
        candidates.return_value.close.assert_called()


if __name__=='__main__':unittest.main()
