"""Compile actual firmware modules against mock hardware; never access USB/RF."""
import importlib.util
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'firmware/application/src'

COMMON = '''#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>
#define ALIGN_U32 __attribute__((aligned(4)))
#define PACKED __attribute__((packed))
#define STATIC_ASSERT(x) _Static_assert(x, #x)
#define APP_ERROR_CHECK_BOOL(x) assert(x)
#define NRF_LOG_MODULE_REGISTER()
#define NRF_LOG_ERROR(...)
#define NRF_LOG_WARNING(...)
#define NRF_LOG_INFO(...)
#define STATUS_SUCCESS 0x68
#define STATUS_FLASH_WRITE_FAIL 0x70
'''

class FirmwareTests(unittest.TestCase):
    def compile_run(self, files, program):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            for name, content in files.items(): (p/name).write_text(content)
            (p/'test.c').write_text(program)
            subprocess.run(['cc','-std=c11','-Wall','-Werror','-Wno-unused-function','-I',tmp,str(p/'test.c'),'-o',str(p/'test')], check=True, capture_output=True)
            subprocess.run([str(p/'test')], check=True, capture_output=True)

    def test_settings_migration_and_flash_failure(self):
        files = {name: COMMON for name in ['utils.h','crc_utils.h','app_status.h','nrf_log.h','nrf_log_ctrl.h','nrf_log_default_backends.h']}
        files['settings.h']=(SRC/'settings.h').read_text()
        files['settings.c']=(SRC/'settings.c').read_text()
        files['fds_ids.h']=(SRC/'utils/fds_ids.h').read_text()
        files['fds_util.h']=COMMON+'''bool fds_read_sync(uint16_t,uint16_t,uint16_t*,uint8_t*);
bool fds_write_sync(uint16_t,uint16_t,uint16_t,uint8_t*);
void calc_14a_crc_lut(uint8_t*,uint16_t,uint8_t*);
'''
        self.compile_run(files, '''#include "settings.c"
static uint8_t saved[32]; static uint16_t saved_len; static bool exists, fail; static int writes;
bool fds_read_sync(uint16_t id,uint16_t key,uint16_t *len,uint8_t *buf) {
 if (!exists || id!=FDS_SETTINGS_FILE_ID || saved_len>*len) return false;
 memcpy(buf,saved,saved_len); *len=saved_len; return true;
}
bool fds_write_sync(uint16_t id,uint16_t key,uint16_t len,uint8_t *buf) {
 if(fail) return false; memcpy(saved,buf,len); saved_len=len; exists=true; writes++; return true;
}
void calc_14a_crc_lut(uint8_t *p,uint16_t n,uint8_t *out) {
 uint16_t c=0x1234; for(int i=0;i<n;i++) c=(c*31)^p[i]; memcpy(out,&c,2);
}
static void fixture(uint16_t version,uint16_t legacy) {
 settings_init_config(); config.version=version; config.long_press_threshold=legacy;
 config.polling_enable=true; config.ab_reboot_enable=false; config.button_a_press=6;
 memcpy(saved,&config,16); saved_len=16; exists=true; m_config_crc=0; writes=0;
}
int main(void) {
 _Static_assert(sizeof(settings_data_t)==16,"settings layout");
 exists=false; settings_load_config(); assert(config.version==SETTINGS_CURRENT_VERSION);
 assert(!settings_get_polling_enable() && settings_get_polling_interval_ms()==500);
 fixture(7,750); settings_load_config(); assert(config.long_press_threshold==750);
 assert(!config.polling_enable && config.polling_interval_ms==500 && writes==1);
 fixture(8,1200); settings_load_config(); assert(config.long_press_threshold==1000);
 assert(config.polling_enable && config.polling_interval_ms==1200 && !config.ab_reboot_enable && writes==1);
 fixture(8,0); settings_load_config(); assert(config.polling_interval_ms==500);
 fixture(6,0); settings_load_config(); assert(config.long_press_threshold==1000 && !config.polling_enable);
 settings_set_long_press_threshold(1); assert(config.long_press_threshold==200);
 settings_set_polling_interval_ms(100); assert(config.polling_interval_ms==100);
 settings_set_polling_interval_ms(5000); assert(config.polling_interval_ms==5000);
 settings_set_polling_interval_ms(5001); assert(config.polling_interval_ms==5000);
 settings_save_config(); settings_load_config(); assert(config.polling_interval_ms==5000);
 settings_set_polling_enable(true); fail=true; assert(settings_save_config()==STATUS_FLASH_WRITE_FAIL);
 return 0;
}''')

    def test_polling_scheduler_and_transaction_lock(self):
        files={'polling.c':(SRC/'rfid/polling.c').read_text(),'polling.h':(SRC/'rfid/polling.h').read_text()}
        files['app_timer.h']=COMMON+'''typedef int ret_code_t;
#define APP_TIMER_DEF(x) static int x
#define APP_TIMER_MODE_REPEATED 1
#define APP_TIMER_TICKS(x) (x)
#define APP_ERROR_CHECK(x) assert((x)==0)
static uint32_t now;
static int app_timer_create(int *a,int b,void (*f)(void*)) { return 0; }
static int app_timer_start(int a,uint32_t ticks,void *p) { assert(ticks>=100&&ticks<=5000); return 0; }
static int app_timer_stop(int a) { return 0; }
static uint32_t app_timer_cnt_get(void) { return now; }
static uint32_t app_timer_cnt_diff_compute(uint32_t a,uint32_t b) { return (a-b)&0xffffff; }
'''
        files['settings.h']=COMMON+'''static bool enabled=true; static uint16_t interval=500;
static bool settings_get_polling_enable(void) { return enabled; }
static uint16_t settings_get_polling_interval_ms(void) { return interval; }
'''
        files['rfid_main.h']=COMMON+'''#define DEVICE_MODE_TAG 1
#define DEVICE_MODE_READER 2
static int mode=1, displays;
static int get_device_mode(void) { return mode; }
static void light_up_by_slot(void) { displays++; }
'''
        files['tag_emulation.h']=COMMON+'''#define TAG_MAX_SLOT_NUM 16
#define TAG_SENSE_HF 2
#define TAG_SENSE_LF 1
static uint8_t slot; static bool hf[16], lf[16], skip[16]; static int switches;
static uint8_t tag_emulation_get_slot(void) { return slot; }
static uint8_t tag_emulation_slot_find_next(uint8_t n) { for(int i=0;i<16;i++) { n=(n+1)%16; if(hf[n]||lf[n]) return n; } return n; }
static bool tag_emulation_slot_polling_skip(uint8_t n) { return skip[n]; }
static bool is_slot_enabled(uint8_t n,int sense) { return sense==2?hf[n]:lf[n]; }
static void tag_emulation_change_slot(uint8_t n,bool b) { slot=n; switches++; }
'''
        files['lf_tag_em.h']=COMMON+'''static bool lf_field, lf_boundary, pause;
static bool lf_reader_field_present(void) { return lf_field; }
static bool lf_polling_pause_at_boundary(void) { pause=true; return lf_boundary; }
static void lf_polling_resume(void) { pause=false; }
'''
        files['nfc_14a.h']=COMMON+'''static bool hf_field, quiesce_ok=true;
static bool nfc_tag_14a_field_present(void) { return hf_field; }
static bool nfc_tag_14a_polling_quiesce(void) { return quiesce_ok; }
'''
        self.compile_run(files, '''#include "polling.c"
static void tick(void) { now+=500; polling_timer_handler(0); polling_process(); }
int main(void) {
 polling_init(); polling_start(); tick(); assert(switches==0);
 hf[0]=hf[8]=hf[15]=true; hf_field=true; polling_note_hf_field(true);
 polling_process(); tick(); assert(slot==8); skip[15]=true; tick(); assert(slot==0);
 polling_lock_hf_transaction(); tick(); assert(slot==0);
 hf_field=false; polling_note_hf_field(false); polling_process(); assert(slot==0);
 hf_field=true; polling_process(); quiesce_ok=false; tick(); assert(slot==0);
 quiesce_ok=true; polling_process(); assert(slot==8);
 polling_forget_session(); slot=15; hf_field=false; polling_process(); assert(slot==15);
 slot=0; hf_field=true; polling_note_hf_field(true); polling_note_reader_activity();
 polling_process(); polling_timer_handler(0); polling_process(); assert(slot==0); now+=51; polling_process(); assert(slot==8);
 mode=DEVICE_MODE_READER; tick(); assert(slot==8); mode=DEVICE_MODE_TAG;
 hf_field=false; lf_field=true; lf[0]=lf[8]=true; slot=0; polling_process();
 lf_boundary=false; tick(); assert(slot==0 && pause);
 lf_boundary=true; polling_process(); assert(slot==8);
 lf_field=false; polling_process(); assert(slot==0);
 enabled=false; polling_start(); assert(!polling_is_running() && !pause);
 now=0xfffff0; enabled=true; polling_start(); hf_field=true; polling_note_hf_field(true); polling_note_reader_activity();
 now=0x25; assert(polling_hf_can_switch()); return 0;
}''')

    def test_slot_migration_preserves_types_and_skip(self):
        h=(SRC/'rfid/nfctag/tag_emulation.h').read_text()
        h=h[h.index('#define TAG_SLOT_CONFIG_CURRENT_VERSION'):h.index('// The most basic emulation')]
        c=(SRC/'rfid/nfctag/tag_emulation.c').read_text()
        start=c.index('static void tag_emulation_migrate_slot_config(void)')
        end=c.index('\n/**',start)
        self.compile_run({'common.h':COMMON}, '#include "common.h"\n#define TAG_MAX_SLOT_NUM 16\ntypedef uint16_t tag_specific_type_t;\n'+h+'''
static tag_slot_config_t slotConfig;
static void tag_emulation_migrate_slot_config_v0_to_v8(void) { assert(false); }
static int saves;
static void tag_emulation_save_config(void) { saves++; }
'''+c[start:end]+'''
int main(void) {
 memset(&slotConfig,0xff,sizeof(slotConfig)); slotConfig.version=8; slotConfig.active_slot=7;
 slotConfig.slots[0].tag_hf=1001; slotConfig.slots[7].tag_lf=2001;
 tag_emulation_migrate_slot_config(); assert(slotConfig.version==10 && slotConfig.active_slot==7);
 assert(slotConfig.slots[0].tag_hf==1001 && slotConfig.slots[7].tag_lf==2001);
 assert(!slotConfig.slots[0].polling_skip && !slotConfig.slots[8].enabled_hf && !slotConfig.slots[15].tag_lf);
 slotConfig.version=9; slotConfig.active_slot=15; slotConfig.slots[15].tag_hf=1100;
 slotConfig.slots[15].polling_skip=true; tag_emulation_migrate_slot_config();
 assert(slotConfig.version==10 && slotConfig.active_slot==15 && slotConfig.slots[15].tag_hf==1100 && slotConfig.slots[15].polling_skip);
 assert(saves==2); return 0;
}''')

    def test_usb_animation_reset_colors_and_timing(self):
        def function(text, name):
            start=text.index('void '+name+'('); first=text.index('{',start); depth=1; end=first+1
            while depth:
                depth+=(text[end]=='{')-(text[end]=='}'); end+=1
            return text[start:end]
        c=(SRC/'rgb_marquee.c').read_text()
        functions='\n'.join(function(c,n) for n in ['rgb_pwm_uninit','rgb_pwm_init','rgb_marquee_stop','rgb_marquee_reset','rgb_marquee_usb_idle','rgb_marquee_usb_open_sweep','rgb_marquee_usb_open_symmetric'])
        self.compile_run({'common.h':COMMON}, '#include "common.h"\n'+r"""
#define LIGHT_LEVEL_MAX 99
#define RGB_LIST_NUM 8
#define NRF_DRV_PWM_FLAG_LOOP 1
#define NRF_DRV_PWM_PIN_NOT_USED 0xffffffff
typedef void (*nrfx_pwm_handler_t)(int);
#define APP_ERROR_CHECK(x) assert((x)==0)
static bool m_pwm_initialized;
static int pwm0_ins, seq, timer_value, color_value, starts;
static int *timer=&timer_value;
static bool g_usb_led_marquee_enable=true;
static uint8_t rgb_marquee_usb_idle_step, rgb_marquee_usb_open_step, rgb_marquee_usb_idle_color;
static unsigned int cleared;
static void nrf_gpio_pin_clear(uint32_t p) { cleared |= 1u<<p; }
static int rand(void) { return 1; }
static uint16_t get_pwmduty(uint8_t level) { return 1000-level*10; }
static struct {uint16_t channel_0,channel_1,channel_2,channel_3;} pwm_sequ_val;
static struct {uint32_t output_pins[4];} pwm_config;
static uint32_t pins[]={0,1,2,3,4,5,6,7}, reverse[]={7,6,5,4,3,2,1,0};
static uint32_t *hw_get_led_array(void) { return pins; }
static uint32_t *hw_get_led_reversal_array(void) { return reverse; }
static void nrfx_pwm_stop(void *p,bool b) {}
static void nrfx_pwm_uninit(void *p) {}
static int nrf_drv_pwm_init(void *p,void *c,void *f) { return 0; }
static void nrf_drv_pwm_simple_playback(void *p,void *s,int n,int f) { starts++; }
static void set_slot_light_color(int c) { color_value=c; }
static void bsp_set_timer(int *t,int v) { *t=v; }
#define NO_TIMEOUT_1MS(t,n) (*(t)<(n))
"""+functions+r"""
int main(void) {
 rgb_marquee_usb_open_sweep(5,0); assert(color_value==5 && starts==1 && pwm_config.output_pins[0]==0);
 timer_value=79; rgb_marquee_usb_open_sweep(5,0); assert(starts==1);
 timer_value=80; rgb_marquee_usb_open_sweep(5,0); rgb_marquee_usb_open_sweep(5,0);
 assert(starts==2 && pwm_config.output_pins[0]==1);
 rgb_marquee_stop(); rgb_marquee_usb_open_sweep(3,1);
 assert(color_value==3 && pwm_config.output_pins[0]==7); // foreground changed PWM: fresh color + direction + phase
 rgb_marquee_stop(); rgb_marquee_usb_open_symmetric(4);
 assert(color_value==4 && pwm_config.output_pins[0]==0 && pwm_config.output_pins[1]==7);
 int previous=starts; timer_value=99; rgb_marquee_usb_open_symmetric(4); assert(starts==previous);
 timer_value=100; rgb_marquee_usb_open_symmetric(4); rgb_marquee_usb_open_symmetric(4); assert(starts==previous+1);
 g_usb_led_marquee_enable=false; rgb_marquee_usb_open_symmetric(4); assert(rgb_marquee_usb_open_step==0);
 g_usb_led_marquee_enable=true; rgb_marquee_stop(); cleared=0;
 rgb_marquee_usb_idle(); assert(cleared==255 && pwm_sequ_val.channel_0==1000);
 for(int i=0;i<4;i++) assert(pwm_config.output_pins[i]==(uint32_t)(i+2));
 int idle_starts=starts, old_color=color_value;
 for(int i=0;i<198;i++) {
  timer_value=25; rgb_marquee_usb_idle();
  assert(starts==idle_starts && color_value==old_color);
 }
 assert(rgb_marquee_usb_idle_step==3 && pwm_sequ_val.channel_0==1000);
 timer_value=24; rgb_marquee_usb_idle(); assert(rgb_marquee_usb_idle_step==3);
 timer_value=25; rgb_marquee_usb_idle(); assert(!m_pwm_initialized && rgb_marquee_usb_idle_step==0);
 rgb_marquee_usb_idle(); assert(color_value!=old_color && pwm_sequ_val.channel_0==1000);
 assert(starts==idle_starts+1);
 rgb_marquee_stop(); rgb_marquee_usb_open_sweep(0,0); rgb_marquee_stop();
 cleared=0; rgb_marquee_usb_idle(); assert(cleared==255 && pwm_sequ_val.channel_0==1000);
 for(int i=0;i<4;i++) assert(pwm_config.output_pins[i]==(uint32_t)(i+2));
 g_usb_led_marquee_enable=false; rgb_marquee_usb_idle(); assert(!m_pwm_initialized);

 return 0;
}
""")

    def test_usb_probe_does_not_change_led_mode(self):
        self.compile_run({'common.h':COMMON,'usb_led_mode.h':(SRC/'usb_led_mode.h').read_text()}, r"""
#include "common.h"
#include "usb_led_mode.h"
int main(void) {
 usb_led_mode_t s={0};
 for(uint32_t t=0;t<10000;t+=1000) {
  assert(!usb_led_mode_update(&s,true,t,1000));
  assert(!usb_led_mode_update(&s,true,t+500,1000));
  assert(!usb_led_mode_update(&s,false,t+600,1000));
 }
 assert(!usb_led_mode_update(&s,true,10000,1000));
 assert(!usb_led_mode_update(&s,true,10999,1000));
 assert(usb_led_mode_update(&s,true,11000,1000));
 assert(usb_led_mode_update(&s,false,12000,1000));
 assert(usb_led_mode_update(&s,true,12500,1000));
 assert(usb_led_mode_update(&s,false,14000,1000));
 assert(!usb_led_mode_update(&s,false,15000,1000));
 s=(usb_led_mode_t){0};
 assert(!usb_led_mode_update(&s,true,0xffff00,1000));
 assert(!usb_led_mode_update(&s,true,0x2e7,1000));
 assert(usb_led_mode_update(&s,true,0x2e8,1000));
 return 0;
}
""")

    def test_protocol_has_no_collisions_and_preserves_official(self):
        text=(SRC/'data_cmd.h').read_text()
        pairs=re.findall(r'#define (DATA_CMD_\w+)\s+\((\d+)\)',text)
        extension=[(name,n) for name,n in pairs if 1100 <= int(n) <= 1108]
        self.assertEqual(len(extension),9)
        for name,n in extension: self.assertEqual(sum(v==n for _,v in pairs),1)
        d=dict(pairs)
        self.assertEqual(d['DATA_CMD_GET_LONG_PRESS_THRESHOLD'],'1041')
        self.assertEqual(d['DATA_CMD_SET_LONG_PRESS_THRESHOLD'],'1042')
        self.assertEqual(d['DATA_CMD_GET_MOCHA_IDENTITY'],'1100')

    def test_cli_identity_gate_and_serial_frame(self):
        spec=importlib.util.spec_from_file_location('mocha',ROOT/'tools/mocha.py')
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        f=module.frame(1104,b'\x13\x88')
        self.assertEqual(sum(f[:9])&255,0); self.assertEqual(sum(f[9:])&255,0)
        with self.assertRaises(Exception): module.bounded(100,5000)('99')
        self.assertEqual(module.bounded(1,16)('16'),16)
        # Mismatched official firmware returns successfully but must never be writable.
        import sys, types
        writes=[]
        class Serial:
            def __init__(self,*a,**k): self.closed=False
            def reset_input_buffer(self): pass
            def write(self,data): writes.append(data)
            def read(self,n):
                if n==9:
                    h=bytearray(module.frame(1100,b'official')[:9]); h[5]=0x68; h[8]=(-sum(h[:8]))&255; return bytes(h)
                return b'official'+bytes([(-sum(b'official'))&255])
            def close(self): self.closed=True
        old=sys.modules.get('serial'); old_platform=sys.platform
        sys.modules['serial']=types.SimpleNamespace(Serial=Serial); sys.platform='test'
        try:
            with self.assertRaisesRegex(RuntimeError,'identity mismatch'): module.Device('/unused')
            self.assertEqual(len(writes),1); self.assertEqual(int.from_bytes(writes[0][2:4],'big'),1100)
        finally:
            sys.platform=old_platform
            if old is None: del sys.modules['serial']
            else: sys.modules['serial']=old

if __name__=='__main__': unittest.main(verbosity=2)
