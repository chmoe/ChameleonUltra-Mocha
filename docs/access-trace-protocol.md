# Mocha Access Trace protocol v1.6 (2026-10-15)

Status: implementation contract. v1.3 reduces capacity to seven sessions to count
the entire 8 KiB FDS swap page within the 16 KiB physical budget. v1.2 adds GC before enabling and stops retrying
a flash write that was accepted but failed, to bound dirty fragments. v1.1 clarified failed-clear inhibition, permits
clear to discard pending unsaved RAM, and explicitly uses application CRC32
without enabling SDK CRC checks on legacy records. Layout/commands unchanged. Existing Chameleon frame header remains big endian;
ALL trace payload integers are little endian. Commands 1120–1125 are new, listed
by GET_DEVICE_CAPABILITIES (1035). Old firmware returns 0x67 INVALID_CMD.
Only MIFARE Classic emulation is supported. Recording defaults OFF when no saved switch exists; a valid saved switch is
restored after standby/reset. Saved sessions remain readable while disabled.

| Command | Request | Success payload |
|---|---|---|
|1120 capabilities|empty|u16 major=1, u16 minor=6, u32 features=127 (Ultra), u16 session_size=1024, u16 event_size=32, u16 max_sessions=7, u16 max_events=31|
|1121 status|empty|32 bytes described below|
|1122 enable|u8 0/1|empty|
|1123 session page|u32 generation, u16 start, u8 limit 1..7|u32 generation, u16 next, u8 count, then count × 16-byte summaries|
|1124 event page|u32 generation, u16 session_index, u16 start, u8 limit 1..31|u32 generation, u16 next, u8 count, then count × 32-byte events|
|1125 clear|ASCII `CLEAR`|empty; deletes trace records only|

Status layout: u16 major, u16 minor, u32 generation, u8 enabled, u8 flags,
u16 committed_sessions, u16 max_sessions, u16 events_per_session,
u32 physical_budget=16384, u32 committed_record_bytes (includes FDS headers),
u32 dropped_events, u32 save_failures.
Flags: bit0 full, bit1 RAM overflow, bit2 save failure, bit3 recovered invalid
record, bit4 RF active, bit5 pending save, bit6 button enable request waiting for RF/save, bit7 switch not yet durable. Sticky flags/counters reset by explicit
clear (except full recomputed). Overflow/drop counters can be lost on reset;
session overflow flag persists. Features bits: 0 Classic, 1 plaintext, 2 persistence,
3 generation pagination, 4 button toggle action, 5 deferred button enable / safe stop, 6 persistent switch. No wall clock or guaranteed retention across DFU.

Summary layout: u32 session_id, u32 duration_ms, u16 tag_type, u8 slot (0..15),
u8 flags (bit0 truncated), u16 event_count, u16 reserved=0.
Event layout (32 bytes): u32 relative_ms, u8 kind, u8 command, u8 block,
u8 key (0=A,1=B,255=none), u8 result, u8 response, u8 data_length (0..16),
u8 flags, u8 data[16], u8 reserved[4]=0.
Kinds: 1 request, 2 response, 3 auth result, 4 write data, 5 session end.
Results: 0 requested/pending, 1 response generated or operation completed,
2 rejected, 3 malformed/CRC error, 4 auth failed, 5 field left.
Response is the plaintext ACK/NAK nibble when applicable; 255=none.
Event flags: bit0 nested auth, bit1 Gen1a, bit2 write deceive, bit3 write shadow.
Read response bytes are captured after access-condition masking, before Crypto1
and CRC. Write data is captured after decrypt, before trailer field restoration.
Authentication target block is NOT a read block. Response generation does NOT
prove delivery or access granted. Session end is RF disappearance, not door result.

Errors: 0x60 bad payload/index/limit; 0x75 busy (enable-on during RF/pending save; clear during RF or save),
0x73 stale generation; 0x70 storage failure; 0x71 invalid stored session;
0x68 success. Empty end pages return count=0 and next=start. Request start must
be <= current count. Each page echoes generation; on 0x73 restart from status.
Only committed valid sessions are exposed. Save and clear change generation;
RAM activity does not. Reconnect/reset requires a new status and full read.

Examples (payload hex, outer command/status frame omitted): enable 1122 `01`;
status generation=0x12345678 then session page 1123 `78 56 34 12 00 00 07`;
event page for session 0 from event 0 limit 10: 1124
`78 56 34 12 00 00 00 00 0a`; clear 1125 `43 4c 45 41 52`.

Storage: seven immutable 1024-byte FDS session records (12-byte FDS header each),
31 events/session. No rolling overwrite. Corrupt records consume capacity until
clear; no automatic deletion. One bounded RAM session; if another RF session
arrives before save completes it is skipped and overflow reported. At full,
new recording stops while saved data stays readable. Field callbacks only mutate
RAM; main loop saves after field leaves and inhibits standby until done.
Application CRC32 (SDK FDS CRC checking remains disabled for legacy compatibility) validates full records at boot/read. Reset during
an unsaved session loses that RAM session. Flash failure keeps pending RAM and
blocks standby. Enqueue failures retry after 2 seconds; an accepted write with a
failed completion stops retrying until explicit clear. Enabling after boot/disable
runs normal FDS GC before collecting, reclaiming interrupted fragments; no implicit discard.
A failed clear inhibits new recording/saving until clear succeeds; restart pagination
after any clear attempt, including failure. See access-trace-validation.md for Flash accounting and validation limits.


## v1.4 button action and LED feedback (2026-10-14)

