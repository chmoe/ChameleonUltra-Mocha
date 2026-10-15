"""Exercise actual trace C implementation with FDS/RF fault injection."""
import subprocess
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

MOCK = r'''
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>
#define NRF_SUCCESS 0
#define PROJECT_CHAMELEON_ULTRA
#define APP_TIMER_TICKS(n) ((uint32_t)((uint64_t)(n)*32768u/1000))
#define __WFE() ((void)0)
#define CRITICAL_REGION_ENTER()
#define CRITICAL_REGION_EXIT()
static uint32_t tick;
static uint32_t app_timer_cnt_get(void) { return tick; }
static uint32_t app_timer_cnt_diff_compute(uint32_t a,uint32_t b) { return (a-b)&0xffffff; }
static void bsp_wdt_feed(void) {}
#define TAG_TYPE_MIFARE_Mini 1
#define TAG_TYPE_MIFARE_1024 2
#define TAG_TYPE_MIFARE_2048 3
#define TAG_TYPE_MIFARE_4096 4
static unsigned tag_type=2;
typedef struct { uint16_t tag_hf; } tag_slot_specific_type_t;
static uint8_t tag_emulation_get_slot(void) { return 5; }
static void tag_emulation_get_specific_types_by_slot(uint8_t s,tag_slot_specific_type_t *p) { (void)s;p->tag_hf=tag_type; }
typedef struct { unsigned key; } fds_record_desc_t;
typedef struct { unsigned index; } fds_find_token_t;
typedef struct { unsigned file_id,key; struct {const void *p_data;unsigned length_words;} data; } fds_record_t;
typedef struct { unsigned id,result; struct {unsigned file_id,record_key;} write,del; } fds_evt_t;
#define FDS_EVT_WRITE 1
#define FDS_EVT_DEL_RECORD 2
#define FDS_EVT_GC 3
#define FDS_EVT_UPDATE 4
static void (*handler)(const fds_evt_t*);
static uint8_t flash[8][1024], exists[8], control_flash[16];
static bool control_exists;
static bool fail_write,fail_gc,fail_delete,fail_completion,physical_rf;
static unsigned writes,gcs;
static unsigned fds_register(void (*h)(const fds_evt_t*)) {handler=h;return 0;}
static bool fds_is_exists(unsigned id,unsigned k) {if(id==0x1301)return control_exists;return exists[k-1];}
static bool fds_read_sync(unsigned id,unsigned k,uint16_t *len,uint8_t *out) {
    if(id==0x1301){if(!control_exists)return false;memcpy(out,control_flash,16);*len=16;return true;}
    if(!exists[k-1])return false;memcpy(out,flash[k-1],1024);*len=1024;return true;
}
static unsigned fds_record_write(fds_record_desc_t *d,const fds_record_t *r) {
    assert(!physical_rf);
    if(r->file_id==0x1301){if(fail_write)return 1;memcpy(control_flash,r->data.p_data,16);control_exists=true;
      fds_evt_t e={.id=FDS_EVT_WRITE,.write={.file_id=0x1301,.record_key=1}};handler(&e);return 0;}
    assert(r->key>=1&&r->key<=8); assert(!exists[r->key-1]);
    (void)d; writes++; if(fail_write)return 1;
    if(fail_completion){fds_evt_t e={.id=FDS_EVT_WRITE,.result=1,.write={.file_id=0x1300,.record_key=r->key}};handler(&e);return 0;}
    memcpy(flash[r->key-1],r->data.p_data,1024);exists[r->key-1]=1;
    fds_evt_t e={.id=FDS_EVT_WRITE,.write={.file_id=0x1300,.record_key=r->key}};handler(&e);return 0;
}
static unsigned fds_record_update(fds_record_desc_t *d,const fds_record_t *r) {
 (void)d;assert(!physical_rf);if(fail_write)return 1;memcpy(control_flash,r->data.p_data,16);
 fds_evt_t e={.id=FDS_EVT_UPDATE,.write={.file_id=0x1301,.record_key=1}};handler(&e);return 0;
}
static unsigned fds_record_find(unsigned id,unsigned k,fds_record_desc_t *d,fds_find_token_t *t) {
    if(id==0x1301){if(!control_exists)return 1;d->key=1;return 0;}
    if(!exists[k-1]||t->index)return 1;d->key=k;t->index=1;return 0;
}
static unsigned fds_record_delete(fds_record_desc_t *d) {
    if(fail_delete)return 1;exists[d->key-1]=0;
    fds_evt_t e={.id=FDS_EVT_DEL_RECORD,.del={.file_id=0x1300,.record_key=d->key}};handler(&e);return 0;
}
static unsigned fds_gc(void) {gcs++;if(fail_gc)return 1;fds_evt_t e={.id=FDS_EVT_GC};handler(&e);return 0;}
static void fds_util_trace_gc(bool b) {(void)b;}
'''
PROGRAM = r'''
#include "access_trace.c"
static uint8_t out[1024]; static uint16_t olen;
static unsigned q(unsigned c,const uint8_t *p,unsigned n) {return access_trace_command(c,p,n,out,&olen);}
static void boot(void) {
 count=occupied=flags=0;enabled=clear_failed=save_blocked=enable_requested=active=pending=saving=rf_present=false;
 field_seen=loss_checking=false;loss_since=0;generation=1;next_id=1;dropped=failures=n_events=0;feedback=-1;state_dirty=state_blocked=false;access_trace_init();
}
static void on(void) {uint8_t b=1;assert(q(1122,&b,1)==0x68);}
static void settle(void) {access_trace_process(false);tick+=APP_TIMER_TICKS(100);access_trace_process(false);}
static void session(unsigned events) {
 physical_rf=true;access_trace_field(true);
 for(unsigned i=0;i<events;i++){uint8_t d[16];memset(d,i,16);access_trace_event(2,0x30,i,0,1,255,0,d,16);}
 access_trace_process(true);physical_rf=false;access_trace_field(false);settle();
}
int main(void) {
 boot();session(2);assert(writes==0);on();session(2);assert(count==1 && writes==1);
 assert(q(1121,NULL,0)==0x68 && olen==32 && out[8]==1 && rd16(out+10)==1);
 uint32_t gen=rd32(out+4);uint8_t p[9]={0};wr32(p,gen);p[8]=31;
 assert(q(1124,p,9)==0x68 && out[6]==3 && olen==103);
 assert(out[7+4]==2 && out[7+6]==0 && out[7+10]==16 && out[7+12]==0);
 assert(out[7+64+4]==5); /* end event */
 p[8]=32;assert(q(1124,p,9)==0x60);p[8]=31;
 boot();assert(enabled && count==1);assert(q(1124,p,9)==0x73);on();
 session(40);assert(count==2 && (flags&OVERFLOW));assert(load(2,(uint8_t*)scratch));
 assert(rd16((uint8_t*)scratch+12)==31 && ((uint8_t*)scratch)[11]==1);
 fail_write=true;session(1);assert(pending && (flags&FAILED));assert(access_trace_busy());
 uint8_t enable=0;assert(q(1122,&enable,1)==0x68);
 unsigned prior=writes;tick+=APP_TIMER_TICKS(2001);physical_rf=true;access_trace_process(true);assert(writes==prior);
 physical_rf=false;fail_write=false;settle();assert(count==3 && !pending);
 on();for(unsigned i=0;i<4;i++)session(0);assert(count==7 && (flags&FULL));
 prior=writes;session(5);assert(writes==prior && count==7);
 flash[2][200]^=1;boot();assert(count==6 && (flags&CORRUPT) && (flags&FULL));
 assert(q(1125,(const uint8_t*)"NO",2)==0x60);
 fail_gc=true;assert(q(1125,(const uint8_t*)"CLEAR",5)==0x70 && clear_failed);
 fail_gc=false;assert(q(1125,(const uint8_t*)"CLEAR",5)==0x68);
 assert(count==0 && flags==0 && !pending && gcs>=2);on();
 physical_rf=true;access_trace_field(true);assert(q(1125,(const uint8_t*)"CLEAR",5)==0x75);
 /* Power loss: RAM session lost, committed flash untouched. */
 physical_rf=false;boot();assert(count==0 && !access_trace_busy());
 on();physical_rf=true;access_trace_field(true);
 tick+=APP_TIMER_TICKS(400000);access_trace_process(true);
 tick+=APP_TIMER_TICKS(400000);access_trace_process(true);
 physical_rf=false;access_trace_field(false);settle();
 assert(rd32(flash[0]+4)>=800099 && rd32(flash[0]+4)<=800101);
 assert(q(1125,(const uint8_t*)"CLEAR",5)==0x68);
 fail_completion=true;on();session(1);assert(pending && save_blocked);
 prior=writes;tick+=APP_TIMER_TICKS(3000);access_trace_process(false);assert(writes==prior);
 fail_completion=false;assert(q(1125,(const uint8_t*)"CLEAR",5)==0x68);
 control_exists=false;boot();bool led_state=false;unsigned old_gc=gcs;
 assert(q(1120,NULL,0)==0x68 && rd16(out+2)==6 && (rd32(out+4)&16));
 physical_rf=true;access_trace_field(true);access_trace_button_toggle();
 assert(q(1121,NULL,0)==0x68 && !out[8] && (out[9]&64));
 access_trace_process(true);assert(gcs==old_gc && !enabled);
 access_trace_button_toggle();assert(!enable_requested && !access_trace_take_feedback(&led_state));
 access_trace_button_toggle();physical_rf=false;settle();
 assert(enabled && !enable_requested && gcs>=old_gc+1);
 assert(access_trace_take_feedback(&led_state) && led_state);
 physical_rf=true;access_trace_field(true);
 access_trace_event(1,0x30,4,0,0,255,0,NULL,0);unsigned events=n_events;
 access_trace_button_toggle();assert(!enabled && active && !pending && state_dirty && rd32(control_flash+4)==1);
 assert(access_trace_take_feedback(&led_state) && !led_state);
 access_trace_event(2,0x30,4,0,1,255,0,NULL,0);assert(n_events==events);
 prior=writes;access_trace_process(true);assert(writes==prior);
 physical_rf=false;access_trace_field(false);assert(active && !pending);
 settle();assert(count==1 && !pending && (flash[0][11]&2));
 assert(rd16(flash[0]+12)==events+1 && !state_dirty && rd32(control_flash+4)==0);
 boot();assert(!enabled && !state_dirty);
 assert(q(1125,(const uint8_t*)"CLEAR",5)==0x68);
 fail_gc=true;access_trace_button_toggle();access_trace_process(false);
 assert(!enabled && !enable_requested && (flags&FAILED) && !access_trace_take_feedback(&led_state));fail_gc=false;
 tag_type=999;on();session(3);assert(count==0);
 boot();assert(enabled && !state_dirty && feedback==-1);
 uint8_t off=0;assert(q(1122,&off,1)==0x68);boot();assert(!enabled && !state_dirty);
 control_flash[12]^=1;boot();assert(!enabled && (flags&CORRUPT));
 return 0;
}
'''

class TraceTests(unittest.TestCase):
    def test_firmware_storage_and_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            for name in ['app_timer.h','fds_util.h','tag_emulation.h','bsp_wdt.h','app_util_platform.h']:
                (p/name).write_text('#include "mock.h"\n')
            (p/'mock.h').write_text(MOCK)
            for name in ['access_trace.c','access_trace.h','app_status.h']:
                (p/name).write_text((ROOT/'firmware/application/src'/name).read_text())
            (p/'test.c').write_text(PROGRAM)
            build=subprocess.run(['cc','-std=c11','-Wall','-Werror','-Wno-misleading-indentation','-I',tmp,str(p/'test.c'),'-o',str(p/'test')],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(p/'test')],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr)

if __name__=='__main__': unittest.main()
