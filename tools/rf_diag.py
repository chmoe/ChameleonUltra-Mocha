#!/usr/bin/env python3
"""Read cold-wake RF events without changing slots, sensing, or card data."""
import argparse
import json
import struct
from pathlib import Path
from mocha import Device

KINDS = dict(enumerate(['field_on', 'field_off', 'rx', 'tx_start', 'tx_end',
                       'timeout', 'ready', 'sense_on', 'sense_off', 'tx_request', 'rearm'], 1))

def decode(raw):
    if len(raw) < 16:
        raise ValueError('Short RF header')
    version, first, end, count = struct.unpack_from('<4I', raw)
    if version != 1 or count > 8 or len(raw) != 16 + count * 32 or first > end:
        raise ValueError('Invalid RF log page')
    events = []
    for i in range(count):
        seq, ticks, kind, slot, state, hw, bits, captured, data = struct.unpack_from(
            '<IIBBBBHH16s', raw, 16 + i * 32)
        if captured > 16 or not first <= seq < end:
            raise ValueError('Invalid RF event')
        prefix = data[:captured]
        event = dict(sequence=seq, rtc_ticks=ticks, kind=KINDS.get(kind, str(kind)),
                     slot=slot + 1, state=state, hardware=hw, bits=bits, data=prefix.hex())
        if kind == 3 and bits >= 16 and len(prefix) >= 2:
            if prefix[0] == 0x30:
                event['read_pages'] = [prefix[1], prefix[1] + 3]
            elif prefix[0] == 0x3a and bits >= 24 and len(prefix) >= 3:
                event['fast_read_pages'] = [prefix[1], prefix[2]]
        events.append(event)
    if any(b['sequence'] != a['sequence'] + 1 for a, b in zip(events, events[1:])):
        raise ValueError('Noncontiguous RF log page')
    return first, end, events

def capture(device):
    result = {'version': device.q(1017).decode(),
              'startup': list(struct.unpack('!9I', device.q(1110))),
              'diagnostics': list(struct.unpack('!12I', device.q(1109))), 'events': []}
    cursor = 0
    target = None
    for _ in range(64):
        first, end, events = decode(device.q(1111, struct.pack('<IB', cursor, 8)))
        if target is None:
            target = end
            result.update(first_available=first, snapshot_end=end, overwritten_before_read=first)
        if first > max(cursor, result['first_available']):
            raise RuntimeError('RF log overwritten during export; move phone away and retry')
        kept = [e for e in events if e['sequence'] < target]
        result['events'].extend(kept)
        if not kept or kept[-1]['sequence'] + 1 >= target:
            return result
        cursor = kept[-1]['sequence'] + 1
    raise RuntimeError('RF export did not converge')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    device = Device(args.port)
    try:
        result = capture(device)
    finally:
        device.close()
    Path(args.output).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'events': len(result['events']), 'output': args.output,
                      'timeouts': sum(e['kind'] == 'timeout' for e in result['events'])}))
