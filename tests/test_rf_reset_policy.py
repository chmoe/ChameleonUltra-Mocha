"""Exercise real Classic/NTAG load callbacks with the shared 14A policy."""
import subprocess
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / 'firmware/application/src/rfid/nfctag/hf'

def function(source, name):
    text = source.read_text()
    start = text.index(name + '(')
    start = text.rfind('\n', 0, start) + 1
    opening = text.index('{', start)
    depth, end = 1, opening + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]

class ResetPolicyTests(unittest.TestCase):
    def test_classic_ntag_and_other_handlers_do_not_share_saved_policy(self):
        shared = '\n'.join(function(SRC/'nfc_14a.c', name) for name in [
            'nfc_tag_14a_set_handler', 'nfc_tag_14a_set_reset_enable',
            'nfc_tag_14a_is_reset_enable'])
        classic = function(SRC/'nfc_mf1.c', 'nfc_tag_mf1_data_loadcb')
        ntag = function(SRC/'nfc_mf0_ntag.c', 'nfc_tag_mf0_ntag_data_loadcb')
        program = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <assert.h>
#define NRF_LOG_INFO(...)
#define NRF_LOG_ERROR(...)
#define ASSERT(x) assert(x)
typedef int tag_specific_type_t;
typedef struct {int length; uint8_t *buffer;} tag_data_buffer_t;
typedef struct {void (*get_coll_res)(void), (*cb_state)(void), (*cb_reset)(void);} nfc_tag_14a_handler_t;
typedef struct {struct {bool field_off_do_reset;} config;} nfc_tag_mf1_information_t;
typedef struct {int unused;} nfc_tag_mf0_ntag_information_t;
static bool reset_if_field_lost;
static nfc_tag_14a_handler_t m_tag_handler;
static int get_information_size_by_tag_type(int type) {return 16;}
static void get_mifare_coll_res(void) {}
static void nfc_tag_mf1_state_handler(void) {}
static void nfc_tag_mf1_reset_handler(void) {}
static void nfc_tag_mf0_ntag_get_coll_res(void) {}
static void nfc_tag_mf0_ntag_state_handler(void) {}
static void nfc_tag_mf0_ntag_reset_handler(void) {}
static void ulc_3des_init(void) {}
''' + shared + r'''
static nfc_tag_mf1_information_t *classic_information;
static nfc_tag_mf0_ntag_information_t *ntag_information;
static int classic_type,ntag_type;
#define m_tag_information classic_information
#define m_tag_type classic_type
''' + classic + r'''
#undef m_tag_information
#undef m_tag_type
#define m_tag_information ntag_information
#define m_tag_type ntag_type
''' + ntag + r'''
int main(void) {
 nfc_tag_mf1_information_t yes={.config={true}}, no={.config={false}};
 uint8_t raw[16]={0};
 tag_data_buffer_t on={16,(uint8_t *)&yes}, off={16,(uint8_t *)&no}, tag={16,raw};
 // Classic ON -> NTAG -> Classic ON: only runtime policy changes.
 nfc_tag_mf1_data_loadcb(1001,&on);assert(nfc_tag_14a_is_reset_enable());
 nfc_tag_mf0_ntag_data_loadcb(1101,&tag);assert(!nfc_tag_14a_is_reset_enable());
 assert(m_tag_handler.cb_state==nfc_tag_mf0_ntag_state_handler && yes.config.field_off_do_reset);
 nfc_tag_mf1_data_loadcb(1001,&on);assert(nfc_tag_14a_is_reset_enable());
 // Classic ON -> Classic OFF -> NTAG: apply the destination option.
 nfc_tag_mf1_data_loadcb(1001,&off);assert(!nfc_tag_14a_is_reset_enable());
 nfc_tag_mf0_ntag_data_loadcb(1101,&tag);assert(!nfc_tag_14a_is_reset_enable());
 assert(!no.config.field_off_do_reset && yes.config.field_off_do_reset);
 // Any other registered tag type gets the safe default as well.
 nfc_tag_mf1_data_loadcb(1001,&on);
 nfc_tag_14a_handler_t other={0};nfc_tag_14a_set_handler(&other);
 assert(!nfc_tag_14a_is_reset_enable());
 // Preserve the existing NULL-handler no-op contract.
 nfc_tag_mf1_data_loadcb(1001,&on);nfc_tag_14a_set_handler(NULL);
 assert(nfc_tag_14a_is_reset_enable() && m_tag_handler.cb_state==nfc_tag_mf1_state_handler);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p/'test.c').write_text(program)
            built = subprocess.run(['cc','-std=c11','-Wall','-Werror',str(p/'test.c'),
                                    '-o',str(p/'test')], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            subprocess.run([str(p/'test')], check=True)
