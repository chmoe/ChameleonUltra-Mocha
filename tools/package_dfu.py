#!/usr/bin/env python3
"""Application-only package using Nordic's nrfutil 6.1.7 API, no BLE driver."""
from pathlib import Path
from nordicsemi.dfu.package import Package
from nordicsemi.dfu.signing import Signing
root=Path(__file__).resolve().parents[1]
signer=Signing(); signer.load_key(str(root/'resource/dfu_key/chameleon.pem'))
(root/'dist').mkdir(exist_ok=True)
Package(debug_mode=False, hw_version=0, app_version=1, sd_req=[0x100], sd_id=[0x100],
        app_fw=str(root/'firmware/objects/application.hex'), signer=signer).generate_package(str(root/'dist/mocha-ultra-dfu-app.zip'))
print('Created dist/mocha-ultra-dfu-app.zip')
