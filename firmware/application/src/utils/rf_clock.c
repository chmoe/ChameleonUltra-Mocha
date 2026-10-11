#include "rf_clock.h"
#include "nrf_drv_clock.h"
static uint8_t m_owners;
void rf_clock_acquire(uint8_t owner) {
    if (m_owners & owner) return;
    if (!m_owners) {
        // USB uses this same reference counter. Direct SoftDevice requests
        // would be cancelled when USB releases its last driver reference.
        nrf_drv_clock_hfclk_request(NULL);
        while (!nrf_drv_clock_hfclk_is_running()) {}
    }
    m_owners |= owner;
}
void rf_clock_release(uint8_t owner) {
    if (!(m_owners & owner)) return;
    m_owners &= (uint8_t)~owner;
    if (!m_owners) nrf_drv_clock_hfclk_release();
}
