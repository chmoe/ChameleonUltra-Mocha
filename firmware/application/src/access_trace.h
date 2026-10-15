#ifndef ACCESS_TRACE_H
#define ACCESS_TRACE_H
#include <stdint.h>
#include <stdbool.h>
void access_trace_init(void);
void access_trace_field(bool present);
void access_trace_process(bool present);
bool access_trace_busy(void);
void access_trace_button_toggle(void);
bool access_trace_take_feedback(bool *enabled);
void access_trace_event(uint8_t kind, uint8_t command, uint8_t block, uint8_t key,
                        uint8_t result, uint8_t response, uint8_t flags,
                        const uint8_t *data, uint8_t length);
uint16_t access_trace_command(uint16_t cmd, const uint8_t *data, uint16_t length,
                              uint8_t *out, uint16_t *out_length);
#endif
