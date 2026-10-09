from pathlib import Path
import tempfile
import unittest
from vision_rsi.ledger import Ledger
from vision_rsi.observatory import dashboard


class LedgerTests(unittest.TestCase):
    def test_durability_idempotency_and_conflict(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(folder)
            payload={'summary':'research goal'}
            seq=ledger.append('goal','objective',payload)
            self.assertEqual(Ledger(folder).append('goal','objective',payload),seq)
            with self.assertRaises(ValueError):
                ledger.append('goal','objective',{'summary':'different'})
            self.assertEqual(len(ledger.events()),1)

    def test_references_pause_and_self_promotion(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(folder)
            ledger.append('goal','objective',{'summary':'goal'})
            with self.assertRaises(ValueError):
                ledger.append('h','hypothesis',{'summary':'hypothesis','refs':['missing']})
            ledger.append('pause','paused',{'summary':'pause'})
            with self.assertRaises(ValueError):
                ledger.append('a','action',{'summary':'new work'})
            ledger.append('resume','resumed',{'summary':'resume'})
            ledger.append('a','action',{'summary':'new work'})
            ledger.append('r','result',{'summary':'failed','action':'a','status':'failed'})
            with self.assertRaises(ValueError):
                ledger.append('r2','result',{'summary':'duplicate','action':'a','status':'completed'})
            with self.assertRaises(ValueError):
                ledger.append('self','self_change',{'summary':'adopt me','status':'adopted'})
            ledger.append('self','self_change',{'summary':'proposal','status':'proposed'})

    def test_dashboard_does_not_execute_recorded_html(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(folder)
            ledger.append('goal','objective',{'summary':'</script><script>alert(1)</script>'})
            page=Path(dashboard(ledger)).read_text(encoding='utf-8')
            self.assertNotIn('</script><script>alert',page)
            self.assertIn('textContent',page)
