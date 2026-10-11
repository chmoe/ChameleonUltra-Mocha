#pragma once
#include <stdint.h>
#define RF_CLOCK_HF 1u
#define RF_CLOCK_LF 2u
// Thread context only; RF shares the SDK clock reference counter with USB.
void rf_clock_acquire(uint8_t owner);
void rf_clock_release(uint8_t owner);
