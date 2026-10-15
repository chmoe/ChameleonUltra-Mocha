"""Run the actual Classic state handler; stub RF and transform Crypto1 bytes."""
import re, subprocess, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'firmware/application/src/rfid/nfctag/hf'
MOCK=r'''
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>
#define NFC_MF1_FAST_SIM
#define NRF_LOG_INFO(...)
#define NFC_TAG_14A_CRC_LENGTH 2
#define NFC_TAG_14A_UID_SINGLE_SIZE 4
#define NFC_TAG_STATE_14A_ACTIVE 1
#define NFC_TAG_STATE_14A_PROPRIETARY 2
#define NFC_TAG_STATE_14A_HALTED 3
#define U32HTONL(x) (x)
#define ACK_VALUE 0x0a
#define NAK_INVALID_OPERATION_TBIV 4
#define NAK_CRC_PARITY_ERROR_TBIV 5
#define NAK_OTHER_ERROR 6
typedef struct { uint8_t size,uid[10],sak[1],atqa[2]; } nfc_tag_14a_coll_res_entity_t;
'''
STUBS=r'''
static nfc_tag_mf1_information_t info, *m_tag_information=&info;
static nfc_tag_mf1_trailer_info_t *m_tag_trailer_info;
static nfc_tag_mf1_tx_buffer_t m_tag_tx_buffer;
static nfc_tag_mf1_std_state_machine_t m_mf1_state;
static nfc_tag_mf1_gen1a_state_machine_t m_gen1a_state;
static uint8_t KeyInUse, CurrentAddress, AuthenticatedSector, ReaderResponse[4], CardResponse[4], m_data_block_buffer[16];
static uint8_t uid[4], *UID_BY_CASCADE_LEVEL=uid;
static unsigned condition;static bool crc_ok=true;
static uint8_t GetAccessCondition(uint8_t b) {(void)b;return condition;}
static uint8_t blockToSector(uint8_t b) {return b<128?b/4:32+(b-128)/16;}
static uint8_t sectorToBlock(uint8_t s) {return s<32?s*4:128+(s-32)*16;}
static bool isSectorTrailer(uint8_t b) {return b<128?(b%4==3):(b%16==15);}
static bool check_block_max_overflow(uint8_t b) {(void)b;return false;}
static void nfc_tag_mf1_reset_handler(void) {m_mf1_state=MF1_STATE_UNAUTHENTICATED;}
static bool nfc_tag_14a_checks_crc(uint8_t *p,unsigned n) {(void)p;(void)n;return crc_ok;}
static void nfc_tag_14a_set_state(unsigned s) {(void)s;}
static void nfc_tag_14a_tx_nbit(uint8_t v,unsigned n) {(void)v;(void)n;}
static void nfc_tag_14a_tx_bytes(uint8_t *p,unsigned n,bool c) {(void)p;(void)n;(void)c;}
static void nfc_tag_14a_tx_bits(uint8_t *p,unsigned n) {(void)p;(void)n;}
static void nfc_tag_14a_append_crc(uint8_t *p,unsigned n) {p[n]=p[n+1]=0;}
static unsigned nfc_tag_14a_wrap_frame(uint8_t *p,unsigned n,uint8_t *parity,uint8_t *out) {(void)parity;memcpy(out,p,n/8);return n;}
static void Crypto1ByteArray(uint8_t *p,unsigned n) {for(unsigned i=0;i<n;i++)p[i]^=0xff;}
static void Crypto1ByteArrayWithParity(uint8_t *p,uint8_t *parity,unsigned n) {(void)parity;Crypto1ByteArray(p,n);}
static uint8_t Crypto1Nibble(void) {return 0;}
static void Crypto1Setup(uint8_t *a,uint8_t *b,uint8_t *c) {(void)a;(void)b;(void)c;}
static void Crypto1PRNG(uint8_t *p,unsigned n) {(void)p;(void)n;}
static void Crypto1Auth(uint8_t *p) {(void)p;}
static void Crypto1SetupNested(uint8_t *a,uint8_t *b,uint8_t *c,uint8_t *d,bool f) {(void)a;(void)b;(void)c;(void)d;(void)f;}
static void nfc_tag_mf1_random_nonce(uint8_t *p,bool nested) {(void)nested;memset(p,0x42,4);}
static void append_mf1_auth_log_step1(bool a,bool b,uint8_t c,uint8_t *d) {(void)a;(void)b;(void)c;(void)d;}
static void append_mf1_auth_log_step2(uint8_t *a,uint8_t *b) {(void)a;(void)b;}
static void append_mf1_auth_log_step3(bool b) {(void)b;}
static bool CheckValueIntegrity(uint8_t *p) {(void)p;return false;}
static void ValueFromBlock(uint32_t *v,uint8_t *p) {memcpy(v,p,4);}
static void ValueToBlock(uint8_t *p,uint32_t v) {memcpy(p,&v,4);}
struct event {uint8_t kind,cmd,block,key,result,response,flags,len,data[16];};
static struct event log_events[64];static unsigned log_count;
static void access_trace_event(uint8_t kind,uint8_t cmd,uint8_t block,uint8_t key,uint8_t result,uint8_t resp,uint8_t flags,const uint8_t *p,uint8_t len) {
 struct event *e=&log_events[log_count++];*e=(struct event){kind,cmd,block,key,result,resp,flags,len,{0}};if(p)memcpy(e->data,p,len);
}
'''
PROGRAM=r'''
static void setup(void) {
 memset(&info,0,sizeof(info));log_count=0;condition=0;crc_ok=true;
 m_mf1_state=MF1_STATE_AUTHENTICATED;AuthenticatedSector=1;KeyInUse=0;
 m_tag_trailer_info=(void*)info.memory[7];memset(info.memory[7],0x5a,16);
}
static void command(uint8_t cmd,uint8_t block) {uint8_t p[4]={cmd,block,0,0};Crypto1ByteArray(p,4);nfc_tag_mf1_state_handler(p,32);}
int main(void) {
 setup();memset(info.memory[4],0x12,16);command(CMD_READ,4);
 assert(log_count==2 && log_events[0].kind==1 && log_events[1].kind==2);
 assert(log_events[1].data[0]==0x12 && m_tag_tx_buffer.tx_raw_buffer[0]==0xed);
 setup();command(CMD_READ,7);assert(log_events[1].len==16);
 for(unsigned i=0;i<6;i++)assert(log_events[1].data[i]==0);
 assert(log_events[1].data[10]==0x5a); /* Actual masked trailer, not dump. */
 setup();condition=7;command(CMD_READ,4);assert(log_events[1].result==2 && log_events[1].len==0);
 setup();command(CMD_READ,8);assert(log_events[1].result==2);
 setup();command(CMD_WRITE,7);uint8_t p[18];memset(p,0x33,18);Crypto1ByteArray(p,18);nfc_tag_mf1_state_handler(p,144);
 assert(log_events[2].kind==4 && log_events[2].data[0]==0x33);
 /* Trailer data restored after capture: original access bytes are retained. */
 assert(info.memory[7][6]==0x5a && log_events[3].response==ACK_VALUE);
 setup();info.config.mode_block_write=NFC_TAG_MF1_WRITE_DECEIVE;command(CMD_WRITE,4);memset(p,0x33,18);Crypto1ByteArray(p,18);nfc_tag_mf1_state_handler(p,144);
 assert(info.memory[4][0]==0 && (log_events[2].flags&4) && log_events[3].result==1);
 setup();crc_ok=false;command(CMD_READ,4);assert(log_events[0].result==3 && log_events[0].block==255);
 setup();m_mf1_state=MF1_STATE_UNAUTHENTICATED;uint8_t a[4]={CMD_AUTH_A,5,0,0};nfc_tag_mf1_state_handler(a,32);
 assert(log_events[0].cmd==CMD_AUTH_A && log_events[0].block==5 && log_events[1].len==4);
 uint8_t reply[8]={0};memcpy(reply+4,ReaderResponse,4);for(unsigned i=4;i<8;i++)reply[i]^=255;
 nfc_tag_mf1_state_handler(reply,64);assert(log_events[2].kind==3 && log_events[2].result==1);
 return 0;
}
'''
class ClassicTests(unittest.TestCase):
 def test_plaintext_and_semantics(self):
  source=(BASE/'nfc_mf1.c').read_text();header=(BASE/'nfc_mf1.h').read_text()
  definitions=source[source.index('#define MEM_KEY_A_OFFSET'):source.index('// Save the current MF1 standard status')]
  types=header[header.index('#define NFC_TAG_MF1_DATA_SIZE'):header.index('// MF1 label verification history')]
  handler=source[source.index('static uint8_t trace_cmd'):source.index('/**\n * @brief Provide the necessary anti -conflict resources')]
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);(p/'test.c').write_text(MOCK+types+definitions+STUBS+handler+PROGRAM)
   build=subprocess.run(['cc','-std=c11','-Wall','-Werror','-Wno-unused-function','-I',tmp,str(p/'test.c'),'-o',str(p/'test')],capture_output=True,text=True)
   self.assertEqual(build.returncode,0,build.stderr)
   run=subprocess.run([str(p/'test')],capture_output=True,text=True);self.assertEqual(run.returncode,0,run.stderr)
if __name__=='__main__': unittest.main()
