#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
: "${GNU_INSTALL_ROOT:?Set GNU_INSTALL_ROOT to ARM GNU 12.2.rel1 bin directory with trailing slash}"
PYTHON=${PYTHON:-python3}
MOCHA_SOURCE_REV=${MOCHA_SOURCE_REV:-$(git rev-parse --short=7 HEAD)}
mkdir -p dist
make -C firmware/application clean GNU_INSTALL_ROOT="$GNU_INSTALL_ROOT" APP_FW_VER_MAJOR=2 APP_FW_VER_MINOR=2 GIT_VERSION="Mocha-1.0.0-${MOCHA_SOURCE_REV}"
make -C firmware/application -j8 GNU_INSTALL_ROOT="$GNU_INSTALL_ROOT" APP_FW_VER_MAJOR=2 APP_FW_VER_MINOR=2 CURRENT_DEVICE_TYPE=ultra GIT_VERSION="Mocha-1.0.0-${MOCHA_SOURCE_REV}"
"$PYTHON" tests/test_host.py
"$PYTHON" tools/package_dfu.py
"$PYTHON" tools/verify_dfu.py
cp firmware/objects/application.hex dist/mocha-application.hex
cp firmware/objects/application.bin dist/mocha-application.bin
cp firmware/objects/application.out dist/mocha-application.elf
