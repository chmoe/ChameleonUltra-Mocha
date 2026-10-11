#!/usr/bin/env python3
"""Mocha control CLI. GPL-3.0; protocol follows upstream ChameleonUltra.
No card dumps, flashing, or automatic port discovery. Every connection verifies
Mocha identity before any write, including official button and slot commands.
"""
import argparse
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
    x = sub.add_parser('button'); x.add_argument('button', choices=['a','b']); x.add_argument('press', choices=['short','long']); x.add_argument('function', choices=['disabled','next','previous','clone-uid','battery','field','polling','dfu'])
    x = sub.add_parser('select'); x.add_argument('slot', type=bounded(1,16))
    x = sub.add_parser('long-press'); x.add_argument('ms', type=bounded(200,65535))
    return p


def run(d, a):
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
        functions = ['disabled','next','previous','clone-uid','battery','field','polling','dfu']
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
