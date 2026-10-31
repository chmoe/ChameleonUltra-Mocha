#pragma once
#include <stdint.h>
/* RAM only; protocol v1 is little endian, 16-byte header, 32-byte events. */
enum { RF_DIAG_FIELD_ON=1, RF_DIAG_FIELD_OFF, RF_DIAG_RX, RF_DIAG_TX_START,
       RF_DIAG_TX_END, RF_DIAG_TIMEOUT, RF_DIAG_READY, RF_DIAG_SENSE_ON,
       RF_DIAG_SENSE_OFF, RF_DIAG_TX_REQUEST, RF_DIAG_REARM };
void rf_diag_record(uint8_t kind, uint8_t slot, uint8_t state, uint8_t hardware,
                    const uint8_t *data, uint16_t bits);
uint16_t rf_diag_read(uint32_t start, uint8_t limit, uint8_t *out);
