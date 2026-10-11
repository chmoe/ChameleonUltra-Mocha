#include "polling.h"

#include "app_timer.h"
#include "rfid_main.h"
#include "settings.h"
#include "tag_emulation.h"
#include "lf_tag_em.h"
#include "nfc_14a.h"

APP_TIMER_DEF(m_polling_timer);

#define POLLING_HF_QUIET_MS 50

static volatile bool m_polling_pending;
static bool m_polling_running;
static volatile uint32_t m_last_reader_activity;
static volatile bool m_hf_seen;
static volatile bool m_hf_locked;
static bool m_session_hf;
static bool m_polling_active;      // cycling session in progress
static uint8_t m_original_slot;    // slot to restore when the reader leaves

static void polling_timer_handler(void *p_context) {
    m_polling_pending = true;   // only set a flag: slot switch touches flash
}

void polling_init(void) {
    ret_code_t err_code = app_timer_create(&m_polling_timer, APP_TIMER_MODE_REPEATED, polling_timer_handler);
    APP_ERROR_CHECK(err_code);
}

void polling_start(void) {
    if (!settings_get_polling_enable()) { polling_stop(); return; }
    m_polling_pending = false;
    // Stop-then-start so an interval change always takes effect immediately,
    // regardless of the previous timer state.
    app_timer_stop(m_polling_timer);
    ret_code_t err_code = app_timer_start(m_polling_timer,
                                          APP_TIMER_TICKS(settings_get_polling_interval_ms()), NULL);
    APP_ERROR_CHECK(err_code);
    m_polling_running = true;
}

void polling_stop(void) {
    ret_code_t err_code = app_timer_stop(m_polling_timer);
    APP_ERROR_CHECK(err_code);
    m_polling_pending = false;
    m_polling_running = false;
    m_polling_active = false;
    lf_polling_resume();
}

bool polling_is_running(void) {
    return m_polling_running;
}

void polling_note_hf_field(bool present) {
    m_hf_seen = present;
    if (!present) m_hf_locked = false;
}

void polling_lock_hf_transaction(void) { m_hf_locked = true; }

void polling_note_reader_activity(void) {
    m_last_reader_activity = app_timer_cnt_get();
}

// Next enabled slot that participates in polling (skips polling_skip slots).
static uint8_t polling_find_next(uint8_t slot_now) {
    uint8_t candidate = slot_now;
    for (uint8_t i = 0; i < TAG_MAX_SLOT_NUM; i++) {
        candidate = tag_emulation_slot_find_next(candidate);
        if (candidate == slot_now) {
            break;  // no other enabled slot
        }
        // Keep the sensor for the triggering modality enabled on every candidate.
        if (!tag_emulation_slot_polling_skip(candidate) &&
            is_slot_enabled(candidate, m_session_hf ? TAG_SENSE_HF : TAG_SENSE_LF)) {
            return candidate;
        }
    }
    return slot_now;
}

static bool polling_reader_present(void) {
    return lf_reader_field_present() || nfc_tag_14a_field_present();
}

void polling_process(void) {
    if (!m_polling_running) return;
    if (!settings_get_polling_enable()) { polling_stop(); return; }
    if (get_device_mode() != DEVICE_MODE_TAG) {
        m_polling_active = false;
        m_polling_pending = false;
        lf_polling_resume();
        return;
    } // emulation mode only

    if (polling_reader_present()) {
        if (!m_polling_active) {
            // Reader arrived: start a cycling session from the current slot.
            m_session_hf = nfc_tag_14a_field_present();
            m_original_slot = tag_emulation_get_slot();
            m_polling_active = true;
            polling_start(); // interval begins at field/session arrival
        }
        if (!m_polling_pending) return;
        // Concurrent fields must not let LF polling interrupt an HF transaction.
        if (m_hf_locked || (!m_session_hf && nfc_tag_14a_field_present())) {
            lf_polling_resume();
            return;
        }
        if (m_session_hf) {
            // Never interrupt SELECT/authentication/read/write. Quiet pre-selection
            // activity may cycle, but any selected transaction locks until field loss.
            if (m_hf_locked) return;
            if (m_hf_seen && app_timer_cnt_diff_compute(app_timer_cnt_get(), m_last_reader_activity)
                    < APP_TIMER_TICKS(POLLING_HF_QUIET_MS)) return;
        }
        if (lf_reader_field_present() && !lf_polling_pause_at_boundary()) {
            return; // wait for a complete finite LF burst, never truncate a frame
        }
        m_polling_pending = false;
        uint8_t slot_now = tag_emulation_get_slot();
        uint8_t slot_new = polling_find_next(slot_now);
        if (slot_new == slot_now) { lf_polling_resume(); return; } // only one enabled slot
        if (m_session_hf && !nfc_tag_14a_polling_quiesce()) {
            m_polling_pending = true;
            return;
        }
        if (m_session_hf) {
            // Keep NFCT field/clock state alive while replacing card data.
            lf_tag_125khz_sense_switch(false);
            tag_emulation_change_slot(slot_new, false);
            tag_emulation_sense_switch(TAG_SENSE_LF, true);
            nfc_tag_14a_polling_resume();
        } else {
            tag_emulation_change_slot(slot_new, true);
        }
        // RF polling feedback must not block the main loop for a sweep.
        light_up_by_slot();
    } else {
        m_polling_pending = false;
        if (m_polling_active) {
            // Reader left: stop cycling and restore the original slot.
            m_hf_locked = false;
            m_hf_seen = false;
            tag_emulation_change_slot(m_original_slot, true);
            light_up_by_slot();
            m_polling_active = false;
        }
    }
}

void polling_forget_session(void) {
    m_polling_active = false;
    m_polling_pending = false;
    lf_polling_resume();
}
bool polling_hf_can_switch(void) {
    return !m_hf_locked && (!m_hf_seen ||
        app_timer_cnt_diff_compute(app_timer_cnt_get(), m_last_reader_activity)
            >= APP_TIMER_TICKS(POLLING_HF_QUIET_MS));
}
