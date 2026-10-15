"""Exercise actual feedback PWM state machine and button release dispatch."""
import re, unittest
from test_host import FirmwareTests,COMMON,SRC

def function(text,name):
    match=re.search(r'(?m)^(?:static )?[\w *]+\b'+name+r'\([^;\n]*\)\s*\{',text)
    assert match,name
    start=match.start();end=match.end();depth=1
    while depth:depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]

class ButtonTests(FirmwareTests):
    # Run only new tests here; existing FirmwareTests are separately discovered.
    def test_trace_feedback_order_and_colors(self):
        source=(SRC/'rgb_marquee.c').read_text()
        declarations=source[source.index('static bool trace_working'):source.index('static bool m_pwm_initialized')]
        names=['rgb_pwm_uninit','trace_pwm_uninit','rgb_pwm_init','rgb_marquee_stop','rgb_marquee_trace_start','rgb_marquee_trace_pending','trace_show_step','rgb_marquee_trace_process']
        funcs='\n'.join(function(source,name) for name in names)
        self.assertNotIn('bsp_delay',funcs)
        self.compile_run({'common.h':COMMON},'#include "common.h"\n'+r'''
#define RGB_LIST_NUM 8
#define LED_R 40
#define LED_G 41
#define LED_B 42
#define NRF_DRV_PWM_PIN_INVERTED 128
#define NRF_DRV_PWM_PIN_NOT_USED 255
#define NRF_DRV_PWM_FLAG_LOOP 1
#define NO_TIMEOUT_1MS(t,n) (*(t)<=(n))
#define APP_ERROR_CHECK(x) assert((x)==0)
typedef void (*nrfx_pwm_handler_t)(int);
static bool m_pwm_initialized;
static int pwm0_ins,seq,time_value,init_count,stop_count,restore_count;
static bool stop_wait;
static int *timer=&time_value;
static uint8_t rgb_marquee_usb_idle_step,rgb_marquee_usb_open_step;
static uint32_t pins[]={17,8,3,25,21,4,11,31},lit;
static struct {uint32_t output_pins[4];} pwm_config;
static struct {uint16_t channel_0,channel_1,channel_2,channel_3;} pwm_sequ_val;
static uint32_t *hw_get_led_array(void) {return pins;}
static void nrf_gpio_pin_clear(uint32_t pin) {lit &= ~(1u<<pin);}
static void nrf_gpio_pin_set(uint32_t pin) {lit |= 1u<<pin;}
static void nrfx_pwm_stop(void *p,bool b) {(void)p;stop_wait=b;stop_count++;}
static void nrfx_pwm_uninit(void *p) {(void)p;}
static int nrf_drv_pwm_init(void *p,void *c,void *f) {
 (void)p;(void)c;(void)f;init_count++;
 assert(pwm_config.output_pins[0]==(LED_R|128));assert(pwm_config.output_pins[1]==(LED_G|128));assert(pwm_config.output_pins[2]==(LED_B|128));return 0;
}
static void nrf_drv_pwm_simple_playback(void *p,void *s,int n,int f) {(void)p;(void)s;(void)n;(void)f;}
static void bsp_set_timer(int *t,int n) {*t=n;}
void rgb_marquee_stop(void);
static void light_up_by_slot(void) {restore_count++;rgb_marquee_stop();lit=1u<<pins[5];}
'''+declarations+funcs+r'''
static const uint16_t wanted[8][3]={{1000,0,0},{1000,251,0},{1000,1000,0},{0,1000,0},{0,1000,1000},{0,0,1000},{1000,0,1000},{1000,1000,1000}};
static void check(unsigned physical) {
 assert(lit==(1u<<pins[physical]));assert(pwm_sequ_val.channel_0==wanted[physical][0]);
 assert(pwm_sequ_val.channel_1==wanted[physical][1]);assert(pwm_sequ_val.channel_2==wanted[physical][2]);
}
int main(void) {
 for(unsigned i=0;i<8;i++)for(unsigned j=i+1;j<8;j++)assert(memcmp(wanted[i],wanted[j],sizeof(wanted[i])));
 rgb_marquee_trace_start(true);assert(rgb_marquee_trace_pending());
 assert(!rgb_marquee_trace_process(true)&&init_count==0); // RF defers even PWM init.
 assert(rgb_marquee_trace_process(false));check(0);
 for(unsigned i=1;i<8;i++){time_value=79;assert(rgb_marquee_trace_process(false));check(i-1);time_value=80;assert(rgb_marquee_trace_process(false));check(i);}
 time_value=80;assert(!rgb_marquee_trace_process(false)&&!rgb_marquee_trace_pending());assert(restore_count==1);
 rgb_marquee_trace_start(false);assert(rgb_marquee_trace_process(false));check(7);
 for(unsigned i=1;i<8;i++){time_value=80;assert(rgb_marquee_trace_process(false));check(7-i);}
 time_value=80;assert(!rgb_marquee_trace_process(false));
 rgb_marquee_trace_start(true);assert(rgb_marquee_trace_process(false));time_value=80;rgb_marquee_trace_process(false);check(1);
 assert(!rgb_marquee_trace_process(true)&&!m_pwm_initialized&&rgb_marquee_trace_pending()&&!stop_wait);
 assert(rgb_marquee_trace_process(false));check(1); // Resume interrupted step.
 rgb_marquee_stop();assert(!rgb_marquee_trace_pending()&&!rgb_marquee_trace_process(false));
 assert(rgb_marquee_usb_idle_step==0&&rgb_marquee_usb_open_step==0);return 0;
}
''')
    def test_long_and_short_dispatch_use_same_action(self):
        source=(SRC/'app_main.c').read_text()
        self.compile_run({'common.h':COMMON},'#include "common.h"\n'+r'''
#define SLEEP_DELAY_MS_BUTTON_CLICK 1000
static bool m_is_b_btn_release,m_is_a_btn_release,m_is_btn_long_press,m_is_field_on,m_ab_reboot_pending;
bool g_usb_led_marquee_enable=true;
static uint8_t last_action;static unsigned calls;
static uint8_t settings_get_button_press_config(char b) {return b=='a'?8:2;}
static uint8_t settings_get_long_button_press_config(char b) {return b=='b'?8:3;}
static void run_button_function_by_settings(uint8_t a) {last_action=a;calls++;}
static void sleep_timer_start(int ms) {(void)ms;}
'''+function(source,'button_press_process')+r'''
int main(void) {
 m_is_a_btn_release=true;button_press_process();assert(last_action==8&&calls==1&&!m_is_a_btn_release);
 m_is_btn_long_press=true;m_is_b_btn_release=true;button_press_process();assert(last_action==8&&calls==2&&!m_is_b_btn_release);
 m_is_a_btn_release=true;button_press_process();assert(last_action==3&&calls==3);
 m_ab_reboot_pending=true;m_is_a_btn_release=m_is_b_btn_release=true;button_press_process();assert(calls==3&&!m_is_a_btn_release&&!m_is_b_btn_release);
 return 0;
}
''')

    def test_long_only_mapping_and_ab_reboot(self):
        source=(SRC/'app_main.c').read_text()
        self.compile_run({'common.h':COMMON},'#include "common.h"\n'+r'''
#define BUTTON_1 1
#define BUTTON_2 2
#define SettingsButtonDisable 0
#define APP_TIMER_TICKS(n) (n)
typedef unsigned nrf_drv_gpiote_pin_t;
static bool m_system_off_processing,m_is_a_btn_press,m_is_b_btn_press,m_is_a_btn_release,m_is_b_btn_release,m_is_btn_long_press,m_ab_reboot_pending;
static uint32_t m_last_btn_press,now;
static unsigned level;
static uint32_t app_timer_cnt_get(void) {return now;}
static uint32_t app_timer_cnt_diff_compute(uint32_t a,uint32_t b) {return a-b;}
static unsigned nrf_gpio_pin_read(unsigned pin) {(void)pin;return level;}
static uint8_t settings_get_button_press_config(char b) {(void)b;return 0;}
static uint8_t settings_get_long_button_press_config(char b) {(void)b;return 8;}
static unsigned settings_get_long_press_threshold(void) {return 1000;}
static bool settings_get_ab_reboot_enable(void) {return true;}
'''+function(source,'timer_button_event_handle')+r'''
int main(void) {
 unsigned a=BUTTON_2,b=BUTTON_1;
 level=1;timer_button_event_handle(&a);assert(m_is_a_btn_press);
 level=0;now=1500;timer_button_event_handle(&a);assert(m_is_a_btn_release&&m_is_btn_long_press&&!m_ab_reboot_pending);
 m_is_a_btn_release=false;level=1;now=2000;timer_button_event_handle(&a);
 level=0;now=2200;timer_button_event_handle(&a);assert(!m_is_a_btn_release&&!m_is_a_btn_press);
 level=1;now=3000;timer_button_event_handle(&a);timer_button_event_handle(&b);
 level=0;now=4500;timer_button_event_handle(&b);assert(m_ab_reboot_pending);
 return 0;
}
''')

# Avoid duplicating inherited original tests in discovery.
for name in list(vars(FirmwareTests)):
    if name.startswith('test_'):setattr(ButtonTests,name,None)
del FirmwareTests
if __name__=='__main__':unittest.main()
