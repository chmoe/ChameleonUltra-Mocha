# ChameleonUltra-Mocha

Mocha 1.0.0 是基于最新官方 Chameleon Ultra 固件移植 Mazha 功能的版本。仅针对 **Chameleon Ultra**，保留官方 Ultralight C / 3DES 等功能，沿用 GPLv3 并保留原作者和 SDK 许可证。

## 下载和文档

- [Ultra Application DFU 包](releases/mocha-1.0.0/mocha-ultra-dfu-app.zip)
- [使用说明、协议、配置迁移与验证边界](README_MOCHA.md)
- [完整构建源码归档](releases/mocha-1.0.0/mocha-source.tar.gz)
- [相对官方的补丁](releases/mocha-1.0.0/mocha-from-official.patch)
- [构建记录](releases/mocha-1.0.0/build-info.json) / [SHA256 校验清单](releases/mocha-1.0.0/SHA256SUMS)
- [Mocha 控制工具](tools/mocha.py) / [可复现构建脚本](tools/build_mocha.sh)

## 功能

- 16 槽映射到 8 颗灯，9–16 槽使用混色；统一 USB、切槽灯位和颜色，修复共享 PWM 动画争用。
- 场触发轮询，100–5000ms 持久化间隔，每槽跳过位；HF 场离开后恢复原槽。
- 按键开关轮询、进入 DFU，可配置 A+B 重启。
- 保留官方 1041/1042 长按阈值；Mocha 扩展使用 1100–1108，控制工具写入前验证固件身份。
- 官方 v8 槽配置和 Mazha v9 槽配置迁移到 Mocha v10；设置保留长按阈值与独立轮询间隔。

## 固定来源和验证

官方基线：[`5c99d4a39b424cc67ae82bbcfc8ba5ec8f69bf9c`](https://github.com/RfidResearchGroup/ChameleonUltra/commit/5c99d4a39b424cc67ae82bbcfc8ba5ec8f69bf9c)。

Mazha 参考：[`1f44d9a4c66258f2ef16cb90b5262a9d30b0ad98`](https://github.com/Mazha0309/ChameleonUltra-mazha0309/commit/1f44d9a4c66258f2ef16cb90b5262a9d30b0ad98)。

交付固件的构建源码提交：`1fca33a65cd6e0054dbad4f400e6561aff8d622a`。之后的仓库整理提交只调整展示文档、归档上游 CI 并保存构建产物。重建此已交付固件时设置 `MOCHA_SOURCE_REV=1fca33a`。

6 组主机测试、DFU application 哈希和 ECDSA 签名验证通过。独立解压源码归档后重建，BIN 逐字节一致。**尚未刷写设备或进行新固件的实机射频、灯光和断电恢复测试。**

HF 最终 SELECT/ACTIVE 后保持当前槽直到场消失，避免切断认证/读写；这不是门禁成功检测。官方和 Mazha v7 设置无法可靠自动区分，采用保守迁移，详见说明。

## 仓库布局

`firmware/`、`software/`、`hardware/`、`resource/` 为完整源码；`tools/` 为 Mocha 构建与控制工具；`tests/` 为主机模拟；`releases/mocha-1.0.0/` 保存本次构建快照。上游自动发布工作流保存在 `.github/upstream-workflows/`，不在新仓库自动执行。

[上游 README](README_UPSTREAM.md) / [原作者](AUTHORS.md) / [GPLv3](LICENSE)。Nordic SDK 和其他第三方内容保留各自许可证。
