"""Fixed inputs/acceptance checks. Fixtures are explicitly not live model evidence."""

import json
from pathlib import Path

MANIFEST = Path(__file__).with_name("manifest.json")
MODULE_TEST = """import unittest
from sample import add
class Acceptance(unittest.TestCase):
 def test_add(self):
  for a,b,want in [(2,3,5),(-2,-3,-5),(0,0,0),(0.1,0.2,0.3)]:
   self.assertAlmostEqual(add(a,b),want)
"""
MULTI_TEST = (
    MODULE_TEST
    + """ def test_artifacts(self):
  from pathlib import Path
  self.assertTrue(Path('test_sample.py').is_file())
  self.assertIn('unittest',Path('README.md').read_text().lower())
"""
)
EXPENSE_TASK = """Create a complete standard-library Python expense_tracker.py CLI.
Commands: --file PATH add CATEGORY DESCRIPTION AMOUNT; --file PATH list;
--file PATH summary. Persist JSON expenses, exact decimal currency totals and
category totals. Reject zero, negative, nonnumeric, nonfinite and amounts with
more than two decimal places. Never overwrite malformed stored JSON. Include
separate unittest tests and README explaining the commands and unittest.
Run the tests, repair failures using their output, then request review.
Independent test_acceptance.py is read-only; inspect it to see required behavior.
"""
EXPENSE_TEST = """import json, subprocess, sys, tempfile, unittest
from pathlib import Path
class Acceptance(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.file=Path(self.temp.name)/'expenses.json'
 def cli(self,*args):
  return subprocess.run([sys.executable,'expense_tracker.py','--file',str(self.file),*args],capture_output=True,text=True,timeout=8)
 def test_persistence(self):
  self.assertEqual(self.cli('add','food','Lunch','12.50').returncode,0)
  self.assertTrue(self.file.is_file());self.assertIsInstance(json.loads(self.file.read_text()),list)
  self.assertIn('Lunch',self.cli('list').stdout)
 def test_exact_totals(self):
  for cat,desc,n in [('food','one','0.10'),('food','two','0.20'),('bus','fare','2.00')]:
   self.assertEqual(self.cli('add',cat,desc,n).returncode,0)
  r=self.cli('summary');self.assertEqual(r.returncode,0)
  self.assertIn('2.30',r.stdout);self.assertIn('0.30',r.stdout);self.assertIn('food',r.stdout);self.assertIn('bus',r.stdout)
 def test_invalid_amounts(self):
  for n in ['0','-1','abc','NaN','Infinity','-Infinity','1.234']:
   with self.subTest(amount=n):
    before=self.file.read_bytes() if self.file.exists() else None
    self.assertNotEqual(self.cli('add','food','bad',n).returncode,0)
    self.assertEqual(self.file.read_bytes() if self.file.exists() else None,before)
 def test_malformed_preserved(self):
  for data in [b'{broken',b'{}']:
   with self.subTest(data=data):
    self.file.write_bytes(data)
    self.assertNotEqual(self.cli('add','food','new','1.00').returncode,0)
    self.assertEqual(self.file.read_bytes(),data)
 def test_empty(self):
  self.assertEqual(self.cli('list').returncode,0)
  self.assertEqual(self.cli('summary').returncode,0)
 def test_documentation_and_agent_tests(self):
  self.assertTrue(Path('test_expense_tracker.py').is_file())
  self.assertIn('unittest',Path('README.md').read_text().lower())
"""
# Deliberately defective fixture, matching the observed dangerous load-then-overwrite
# behavior. Success for this harness test means our independent checks detect it.
BROKEN_STORE = """import argparse,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--file');p.add_argument('command');p.add_argument('args',nargs='*');a=p.parse_args()
f=Path(a.file)
try: data=json.loads(f.read_text())
except (ValueError,FileNotFoundError): data=[]
if a.command=='add':
 data.append(dict(zip(['category','description','amount'],a.args)));f.write_text(json.dumps(data))
else: print(data)
"""


def manifest():
    return json.loads(MANIFEST.read_text())


def setup_project(case_id, workspace):
    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    (root / "unrelated.txt").write_text("preserve me\n")
    if case_id in ("expense-regression", "data-integrity"):
        (root / "test_acceptance.py").write_text(EXPENSE_TEST)
        return EXPENSE_TASK
    (root / "test_acceptance.py").write_text(MULTI_TEST if case_id == "multi-file" else MODULE_TEST)
    if case_id == "existing-repair":
        (root / "sample.py").write_text("def add(a,b): return a-b\n")
    return (
        "Create sample.py with add(a,b), preserving unrelated.txt. "
        + (
            "Create test_sample.py and README.md explaining unittest. "
            if case_id == "multi-file"
            else ""
        )
        + "Inspect the independent read-only test_acceptance.py, run unittest, repair failures, and request review."
    )
