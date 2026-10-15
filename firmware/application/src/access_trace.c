/* Trace storage is a bounded tenant of existing FDS. No raw flash addresses. */
#include "access_trace.h"
#include <string.h>
#include "app_timer.h"
#include "app_status.h"
#include "fds_util.h"
#include "tag_emulation.h"
#include "bsp_wdt.h"
#include "app_util_platform.h"
#define FILE_ID 0x1300
#define CONTROL_ID 0x1301
#define CONTROL_MAGIC 0x35524354u
#define SESSIONS 7
#define EVENTS 31
#define SIZE 1024
#define FULL 1
#define OVERFLOW 2
#define FAILED 4
#define CORRUPT 8
static uint32_t ram[SIZE/4], scratch[SIZE/4];
static uint8_t keys[SESSIONS], count, occupied;
static volatile uint8_t flags;
static bool enabled, clear_failed, save_blocked, enable_requested;
static int8_t feedback=-1;
static bool state_dirty, state_blocked;
static uint32_t state_retry_at;
static uint32_t control[4];
static volatile bool active, pending, saving, rf_present;
static volatile bool loss_checking, field_seen;
static uint32_t loss_since;
static uint32_t generation=1, last_tick, failures, retry_at;
static uint64_t session_ticks;
static volatile uint32_t dropped;
static uint16_t n_events;
static uint32_t next_id=1;
static volatile bool fds_done;
static uint8_t expected_event;
static uint16_t expected_key, expected_file=FILE_ID;
static volatile uint32_t fds_result;
static uint16_t rd16(const uint8_t *p) { return p[0] | (uint16_t)p[1]<<8; }
static uint32_t rd32(const uint8_t *p) { return rd16(p) | (uint32_t)rd16(p+2)<<16; }
static void wr16(uint8_t *p,uint16_t v) { p[0]=v; p[1]=v>>8; }
static void wr32(uint8_t *p,uint32_t v) { wr16(p,v); wr16(p+2,v>>16); }
static uint32_t crc_bytes(const uint8_t *p, unsigned length, unsigned crc_offset) {
    uint32_t c=~0u;
    for (unsigned i=0;i<length;i++) {
        uint8_t b=(i>=crc_offset && i<crc_offset+4)?0:p[i]; c^=b;
        for(unsigned j=0;j<8;j++) c=(c>>1)^((0-(c&1))&0xedb88320u);
    }
    return ~c;
}
static uint32_t crc(const uint8_t *p) { return crc_bytes(p,SIZE,16); }
static uint32_t elapsed(void) {
    uint64_t ms;
    CRITICAL_REGION_ENTER();
    uint32_t now=app_timer_cnt_get();
    session_ticks+=app_timer_cnt_diff_compute(now,last_tick); last_tick=now;
    ms=session_ticks*1000/32768;
    CRITICAL_REGION_EXIT();
    return ms>UINT32_MAX ? UINT32_MAX : (uint32_t)ms;
}
/* Register separately: errors in our records must never reset the device. */
static void storage_event(fds_evt_t const *e) {
    if (e->id != expected_event) return;
    if ((e->id==FDS_EVT_WRITE || e->id==FDS_EVT_UPDATE) && (e->write.file_id!=expected_file || e->write.record_key!=expected_key)) return;
    if (e->id==FDS_EVT_DEL_RECORD && (e->del.file_id!=expected_file || e->del.record_key!=expected_key)) return;
    fds_result=e->result; fds_done=true;
}
static bool wait_storage(uint32_t rc) {
    if(rc!=NRF_SUCCESS) return false;
    while(!fds_done) { bsp_wdt_feed(); __WFE(); }
    return fds_result==NRF_SUCCESS;
}
static bool load(uint8_t key, uint8_t *p) {
    uint16_t len=SIZE;
    if (!fds_read_sync(FILE_ID,key,&len,p) || len!=SIZE ||
        rd16(p+12)>EVENTS || p[10]>=16 || rd32(p+16)!=crc(p)) return false;
    for (unsigned i=0;i<rd16(p+12);i++) {
        const uint8_t *event=p+32+i*32;
        if (event[4]<1 || event[4]>5 || event[10]>16) return false;
    }
    return true;
}
static void scan_records(bool boot) {
    count=occupied=0; flags &= ~FULL;
    for(uint8_t k=1;k<=SESSIONS;k++) {
        if(!fds_is_exists(FILE_ID,k)) continue;
        occupied|=1u<<(k-1);
        if(!load(k,(uint8_t*)scratch)) { flags|=CORRUPT; continue; }
        keys[count++]=k;
        uint32_t id=rd32((uint8_t*)scratch);
        if(id>=next_id) next_id=id+1;
        if(boot) generation ^= rd32((uint8_t*)scratch+16);
    }
    if(occupied==127) flags|=FULL;
}
void access_trace_init(void) {
    fds_register(storage_event); scan_records(true);
    uint16_t length=sizeof(control);
    if(fds_is_exists(CONTROL_ID,1)) {
        if(fds_read_sync(CONTROL_ID,1,&length,(uint8_t*)control) && length==sizeof(control) &&
           control[0]==CONTROL_MAGIC && control[1]<=1 && control[2]==1 &&
           control[3]==crc_bytes((uint8_t*)control,sizeof(control),12)) enabled=control[1];
        else flags|=CORRUPT;
    }
}
bool access_trace_busy(void) { return active || pending || saving || enable_requested || state_dirty; }
static void stop_collection(void) {
    CRITICAL_REGION_ENTER();
    enable_requested=false;
    if(enabled) {
        enabled=false; feedback=0; state_dirty=true; state_blocked=false;
        if(active) ((uint8_t*)ram)[11]|=2;
    }
    CRITICAL_REGION_EXIT();
}
void access_trace_button_toggle(void) {
    if(enabled || enable_requested) stop_collection();
    else enable_requested=true;
}
bool access_trace_take_feedback(bool *state) {
    if(feedback<0) return false;
    *state=feedback!=0; feedback=-1; return true;
}
#define TRACE_RF_DEFERRED 0x8f000001u
static bool storage_deferred;
enum trace_storage_op { TRACE_WRITE, TRACE_UPDATE, TRACE_DELETE, TRACE_GC };
static uint32_t queue_storage(enum trace_storage_op op, fds_record_desc_t *desc, const fds_record_t *record) {
    uint32_t rc=TRACE_RF_DEFERRED;
    /* Recheck at the queue boundary: a new FIELD_DETECTED may have arrived
       since the main-loop absence check. Only queueing is protected, never wait. */
    CRITICAL_REGION_ENTER();
    if(!rf_present && !field_seen && !loss_checking && !active) {
        switch(op) {
            case TRACE_WRITE: rc=fds_record_write(desc,record); break;
            case TRACE_UPDATE: rc=fds_record_update(desc,record); break;
            case TRACE_DELETE: rc=fds_record_delete(desc); break;
            case TRACE_GC: rc=fds_gc(); break;
        }
    }
    storage_deferred=rc==TRACE_RF_DEFERRED;
    CRITICAL_REGION_EXIT();
    return rc;
}
static bool prepare_enable(void) {
    fds_done=false; expected_event=FDS_EVT_GC; fds_util_trace_gc(true);
    bool ok=wait_storage(queue_storage(TRACE_GC,NULL,NULL)); fds_util_trace_gc(false);
    if(!ok && !storage_deferred) flags|=FAILED;
    return ok;
}
static void persist_state(bool present) {
    if(!state_dirty || state_blocked || present || field_seen || loss_checking || active || pending || saving) return;
    uint32_t now=app_timer_cnt_get();
    if((flags&FAILED) && app_timer_cnt_diff_compute(now,state_retry_at)<APP_TIMER_TICKS(2000)) return;
    saving=true;
    /* Reclaim old control versions before each update, keeping physical budget bounded. */
    if(!prepare_enable()) { if(!storage_deferred) {failures++; state_retry_at=now;} saving=false; return; }
    control[0]=CONTROL_MAGIC;control[1]=enabled;control[2]=1;
    control[3]=crc_bytes((uint8_t*)control,sizeof(control),12);
    fds_record_desc_t desc;fds_find_token_t tok={0};
    bool exists=fds_record_find(CONTROL_ID,1,&desc,&tok)==NRF_SUCCESS;
    fds_record_t rec={.file_id=CONTROL_ID,.key=1,.data={.p_data=control,.length_words=4}};
    expected_file=CONTROL_ID;expected_key=1;expected_event=exists?FDS_EVT_UPDATE:FDS_EVT_WRITE;fds_done=false;
    uint32_t rc=queue_storage(exists?TRACE_UPDATE:TRACE_WRITE,&desc,&rec);
    if(rc==TRACE_RF_DEFERRED) {saving=false;return;}
    if(wait_storage(rc)) state_dirty=false;
    else {flags|=FAILED;failures++;state_retry_at=now;if(rc==NRF_SUCCESS)state_blocked=true;}
    saving=false;
}
static void process_enable(bool present) {
    if(!enable_requested || present || active || pending || saving) return;
    if(clear_failed || save_blocked) { enable_requested=false; return; }
    saving=true;
    if(prepare_enable()) { enabled=true; feedback=1; state_dirty=true; state_blocked=false; }
    else if(storage_deferred) {saving=false;return;}
    enable_requested=false; saving=false;
}
void access_trace_field(bool present) {
    rf_present=present;
    if(!present) return; // Main loop confirms absence; never finalize from a transient IRQ.
    field_seen=true; loss_checking=false;
    if(active || !enabled || clear_failed || (flags&FULL)) return;
    if(pending || saving) { flags|=OVERFLOW; dropped++; return; }
    uint8_t slot=tag_emulation_get_slot();
    tag_slot_specific_type_t types;
    tag_emulation_get_specific_types_by_slot(slot,&types);
    if(types.tag_hf!=TAG_TYPE_MIFARE_Mini && types.tag_hf!=TAG_TYPE_MIFARE_1024 &&
       types.tag_hf!=TAG_TYPE_MIFARE_2048 && types.tag_hf!=TAG_TYPE_MIFARE_4096) return;
    memset(ram,0,sizeof(ram)); n_events=0; last_tick=app_timer_cnt_get(); session_ticks=0;
    wr32((uint8_t*)ram,next_id); wr16((uint8_t*)ram+8,types.tag_hf);
    ((uint8_t*)ram)[10]=slot; active=true;
}
void access_trace_event(uint8_t kind,uint8_t cmd,uint8_t block,uint8_t key,
                        uint8_t result,uint8_t response,uint8_t ef,
                        const uint8_t *data,uint8_t len) {
    if(!active || (!enabled && kind!=5)) return;
    if(n_events==EVENTS) { flags|=OVERFLOW; ((uint8_t*)ram)[11]|=1; dropped++; return; }
    uint8_t *p=(uint8_t*)ram+32+32*n_events++;
    wr32(p,elapsed()); p[4]=kind; p[5]=cmd; p[6]=block; p[7]=key;
    p[8]=result; p[9]=response; p[10]=len>16?16:len; p[11]=ef;
    if(data && p[10]) memcpy(p+12,data,p[10]);
    wr16((uint8_t*)ram+12,n_events);
}
void access_trace_process(bool present) {
    /* Track RTC wraps even during long field sessions with no new frames. */
    if(active) (void)elapsed();
    /* NFCT field status can briefly drop during activation. Match the existing
       sleep RF guard: no Flash until absence has remained stable for 100 ms. */
    if(present) {
        rf_present=true;loss_checking=false;
        if(!field_seen || (!active && !pending && !saving)) access_trace_field(true);
        return;
    }
    bool quiet=!field_seen && !active;
    CRITICAL_REGION_ENTER();
    rf_present=false;
    if(!quiet) {
        uint32_t now=app_timer_cnt_get();
        if(!loss_checking) { loss_since=now; loss_checking=true; }
        else if(app_timer_cnt_diff_compute(now,loss_since)>=APP_TIMER_TICKS(100)) {
            if(active) {
                access_trace_event(5,0,255,255,5,255,0,NULL,0);
                wr32((uint8_t*)ram+4,elapsed());
                active=false; pending=true;
            }
            field_seen=loss_checking=false;quiet=true;
        }
    }
    CRITICAL_REGION_EXIT();
    if(!quiet) return;
    if(!pending) { process_enable(present); persist_state(present); return; }
    if(present || saving || clear_failed || save_blocked) return;
    uint32_t now=app_timer_cnt_get();
    if((flags&FAILED) && app_timer_cnt_diff_compute(now,retry_at)<APP_TIMER_TICKS(2000)) return;
    saving=true;
    wr32((uint8_t*)ram+16,crc((uint8_t*)ram));
    uint8_t key=1;
    while(key<=SESSIONS && (occupied&(1u<<(key-1)))) key++;
    fds_record_desc_t desc;
    fds_record_t rec={.file_id=FILE_ID,.key=key,.data={.p_data=ram,.length_words=SIZE/4}};
    fds_done=false; expected_event=FDS_EVT_WRITE; expected_key=key; expected_file=FILE_ID;
    uint32_t rc = key<=SESSIONS ? queue_storage(TRACE_WRITE,&desc,&rec) : 1;
    if(rc==TRACE_RF_DEFERRED) {saving=false;return;}
    if(key<=SESSIONS && wait_storage(rc)) {
        occupied|=1u<<(key-1); keys[count++]=key; next_id++;
        pending=false; generation++; if(occupied==127) flags|=FULL;
    } else {
        flags|=FAILED; failures++; retry_at=now;
        /* Accepted writes may leave dirty fragments. Never accumulate retries. */
        if(rc==NRF_SUCCESS) save_blocked=true;
    }
    saving=false;
    process_enable(present); persist_state(present);
}
uint16_t access_trace_command(uint16_t cmd,const uint8_t *data,uint16_t len,
                              uint8_t *out,uint16_t *outlen) {
    *outlen=0;
    if(cmd==1120 || cmd==1121) {
        if(len) return STATUS_PAR_ERR;
        memset(out,0,32); wr16(out,1); wr16(out+2,6);
        if(cmd==1120) {
#if defined(PROJECT_CHAMELEON_ULTRA)
            wr32(out+4,127);
#else
            wr32(out+4,79);
#endif
            wr16(out+8,SIZE); wr16(out+10,32);
            wr16(out+12,SESSIONS); wr16(out+14,EVENTS); *outlen=16;
        } else {
            wr32(out+4,generation); out[8]=enabled;
            out[9]=flags|(rf_present?16:0)|((pending||(loss_checking&&active))?32:0)|(enable_requested?64:0)|(state_dirty?128:0);
            wr16(out+10,count); wr16(out+12,SESSIONS); wr16(out+14,EVENTS);
            wr32(out+16,16384); unsigned used=0;
            for(unsigned i=0;i<SESSIONS;i++) if(occupied&(1u<<i)) used++;
            wr32(out+20,used*(SIZE+12)+(fds_is_exists(CONTROL_ID,1)?28:0)); wr32(out+24,dropped); wr32(out+28,failures); *outlen=32;
        }
        return STATUS_SUCCESS;
    }
    if(cmd==1122) {
        if(len!=1 || data[0]>1) return STATUS_PAR_ERR;
        if(!data[0]) { stop_collection(); state_blocked=false; persist_state(rf_present); return state_dirty && !rf_present && !active && !pending ? STATUS_FLASH_WRITE_FAIL : STATUS_SUCCESS; }
        bool busy;
        CRITICAL_REGION_ENTER();
        busy=rf_present || field_seen || loss_checking || active || pending || saving || enable_requested;
        if(!busy) saving=true;
        CRITICAL_REGION_EXIT();
        if(busy) return STATUS_CMD_ERR;
        if(data[0] && !enabled) {
            if(!prepare_enable()) { saving=false; return storage_deferred ? STATUS_CMD_ERR : STATUS_FLASH_WRITE_FAIL; }
            feedback=1;
        }
        if(!enabled) state_dirty=true;
        enabled=data[0]; state_blocked=false; saving=false; persist_state(rf_present);
        return state_dirty ? STATUS_FLASH_WRITE_FAIL : STATUS_SUCCESS;
    }
    if(cmd==1125) {
        if(len!=5 || memcmp(data,"CLEAR",5)) return STATUS_PAR_ERR;
        bool busy;
        CRITICAL_REGION_ENTER();
        busy=rf_present || field_seen || loss_checking || active || saving;
        if(!busy) saving=true;
        CRITICAL_REGION_EXIT();
        if(busy) return STATUS_CMD_ERR;
        clear_failed=true; generation++;
        for(uint8_t k=1;k<=SESSIONS;k++) {
            fds_find_token_t tok={0}; fds_record_desc_t desc;
            while(fds_record_find(FILE_ID,k,&desc,&tok)==NRF_SUCCESS) {
                fds_done=false; expected_event=FDS_EVT_DEL_RECORD; expected_key=k; expected_file=FILE_ID;
                if(!wait_storage(queue_storage(TRACE_DELETE,&desc,NULL))) { if(!storage_deferred) flags|=FAILED; scan_records(false); saving=false; return storage_deferred?STATUS_CMD_ERR:STATUS_FLASH_WRITE_FAIL; }
            }
        }
        /* Collect deletions before any reuse, bounding physical trace allocation. */
        fds_done=false; expected_event=FDS_EVT_GC;
        fds_util_trace_gc(true);
        bool ok=wait_storage(queue_storage(TRACE_GC,NULL,NULL));
        fds_util_trace_gc(false);
        if(!ok) { if(!storage_deferred) flags|=FAILED; scan_records(false); saving=false; return storage_deferred?STATUS_CMD_ERR:STATUS_FLASH_WRITE_FAIL; }
        count=occupied=flags=0; pending=false; saving=false; clear_failed=save_blocked=false; dropped=failures=0; generation++; next_id=1;
        return STATUS_SUCCESS;
    }
    if(cmd!=1123 && cmd!=1124) return STATUS_INVALID_CMD;
    if(len!=(cmd==1123?7:9)) return STATUS_PAR_ERR;
    if(rd32(data)!=generation) return STATUS_MEM_ERR;
    uint16_t start=rd16(data+(cmd==1123?4:6));
    uint8_t limit=data[len-1], total=count, stride=16;
    if(!limit || limit>(cmd==1123?SESSIONS:31)) return STATUS_PAR_ERR;
    if(cmd==1124) {
        uint16_t index=rd16(data+4);
        if(index>=count) return STATUS_PAR_ERR;
        if(!load(keys[index],(uint8_t*)scratch)) return STATUS_FLASH_READ_FAIL;
        total=rd16((uint8_t*)scratch+12); stride=32;
    }
    if(start>total) return STATUS_PAR_ERR;
    uint8_t n=total-start; if(n>limit) n=limit;
    wr32(out,generation); wr16(out+4,start+n); out[6]=n;
    for(uint8_t i=0;i<n;i++) {
        if(cmd==1123) {
            if(!load(keys[start+i],(uint8_t*)scratch)) return STATUS_FLASH_READ_FAIL;
            memcpy(out+7+i*stride,scratch,16);
        } else memcpy(out+7+i*stride,(uint8_t*)scratch+32+(start+i)*32,32);
    }
    *outlen=7+n*stride; return STATUS_SUCCESS;
}
