#!/usr/bin/env python3
"""Mocha control CLI. GPL-3.0; protocol follows upstream ChameleonUltra.
No card dumps, flashing, or automatic port discovery. Every connection verifies
Mocha identity before any write, including official button and slot commands.
"""
import argparse
import csv
from pathlib import Path
import json
import struct
import sys

IDENTITY = b'Mocha/1;slots=16;base=5c99d4a'
CMD = dict(identity=1100, polling_get=1101, polling_set=1102,
           interval_get=1103, interval_set=1104, reboot_get=1105,
           reboot_set=1106, skip_get=1107, skip_set=1108)


def frame(cmd, data=b''):
    header = struct.pack('!BBHHH', 0x11, 0xef, cmd, 0, len(data))
    return header + bytes([(-sum(header)) & 255]) + data + bytes([(-sum(data)) & 255])


class Device:
    def __init__(self, port):
        import serial
        self.serial = serial.Serial(port, 115200, timeout=3, exclusive=True)
        try:
            if sys.platform == 'darwin':
                import fcntl, termios
                fcntl.ioctl(self.serial.fileno(), termios.TIOCEXCL)
            self.serial.reset_input_buffer()
            if self.q(CMD['identity']) != IDENTITY:
                raise RuntimeError('Firmware identity mismatch; writes refused')
        except BaseException:
            self.serial.close()
            raise

    def close(self):
        self.serial.close()

    def q(self, cmd, data=b''):
        self.serial.write(frame(cmd, data))
        header = self.serial.read(9)
        if len(header) != 9 or header[:2] != b'\x11\xef' or sum(header) & 255:
            raise RuntimeError('Invalid or missing response header')
        response_cmd, status, size = struct.unpack('!HHH', header[2:8])
        if size > 4096:
            raise RuntimeError('Response too large')
        body = self.serial.read(size + 1)
        if len(body) != size + 1 or sum(body) & 255 or response_cmd != cmd:
            raise RuntimeError('Invalid response payload or command')
        if status != 0x68:
            raise RuntimeError(f'Command {cmd} failed: status 0x{status:04x}')
        return body[:-1]


def u16(value):
    return struct.pack('!H', value)


def bounded(low, high):
    def parse(value):
        number = int(value, 0)
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f'Expected {low}..{high}')
        return number
    return parse


def parser():
    p = argparse.ArgumentParser(description='Mocha v1 control; close GUI before connecting')
    p.add_argument('--port', required=True)
    sub = p.add_subparsers(dest='action', required=True)
    sub.add_parser('status')
    x = sub.add_parser('polling'); x.add_argument('value', choices=['on', 'off'])
    x = sub.add_parser('interval'); x.add_argument('ms', type=bounded(100, 5000))
    x = sub.add_parser('skip'); x.add_argument('mask', type=bounded(0, 65535), help='16-bit mask; bit 0=slot 1, e.g. 0x8001 skips 1 and 16')
    x = sub.add_parser('ab-reboot'); x.add_argument('value', choices=['on', 'off'])
    x = sub.add_parser('button'); x.add_argument('button', choices=['a','b']); x.add_argument('press', choices=['short','long']); x.add_argument('function', choices=['disabled','next','previous','clone-uid','battery','field','polling','dfu','access-trace'])
    x = sub.add_parser('select'); x.add_argument('slot', type=bounded(1,16))
    x = sub.add_parser('long-press'); x.add_argument('ms', type=bounded(200,65535))
    sub.add_parser('trace-status')
    x = sub.add_parser('trace'); x.add_argument('value', choices=['on', 'off'])
    x = sub.add_parser('trace-export'); x.add_argument('output'); x.add_argument('--format', choices=['json', 'csv'], default='json')
    x = sub.add_parser('trace-clear'); x.add_argument('--confirm', action='store_true', required=True, help='Explicitly delete all access trace sessions')
    return p


def trace_status(d):
    cap = d.q(1120)
    if len(cap) != 16 or struct.unpack_from('<HH', cap) not in [(1, 0), (1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6)]:
        raise RuntimeError('Unsupported access trace protocol')
    raw = d.q(1121)
    if len(raw) != 32:
        raise RuntimeError('Invalid trace status size')
    values = struct.unpack('<HHIBBHHHIIII', raw)
    return dict(zip(['major', 'minor', 'generation', 'enabled', 'flags', 'sessions',
                     'max_sessions', 'events_per_session', 'physical_budget',
                     'committed_record_bytes', 'dropped_events', 'save_failures'], values))


