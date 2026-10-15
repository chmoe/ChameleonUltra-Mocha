# ChameleonUltra-Mocha

Mocha 1.0.0 是基于最新官方 Chameleon Ultra 固件移植 Mazha 功能的版本。仅针对 **Chameleon Ultra**，保留官方 Ultralight C / 3DES 等功能，沿用 GPLv3 并保留原作者和 SDK 许可证。

## 下载和文档

- [最新 Ultra Application DFU 包：Access Trace v1.6](releases/access-trace-v1.6/mocha-ultra-dfu-app.zip)
- [v1.6 验证记录与 SHA256](releases/access-trace-v1.6/validation.json) / [校验清单](releases/access-trace-v1.6/SHA256SUMS)
- [历史 Mocha 1.0.0 DFU 包](releases/mocha-1.0.0/mocha-ultra-dfu-app.zip)
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

历史 2026-10-12 交付固件源码提交：`11211b3`，设备版本字符串 `Mocha-1.0.0-11211b3`。重建此固件时设置 `MOCHA_SOURCE_REV=11211b3`。

11 组主机回归、DFU application 哈希和 ECDSA 签名校验通过。已进行有限的 PN532 UID/SELECT 测试及刷机前后16槽数据/设置校验；不代表门禁认证或所有读卡器兼容性验证。

[射频冷唤醒延迟对照](docs/rf-wake-delay-20261012.md)：官方关闭动画后也在500–1200ms请求窗口失败、1500ms首次读取3/3成功；Mocha相应结果为0/3及2/3。当前证据不支持认定延迟为Mocha独有，具体根因尚未完全定位。

## Access Trace v1.6（2026-10-15）

新增 Classic 模拟访问记录（命令1120–1125）、按钮动作8及持久采集开关。
RF 通信时收集到有界 RAM，连续无场100ms后保存；Flash 入队前再次检查来场。
最多7会话、每会话31事件，满时停止，物理日志预算保守不超过15600字节。

25项主机测试、Ultra 构建、应用 DFU 哈希及签名验证通过。
已安装实机并核对16槽数据、设置及原有日志保留；开启采集后，只读UID的读卡器实测正常识别。
该读卡器没有进行Classic认证或块读写，因此只产生场离开事件，尚未实测真实块读写采集。
当前未记录防冲突/UID选卡过程，响应生成也不代表门禁放行。

设备版本为 `Mocha-1.0.0-fff0445-access-trace1.6`。
重建对应镜像时设置 `MOCHA_SOURCE_REV=fff0445-access-trace1.6`；这是构建版本标记，
完整实现源码以本次仓库提交为准。包仅含应用，不含Bootloader或SoftDevice。
详见[协议](docs/access-trace-protocol.md)和[容量及验证边界](docs/access-trace-validation.md)。
