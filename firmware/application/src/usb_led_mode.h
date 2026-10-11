#ifndef USB_LED_MODE_H
#define USB_LED_MODE_H
#include <stdbool.h>
#include <stdint.h>

typedef struct {
    bool connected;
    bool candidate;
    uint32_t since;
} usb_led_mode_t;

// CDC probes are short-lived connections. Change the visual mode only after
// the requested state stays stable; transport processing remains immediate.
static inline bool usb_led_mode_update(usb_led_mode_t *state, bool opened,
                                      uint32_t now, uint32_t settle_ticks) {
    if (opened != state->candidate) {
        state->candidate = opened;
        state->since = now;
    }
    // app_timer uses a 24-bit RTC counter.
    if (state->connected != state->candidate &&
        ((now - state->since) & 0x00ffffffu) >= settle_ticks) {
        state->connected = state->candidate;
    }
    return state->connected;
}
#endif
