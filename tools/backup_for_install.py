#!/usr/bin/env python3
"""Back up/compare exposed slot data. Temporary slot changes are restored."""
import argparse, json, hashlib
from pathlib import Path
from types import SimpleNamespace
import mocha

def capture(device):
    status=mocha.run(device,SimpleNamespace(action='status'))
    if status['polling']: raise RuntimeError('Pause polling before backup')
    if device.q(1002)!=b'\x00': raise RuntimeError('Expected tag emulation mode')
    original=status['active_slot']-1
    result={'status':status,'global':{},'slots':[]}
    def read(cmd,p=b''):
        try:return {'cmd':cmd,'request':p.hex(),'data':device.q(cmd,p).hex()}
        except RuntimeError as e:
            if 'status 0x0071' in str(e) or 'status 0x0072' in str(e):
                return {'cmd':cmd,'request':p.hex(),'error':str(e)}
            raise
    try:
        for cmd in [1034,1039,1041,1103,1105,1107]:result['global'][str(cmd)]=read(cmd)
        for slot in status['slots']:
            index=slot['slot']-1; item={'slot':slot['slot'],'reads':[]}
            for sense in [1,2]:item['reads'].append(read(1008,bytes([index,sense])))
            if slot['hf_type'] or slot['lf_type']:
                device.q(1003,bytes([index]));assert device.q(1018)==bytes([index])
                typ=slot['hf_type']
                if typ in [1000,1001,1002,1003]:
                    blocks={1000:20,1001:64,1002:128,1003:256}[typ]
                    for start in range(0,blocks,32):item['reads'].append(read(4008,bytes([start,min(32,blocks-start)])))
                    for cmd in [4009,4018,4040,4039]:item['reads'].append(read(cmd))
                elif typ in [1100,1101,1102]:
                    pages=device.q(4030)[0];item['reads'].append({'cmd':4030,'request':'','data':bytes([pages]).hex()})
                    for start in range(0,pages,32):item['reads'].append(read(4021,bytes([start,min(32,pages-start)])))
                    for cmd in [4018,4023,4025,4037]:item['reads'].append(read(cmd))
                    for ctr in [0,1,2]:item['reads'].append(read(4027,bytes([ctr])))
                elif typ:raise RuntimeError('Unsupported backup HF type '+str(typ))
                if slot['lf_type']==100:item['reads'].append(read(5001))
                elif slot['lf_type']:raise RuntimeError('Unsupported backup LF type')
            result['slots'].append(item)
    finally:
        device.q(1003,bytes([original]));assert device.q(1018)==bytes([original])
    assert device.q(1101)==b'\x00'
    return result

def main():
    a=argparse.ArgumentParser();a.add_argument('--port',required=True);a.add_argument('--output',required=True);a.add_argument('--compare');args=a.parse_args()
    d=mocha.Device(args.port)
    try:result=capture(d)
    finally:d.close()
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True);path.parent.chmod(0o700)
    path.write_text(json.dumps(result,indent=2)+'\n');path.chmod(0o600)
    if args.compare:
        before=json.loads(Path(args.compare).read_text());after=json.loads(path.read_text())
        before['status'].pop('version');after['status'].pop('version')
        if before!=after:raise RuntimeError('Device backup comparison failed; retain backup and inspect difference')
    print(json.dumps({'backup':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'slots':len(result['slots']),'active_slot_restored':result['status']['active_slot'],'compare':'matched' if args.compare else 'not requested'}))
if __name__=='__main__':main()
