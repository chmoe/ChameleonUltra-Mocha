#include "rf_diag.h"
#include <string.h>
#include "app_timer.h"
#include "app_util_platform.h"
#define CAPACITY 256u
typedef struct {
    uint32_t sequence, ticks;
    uint8_t kind, slot, state, hardware;
    uint16_t bits, captured;
    uint8_t data[16];
} event_t;
_Static_assert(sizeof(event_t)==32, "RF event wire size");
static event_t events[CAPACITY];
static uint32_t next_sequence;
void rf_diag_record(uint8_t kind, uint8_t slot, uint8_t state, uint8_t hardware,
                    const uint8_t *data, uint16_t bits) {
    CRITICAL_REGION_ENTER();
    event_t *e=&events[next_sequence % CAPACITY];
    memset(e,0,sizeof(*e));
    e->sequence=next_sequence++;
    e->ticks=app_timer_cnt_get();
    e->kind=kind; e->slot=slot; e->state=state; e->hardware=hardware;
    e->bits=bits;
    if (data) {
        uint32_t bytes=((uint32_t)bits+7)/8;
        e->captured=bytes>sizeof(e->data)?sizeof(e->data):bytes;
        memcpy(e->data,data,e->captured);
    }
    CRITICAL_REGION_EXIT();
}
uint16_t rf_diag_read(uint32_t start, uint8_t limit, uint8_t *out) {
    if (!limit || limit>8) return 0;
    uint16_t size;
    CRITICAL_REGION_ENTER();
    uint32_t end=next_sequence, first=end>CAPACITY?end-CAPACITY:0;
    if (start<first) start=first;
    if (start>end) start=end;
    uint32_t count=end-start;
    if (count>limit) count=limit;
    uint32_t header[4]={1,first,end,count};
    memcpy(out,header,sizeof(header));
    for (uint32_t i=0;i<count;i++)
        memcpy(out+16+i*sizeof(event_t),&events[(start+i)%CAPACITY],sizeof(event_t));
    size=16+count*sizeof(event_t);
    CRITICAL_REGION_EXIT();
    return size;
}
