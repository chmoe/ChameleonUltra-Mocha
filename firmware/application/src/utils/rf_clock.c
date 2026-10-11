#include "rf_clock.h"
#include "nrf_soc.h"
#include "app_error.h"
static uint8_t m_owners;
void rf_clock_acquire(uint8_t owner) {
    if (m_owners & owner) return;
    if (!m_owners) {
        APP_ERROR_CHECK(sd_clock_hfclk_request());
        uint32_t running = 0;
        while (!running) APP_ERROR_CHECK(sd_clock_hfclk_is_running(&running));
    }
    m_owners |= owner;
}
void rf_clock_release(uint8_t owner) {
    if (!(m_owners & owner)) return;
    m_owners &= (uint8_t)~owner;
    if (!m_owners) APP_ERROR_CHECK(sd_clock_hfclk_release());
}
