"""Regressions for transient physical-field samples during trace collection.

The Nordic field checker can briefly report absent while an RF transaction is
still active. Trace storage must wait for 100 ms of confirmed absence, including
when a FIELD_LOST callback arrives, and preserve the current RAM session if the
field returns before that interval.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_access_trace import MOCK, ROOT


PREAMBLE = r'''
#include "access_trace.c"
static uint8_t out[1024];
static uint16_t outlen;
static void start(void) {
    uint8_t enable=1;
    access_trace_init();
    assert(access_trace_command(1122,&enable,1,out,&outlen)==STATUS_SUCCESS);
    physical_rf=true;
    access_trace_field(true);
    assert(active && !pending && writes==0);
}
static void event(uint8_t block) {
    uint8_t data[16];
    memset(data,block,sizeof(data));
    access_trace_event(2,0x30,block,0,1,255,0,data,sizeof(data));
}
static void check_saved(unsigned events) {
    assert(count==1 && writes==1 && !active && !pending);
    assert(load(1,(uint8_t *)scratch));
    assert(rd16((uint8_t *)scratch+12)==events);
    assert(((uint8_t *)scratch)[32+(events-1)*32+4]==5);
}
'''


class TraceRfLossTests(unittest.TestCase):
    def run_program(self, body, mock=MOCK):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            for name in ['app_timer.h','fds_util.h','tag_emulation.h',
                         'bsp_wdt.h','app_util_platform.h']:
                (directory/name).write_text('#include "mock.h"\n')
            (directory/'mock.h').write_text(mock)
            for name in ['access_trace.c','access_trace.h','app_status.h']:
                source=ROOT/'firmware/application/src'/name
                (directory/name).write_text(source.read_text())
            (directory/'test.c').write_text(PREAMBLE+body)
            binary=directory/'test'
            build=subprocess.run(
                ['cc','-std=c11','-Wall','-Werror',
                 '-Wno-misleading-indentation','-I',tmp,
                 str(directory/'test.c'),'-o',str(binary)],
                capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_false_sample_never_writes_in_rf_and_recovery_keeps_session(self):
        self.run_program(r'''
int main(void) {
    start();
    event(4);
    /* A false field_check sample is not permission to write physical flash. */
    access_trace_process(false);
    assert(active && !pending && writes==0 && n_events==1);
    tick+=APP_TIMER_TICKS(99);
    access_trace_process(false);
    assert(active && !pending && writes==0 && n_events==1);
    access_trace_process(true);
    event(5);
    tick+=APP_TIMER_TICKS(200);
    access_trace_process(true);
    assert(active && !pending && writes==0 && n_events==2);
    /* A later real departure starts a fresh 100 ms confirmation interval. */
    physical_rf=false;
    access_trace_field(false);
    access_trace_process(false);
    assert(active && !pending && writes==0 && n_events==2);
    tick+=APP_TIMER_TICKS(99);
    access_trace_process(false);
    assert(active && !pending && writes==0);
    tick+=APP_TIMER_TICKS(1);
    access_trace_process(false);
    check_saved(3);
    assert(((uint8_t *)scratch)[32+6]==4);
    assert(((uint8_t *)scratch)[64+6]==5);
    access_trace_process(false);
    assert(count==1 && writes==1); /* No duplicate end event or session. */
    return 0;
}
''')

    def test_false_lost_callback_is_canceled_when_field_returns(self):
        self.run_program(r'''
int main(void) {
    start();
    event(7);
    tick+=APP_TIMER_TICKS(20);
    access_trace_field(false);
    assert(active && !pending && n_events==1 && writes==0);
    access_trace_process(true);
    access_trace_field(true);
    event(8);
    assert(active && !pending && n_events==2 && writes==0);
    physical_rf=false;
    access_trace_field(false);
    access_trace_process(false);
    tick+=APP_TIMER_TICKS(100);
    access_trace_process(false);
    check_saved(3);
    assert(((uint8_t *)scratch)[32+6]==7);
    assert(((uint8_t *)scratch)[64+6]==8);
    return 0;
}
''')

    def test_true_loss_without_callback_saves_after_confirmed_absence(self):
        self.run_program(r'''
int main(void) {
    start();
    event(9);
    physical_rf=false;
    access_trace_process(false);
    assert(active && !pending && writes==0);
    tick+=APP_TIMER_TICKS(99);
    access_trace_process(false);
    assert(active && !pending && writes==0);
    tick+=APP_TIMER_TICKS(1);
    access_trace_process(false);
    check_saved(2);
    return 0;
}
''')

    def test_field_return_after_absence_confirmation_prevents_flash_queue(self):
        mock=MOCK.replace(
            '#define CRITICAL_REGION_ENTER()',
            '#define CRITICAL_REGION_ENTER() (++test_critical_depth)\n'
            'static unsigned test_critical_depth;')
        mock=mock.replace(
            '#define CRITICAL_REGION_EXIT()',
            '#define CRITICAL_REGION_EXIT() test_critical_exit()\n'
            'static void test_critical_exit(void);')
        self.run_program(r'''
static bool inject_new_field;
static void test_critical_exit(void) {
    assert(test_critical_depth);
    if (--test_critical_depth==0 && inject_new_field &&
            !active && pending && !rf_present) {
        /* A real field interrupt may run as soon as the outer mask lifts. */
        inject_new_field=false;
        physical_rf=true;
        access_trace_field(true);
    }
}
int main(void) {
    start();
    event(4);
    physical_rf=false;
    access_trace_field(false);
    access_trace_process(false);
    tick+=APP_TIMER_TICKS(100);
    inject_new_field=true;
    access_trace_process(false);
    assert(!inject_new_field && physical_rf && rf_present);
    assert(writes==0 && count==0 && pending && !active);
    access_trace_process(true);
    assert(writes==0 && pending);
    /* The old session remains available and is saved after the new departure. */
    physical_rf=false;
    access_trace_field(false);
    access_trace_process(false);
    tick+=APP_TIMER_TICKS(100);
    access_trace_process(false);
    check_saved(2);
    assert(test_critical_depth==0);
    return 0;
}
''',mock=mock)


if __name__=='__main__':
    unittest.main()
