#!/usr/bin/env python3
"""Validate signed application-only Nordic DFU package without a device."""
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from nordicsemi.dfu.init_packet_pb import InitPacketPB
from nordicsemi.dfu.signing import Signing

root = Path(__file__).resolve().parents[1]
path = Path(sys.argv[1]) if len(sys.argv)>1 else root/'dist/mocha-ultra-dfu-app.zip'
with zipfile.ZipFile(path) as z:
    assert z.testzip() is None
    manifest=json.loads(z.read('manifest.json'))['manifest']
    assert set(manifest)=={'application'}, 'must not include bootloader or SoftDevice'
    entry=manifest['application']; binary=z.read(entry['bin_file']); packet=InitPacketPB(from_bytes=z.read(entry['dat_file']))
    init=packet.packet.signed_command.command.init
    assert init.hw_version==0 and list(init.sd_req)==[0x100]
    assert init.fw_version==1 and init.app_size==len(binary)
    assert init.sd_size==0 and init.bl_size==0 and not init.is_debug
    assert init.hash.hash==hashlib.sha256(binary).digest()[::-1]
    signature=packet.packet.signed_command.signature
    signer=Signing(); signer.load_key(str(root/'resource/dfu_key/chameleon.pem'))
    assert signer.verify(packet.get_init_command_bytes(),signature[31::-1]+signature[63:31:-1]), 'ECDSA signature mismatch'
    assert b'Mocha-1.0.0-' in binary and b'Mocha/1;slots=16;base=5c99d4a' in binary
    print(json.dumps({'package':path.name,'type':'application','hw_version':0,'sd_req':'0x0100','application_size':len(binary),'signature':'ECDSA P-256/SHA-256 verified','sha256':hashlib.sha256(path.read_bytes()).hexdigest()},indent=2))
