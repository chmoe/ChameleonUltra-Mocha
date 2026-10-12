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

交付固件源码提交：`11211b3`，设备版本字符串 `Mocha-1.0.0-11211b3`。重建此固件时设置 `MOCHA_SOURCE_REV=11211b3`。

11 组主机回归、DFU application 哈希和 ECDSA 签名校验通过。已进行有限的 PN532 UID/SELECT 测试及刷机前后16槽数据/设置校验；不代表门禁认证或所有读卡器兼容性验证。

[射频冷唤醒延迟对照](docs/rf-wake-delay-20261012.md)：官方关闭动画后也在500–1200ms请求窗口失败、1500ms首次读取3/3成功；Mocha相应结果为0/3及2/3。当前证据不支持认定延迟为Mocha独有，具体根因尚未完全定位。