Ultra advertises `features & 0x10` (button action) and `features & 0x20`
(deferred enable / safe stop) in command 1120. Payload stays 16 bytes; major=1,
minor=4. Software MUST detect command 1120, major=1, and button capability bit4;
Mocha identity/name alone does not establish support. Lite does not advertise
these two bits and rejects configuring this action. Do not assume max action
from firmware name. GET_DEVICE_CAPABILITIES also lists 1120–1125.

Action **8 = Toggle access recording** uses the existing button configuration:
1027 set short action `[ASCII A/B, action]`; 1029 set long action, same payload;
1026/1028 read short/long action with `[ASCII A/B]`; 1013 saves settings.
Example: long B toggle: 1029 payload `42 08`, then 1013 empty. Read back via
1028 `42` -> `08`. Short A toggle: 1027 `41 08`, then 1013. Either A or B,
short or long, toggles the SAME independent recording switch; this is NOT
an A+B chord. Existing A+B reboot and existing button mappings/defaults remain.
Long press threshold uses existing 1041/1042 interface. Mappings persist;
recording itself is persisted since v1.5 (default OFF on migration).

Button action is accepted in emulation mode with field generator off. Turning ON
queues an enable request; status bit6 remains set while RF or a previous session
save prevents safe GC. A second button press cancels an enable request. Actual
`enabled` remains 0 until safe GC succeeds. Failure leaves enabled=0 and flags
save-failure; no misleading ON sweep is emitted. Turning OFF takes effect
immediately even during RF: stop collecting new access events, keep current
bounded RAM and append session-end when RF leaves. Session summary flag bit1
means collection was stopped manually. Save only after RF leaves, per original
policy; stop/turn-off never clears existing sessions or discards pending RAM.
Command 1122 OFF gains the same safe-stop behavior and cancels queued enable;
ON still returns busy during RF/pending work. Software must display actual
`enabled` and pending bit6 separately. RF/pending save/queued enable inhibit
battery standby until the existing safe-save/enable policy resolves them.

After each successful actual switch change (button or 1122), play ONE feedback
sweep: ON left-to-right, OFF right-to-left, 80 ms per LED (640 ms total).
The front numbered LED face defines left = LED1, right = LED8, in existing
`hw_get_led_array()[0..7]` order. Do not substitute GPIO-number sorting or
slot 9–16 order. OFF traverses the same eight physical LED/color pairs reversed.

|Physical LED left-to-right|Color|RGB intensities (0..255)|
|---|---|---|
|1|red|255,0,0|
|2|orange|255,64,0|
|3|yellow|255,255,0|
|4|green|0,255,0|
|5|cyan|0,255,255|
|6|blue|0,0,255|
|7|magenta|255,0,255|
|8|white|255,255,255|

RGB PWM distinguishes orange from yellow; all eight colors are different.
Only one numbered LED is lit at a time. No delays or waiting loops implement
this sweep. RF preempts/pauses feedback; it resumes when the field leaves.
Other foreground LED actions may cancel an in-progress sweep. USB animation
is suspended only while feedback owns LEDs, then normal slot/USB rendering
resumes. No sweep starts for an unchanged state, canceled pending ON, unsupported
mode, or failed enable. Color ratios and physical direction still require visual
verification on hardware; GPIO/PWM order and transitions are host-tested.


## v1.5 persistent recording switch

1120 returns major=1, minor=5, features=127 on Ultra (bit6=64 means persistent
switch); existing command/payload sizes remain unchanged. Status flags bit7=128
means current enabled state has not yet been saved. FAILED/save_failures report
storage failures. Actual enabled may differ from last durable state while bit7
is set; an immediate power loss can restore the previous durable state.

Store one independent 16-byte CRC32-protected FDS control record, file 0x1301
key1, outside card/settings/log records. Default OFF only when absent or invalid.
Restore saved ON/OFF on standby wake, reset and ordinary power cycle; no startup
sweep or startup GC is required. Missing/old v1.4 state migrates to OFF, without
changing existing card data/button mappings. Corrupt control record reports
CORRUPT and defaults OFF. DFU retention remains subject to the documented layout
and backup limits. Logs CLEAR deletes only sessions, preserving the switch.

All switch writes and GC occur in main context, after RF and session save.
1122 in idle saves the switch before success; a storage failure returns 0x70.
OFF during RF updates RAM immediately, returns success with status bit7 set,
then saves after field loss; it never writes Flash during active RF. Buttons use
the same deferred persistence policy. Standby is inhibited while bit7 remains.
Accepted-write completion failure stops automatic retries; a subsequent explicit
switch command can retry. Enqueue/GC errors retry at 2-second intervals.
Control adds up to two 28-byte FDS versions plus page tags; conservative total
physical attribution is <=15600 bytes, still below the 16384-byte limit.


## v1.6 stable RF departure before Flash (2026-10-15)

Payload sizes, capability bits (Ultra 127), capacity and storage formats are
unchanged; protocol minor=6. Neither a single absent field-status sample nor a
FIELD_LOST callback authorizes immediate Flash writing. Main loop requires
continuous absence for 100 ms; a returned field cancels that candidate and
continues the same RAM session without an extra end event. Only then append
session-end and save. Session duration/end timestamp includes this confirmation
window. Status bit5 also covers an active session awaiting absence confirmation.
A present main-loop sample repairs a missed FIELD_DETECTED callback and can
start an eligible Classic session. No recording/read/card/polling settings are
automatically changed by this fix. RF-present checks gate switch persistence
as well. This fix does not guarantee reader acceptance or supported card data.

Every trace-related Flash enqueue (session/control writes, deletes and GC) also
rechecks RF and session state in a short critical section immediately before the
SDK call. A returning field defers the pending operation without reporting a
storage failure. Flash operations already queued cannot be canceled when a new
field arrives later; real reader timing still requires hardware verification.
