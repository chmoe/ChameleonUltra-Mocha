import importlib.util
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import rf_diag

class RFDiagnosticsTests(unittest.TestCase):
    def test_ring_wrap_bounds_and_short_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p/'app_timer.h').write_text('#include <stdint.h>\nstatic uint32_t app_timer_cnt_get(void) {return 123;}\n')
            (p/'app_util_platform.h').write_text('#define CRITICAL_REGION_ENTER()\n#define CRITICAL_REGION_EXIT()\n')
            (p/'test.c').write_text('''#include <assert.h>
#include "rf_diag.c"
int main(void) {
 uint8_t out[272], byte=0x26; uint32_t h[4];
 assert(rf_diag_read(0,0,out)==0); assert(rf_diag_read(0,9,out)==0);
 assert(rf_diag_read(0,8,out)==16); memcpy(h,out,16); assert(h[2]==0 && h[3]==0);
 for(int i=0;i<300;i++) rf_diag_record(3,4,0,3,&byte,7);
 assert(rf_diag_read(0,8,out)==272); memcpy(h,out,16);
 assert(h[0]==1 && h[1]==44 && h[2]==300 && h[3]==8);
 event_t e; memcpy(&e,out+16,32);
 assert(e.sequence==44 && e.bits==7 && e.captured==1 && e.data[0]==0x26 && e.data[1]==0);
 assert(rf_diag_read(299,8,out)==48); memcpy(&e,out+16,32); assert(e.sequence==299);
 assert(rf_diag_read(301,8,out)==16);
 uint8_t large[17]={0};rf_diag_record(4,4,0,3,large,136);
 rf_diag_read(300,1,out);memcpy(&e,out+16,32);assert(e.captured==16 && e.bits==136);
 return 0;
}''')
            subprocess.run(['cc','-std=c11','-Wall','-Werror','-I',str(p),
                            '-I',str(ROOT/'firmware/application/src'),str(p/'test.c'),
                            '-o',str(p/'test')], check=True, capture_output=True)
            subprocess.run([str(p/'test')], check=True)

    def test_retained_rx_rearms_after_field_loss_but_not_during_dma(self):
        source=(ROOT/'firmware/application/src/rfid/nfctag/hf/nfc_14a.c').read_text()
        start=source.index('static void nfc_tag_14a_rearm_retained_receiver(void)')
        end=source.index('\n}',start)+2
        helper=source[start:end]
        program=r'''#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <assert.h>
#define NFCT_NFCTAGSTATE_NFCTAGSTATE_Idle 3
#define RF_DIAG_REARM 11
static struct {uint32_t NFCTAGSTATE;} hw;
#define NRF_NFCT (&hw)
static bool m_polling_rx_paused,m_is_responded;
static int armed,logged;
#define NRFX_NFCT_RX_BYTES do {armed++;} while(0);
static void rf_event(int kind,void *data,int bits) {assert(kind==11);logged++;}
'''+helper+r'''
int main(void) {
 for(int state=0;state<=6;state++) {
  hw.NFCTAGSTATE=state;armed=logged=0;m_is_responded=true;
  nfc_tag_14a_rearm_retained_receiver();
  assert(armed==(state==3) && logged==armed);
  assert(m_is_responded==(state!=3));
 }
 hw.NFCTAGSTATE=3;m_polling_rx_paused=true;armed=logged=0;
 nfc_tag_14a_rearm_retained_receiver();assert(armed==0 && logged==0);
 // First READY had armed RX; FIELD_LOST masked it while hardware stayed Idle.
 m_polling_rx_paused=false;armed=logged=0;hw.NFCTAGSTATE=3;
 nfc_tag_14a_rearm_retained_receiver();assert(armed==1);
 // A later active receive must not have its DMA buffer rearmed.
 hw.NFCTAGSTATE=4;nfc_tag_14a_rearm_retained_receiver();assert(armed==1);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'test.c').write_text(program)
            subprocess.run(['cc','-std=c11','-Wall','-Werror',str(p/'test.c'),'-o',str(p/'test')],check=True,capture_output=True)
            subprocess.run([str(p/'test')],check=True)

    def test_decode_commands_and_truncation(self):
        event=struct.pack('<IIBBBBHH16s',0,123,3,4,2,4,32,4,b'\x3a\x04\x44\0')
        page=struct.pack('<4I',1,0,1,1)+event
        first,end,events=rf_diag.decode(page)
        self.assertEqual(events[0]['fast_read_pages'],[4,68])
        self.assertEqual(events[0]['slot'],5)
        for bad in [page[:-1],b'',struct.pack('<4I',2,0,0,0)]:
            with self.assertRaises(ValueError):rf_diag.decode(bad)

    def test_export_stops_at_initial_snapshot(self):
        class Fake:
            def q(self,cmd,data=b''):
                if cmd==1017:return b'test'
                if cmd in [1110,1109]:return bytes(36 if cmd==1110 else 48)
                cursor,limit=struct.unpack('<IB',data)
                end=10 if cursor==0 else 12
                events=[struct.pack('<IIBBBBHH16s',i,0,1,0,0,0,0,0,b'')
                        for i in range(cursor,min(cursor+limit,end))]
                return struct.pack('<4I',1,0,end,len(events))+b''.join(events)
        self.assertEqual([e['sequence'] for e in rf_diag.capture(Fake())['events']],list(range(10)))
