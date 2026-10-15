import importlib.util,struct,unittest
from types import SimpleNamespace
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('mocha',ROOT/'tools/mocha.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Fake:
 def __init__(self):self.calls=[];self.stale=False
 def q(self,cmd,data=b''):
  self.calls.append((cmd,data))
  if cmd==1120:return struct.pack('<HHIHHHH',1,3,15,1024,32,7,31)
  if cmd==1121:return struct.pack('<HHIBBHHHIIII',1,3,42,0,0,1,7,31,16384,1036,0,0)
  if cmd==1123:return struct.pack('<IHBIIHBBHH',42,1,1,1,25,1001,5,0,1,0)
  if cmd==1124:
   event=struct.pack('<IBBBBBBBB16s4s',12,2,0x30,4,0,1,255,16,0,bytes(range(16)),b'\0'*4)
   return struct.pack('<IHB',43 if self.stale else 42,1,1)+event
  raise AssertionError(cmd)
class CliTests(unittest.TestCase):
 def test_export_is_read_only_and_preserves_bytes(self):
  d=Fake();result=m.trace_export(d)
  event=result['sessions'][0]['events'][0]
  self.assertEqual(event['data'],'000102030405060708090a0b0c0d0e0f')
  self.assertEqual(event['command'],0x30);self.assertEqual(result['sessions'][0]['slot'],5)
  self.assertTrue(all(c in [1120,1121,1123,1124] for c,p in d.calls))
 def test_rejects_changed_generation(self):
  d=Fake();d.stale=True
  with self.assertRaisesRegex(RuntimeError,'Inconsistent'):m.trace_export(d)
 def test_rejects_short_page(self):
  d=Fake();old=d.q;d.q=lambda c,p=b'':b'' if c==1123 else old(c,p)
  with self.assertRaisesRegex(RuntimeError,'Short'):m.trace_export(d)
 def test_clear_requires_explicit_confirmation(self):
  with self.assertRaises(SystemExit):m.parser().parse_args(['--port','mock','trace-clear'])
 def test_button_configuration_is_capability_gated(self):
  a=SimpleNamespace(action='button',button='b',press='long',function='access-trace')
  d=Fake()
  with self.assertRaisesRegex(RuntimeError,'does not support'):m.run(d,a)
  self.assertEqual(d.calls,[(1120,b'')])
  d=Fake();old=d.q
  def supported(c,p=b''):
   if c==1120:
    d.calls.append((c,p));return struct.pack('<HHIHHHH',1,4,63,1024,32,7,31)
   d.calls.append((c,p));return b''
  d.q=supported;m.run(d,a)
  self.assertEqual(d.calls,[(1120,b''),(1029,b'b\x08'),(1013,b'')])
if __name__=='__main__':unittest.main()