def trace_export(d):
    status = trace_status(d); generation = status['generation']; sessions = []
    start = 0
    while start < status['sessions']:
        raw = d.q(1123, struct.pack('<IHB', generation, start, min(8, status['max_sessions'])))
        if len(raw) < 7:
            raise RuntimeError('Short trace session page')
        gen, next_index, count = struct.unpack_from('<IHB', raw)
        if gen != generation or not count or next_index != start + count or len(raw) != 7 + count * 16 or next_index > status['sessions']:
            raise RuntimeError('Inconsistent trace session page; retry export')
        for i in range(count):
            vals = struct.unpack_from('<IIHBBHH', raw, 7 + i * 16)
            session = dict(zip(['session_id', 'duration_ms', 'tag_type', 'slot', 'flags', 'event_count', 'reserved'], vals))
            session['events'] = []; sessions.append(session)
        start = next_index
    for index, session in enumerate(sessions):
        start = 0
        while start < session['event_count']:
            raw = d.q(1124, struct.pack('<IHHB', generation, index, start, 31))
            if len(raw) < 7:
                raise RuntimeError('Short trace event page')
            gen, next_index, count = struct.unpack_from('<IHB', raw)
            if gen != generation or not count or next_index != start + count or len(raw) != 7 + count * 32 or next_index > session['event_count']:
                raise RuntimeError('Inconsistent trace event page; retry export')
            for i in range(count):
                vals = struct.unpack_from('<IBBBBBBBB16s4s', raw, 7 + i * 32)
                if vals[7] > 16:
                    raise RuntimeError('Invalid trace data length')
                event = dict(zip(['relative_ms', 'kind', 'command', 'block', 'key', 'result', 'response', 'data_length', 'flags'], vals[:9]))
                event['data'] = vals[9][:event['data_length']].hex()
                session['events'].append(event)
            start = next_index
    if trace_status(d)['generation'] != generation:
        raise RuntimeError('Trace changed during export; retry')
    return dict(protocol=f"Mocha Access Trace {status['major']}.{status['minor']}", status=status, sessions=sessions)


def run(d, a):
    if a.action.startswith('trace'):
        if a.action == 'trace-status': return trace_status(d)
        if a.action == 'trace':
            trace_status(d); d.q(1122, bytes([a.value == 'on'])); return trace_status(d)
        if a.action == 'trace-clear':
            trace_status(d); d.q(1125, b'CLEAR'); return trace_status(d)
        result = trace_export(d)
        destination = Path(a.output)
        if a.format == 'json':
            destination.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
        else:
            fields = ['session_id', 'slot', 'tag_type', 'session_flags', 'duration_ms', 'event_index', 'relative_ms', 'kind', 'command', 'block', 'key', 'result', 'response', 'data_length', 'flags', 'data']
            with destination.open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
                for session in result['sessions']:
                    for index, event in enumerate(session['events']):
                        writer.writerow(dict(session_id=session['session_id'], slot=session['slot'], tag_type=session['tag_type'], session_flags=session['flags'], duration_ms=session['duration_ms'], event_index=index, **event))
        return dict(output=str(destination.resolve()), sessions=len(result['sessions']))
    if a.action == 'status':
        info = d.q(1019); enabled = d.q(1023)
        if len(info) != 64 or len(enabled) != 32:
            raise RuntimeError('Mocha 16-slot response size mismatch')
        mask = int.from_bytes(d.q(CMD['skip_get']), 'big')
        return dict(identity=IDENTITY.decode(), version=d.q(1017).decode(),
                    polling=bool(d.q(CMD['polling_get'])[0]),
                    interval_ms=int.from_bytes(d.q(CMD['interval_get']), 'big'),
                    ab_reboot=bool(d.q(CMD['reboot_get'])[0]),
                    long_press_ms=int.from_bytes(d.q(1041), 'big'),
                    active_slot=d.q(1018)[0]+1,
                    slots=[dict(slot=i+1, hf_type=int.from_bytes(info[i*4:i*4+2], 'big'),
                                lf_type=int.from_bytes(info[i*4+2:i*4+4], 'big'),
                                hf_enabled=bool(enabled[i*2]), lf_enabled=bool(enabled[i*2+1]),
                                polling_skip=bool(mask & (1<<i))) for i in range(16)])
    elif a.action == 'polling': d.q(CMD['polling_set'], bytes([a.value == 'on']))
    elif a.action == 'interval': d.q(CMD['interval_set'], u16(a.ms))
    elif a.action == 'skip': d.q(CMD['skip_set'], u16(a.mask))
    elif a.action == 'ab-reboot': d.q(CMD['reboot_set'], bytes([a.value == 'on']))
    elif a.action == 'select': d.q(1003, bytes([a.slot-1])); d.q(1009)
    elif a.action == 'long-press': d.q(1042, u16(a.ms)); d.q(1013)
    elif a.action == 'button':
        functions = ['disabled','next','previous','clone-uid','battery','field','polling','dfu','access-trace']
        if a.function == 'access-trace':
            capability = d.q(1120)
            if len(capability) != 16 or struct.unpack_from('<H', capability)[0] != 1 or not struct.unpack_from('<I', capability, 4)[0] & 16:
                raise RuntimeError('Firmware does not support access-trace button action')
        d.q(1027 if a.press == 'short' else 1029, bytes([ord(a.button), functions.index(a.function)]))
        d.q(1013)
    return {'saved': a.action}


def main():
    a = parser().parse_args()
    device = None
    try:
        device = Device(a.port)
        print(json.dumps(run(device, a), indent=2, ensure_ascii=False))
    except (OSError, RuntimeError, ImportError) as error:
        print(f'Mocha: {error}', file=sys.stderr)
        return 1
    finally:
        if device: device.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
