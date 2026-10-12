# Mocha 1.0.0 — Chameleon Ultra

这是可构建的官方最新固件移植版本，保留官方 Ultralight C / 3DES、SEOS 和新 LF 协议源码。只为 **Ultra** 构建；本次构建未刷入设备、未访问串口、未写卡数据。

## 固定来源与许可证

- 官方基线：`5c99d4a39b424cc67ae82bbcfc8ba5ec8f69bf9c`，2026-10-11 通过官方 main fetch 核对。
- [官方仓库](https://github.com/RfidResearchGroup/ChameleonUltra)。
- Mazha 参考：`1f44d9a4c66258f2ef16cb90b5262a9d30b0ad98`，通过其 main 的 ls-remote 核对。
- [Mazha 来源](https://github.com/Mazha0309/ChameleonUltra-mazha0309)，自定义改动起点 `1c9e8e8`，017 发布包提交 `6268247`。
- 分支 `codex/mocha`。保留原 AUTHORS、GPLv3 LICENSE、Nordic SDK 和第三方许可证。Mocha 改动及控制工具按 GPLv3 提供；SDK 等仍遵守各自许可证。
- `releases/mocha-1.0.0/build-info.json` 记录最终源码提交、工具版本和产物校验和。`releases/mocha-1.0.0/mocha-source.tar.gz` 为对应源码，`releases/mocha-1.0.0/mocha-from-official.patch` 为相对固定官方基线的补丁。

## 功能和实际行为

- 16 个槽；9–16 初始禁用，保留 1–8 的配置和独立卡数据记录 ID。16 槽返回已扩展；附带原 CLI 的槽枚举和名称解析也支持 16 槽。官方 GUI 仍可能只显示 8 槽。
- 8 颗灯：灯位为 `(slot-1) % 8`；1–8 的双频/HF/LF 为红/绿/蓝，9–16 对应黄/青/品红。USB、开关机、切槽统一灯位和显示色。
- 轮询默认关闭；启用、间隔 100–5000ms、跳过掩码、A+B 重启开关均可持久化。
- 仅模拟模式轮询。场到达时记录原槽并重新开始间隔计时；场离开后恢复原槽。手动切槽取消旧会话；关闭轮询或转读卡模式会结束会话并保留当前槽。
- HF 使用 Nordic NFCT 的 presence/lock 场状态，不再以 500ms 无帧推断离开。最近 50ms 有 HF 帧时推迟切换；最终 SELECT 或进入 ACTIVE/PROPRIETARY 后锁定当前槽，直到场消失。检查与关闭 NFCT 放在短临界区，避免 SELECT 与切槽检查之间的竞争。
- **SELECT/ACTIVE 不是门禁放行信号**：即使认证或门禁判断失败，本次持续场也保持该槽；移开再贴会重新开始。不存在可靠的“刷卡成功后锁定”检测。
- LF 使用模拟模块在停止调制、排空后采样的读头存在状态。轮询请求等待完整的有限广播 burst 结束，之后才切换；实际切换间隔可能大于设置值。没有 LF 读头成功反馈。
- 候选槽必须启用当前会话的感应类型，且没有跳过位：HF 会话不会切到纯 LF 槽，LF 会话不会切到纯 HF 槽。初始槽未启用某感应类型时不会通过该模块启动该类型的会话。并发 HF 场会阻止 LF 轮询，防止切断 HF 事务。
- RF 轮询用即时灯位反馈，避免阻塞扫灯；手动切槽保留淡出旧槽颜色、淡入新槽颜色。所有槽反馈先停止共享 PWM，并重置 USB 状态机；USB 重启时重置本地步序。没有启用高半区闪烁计时器。
- BLE 连接本身不启动 USB 跑马灯。USB 供电且串口关闭为充电动画；串口打开为 80ms 扫灯或 100ms 对称动画。保留官方按键/HF 活动抑制 USB 动画的规则。
- 按键动作 6 为开关轮询，7 为进入 DFU；A+B 长按后释放其中一键可重启，阈值仍使用官方长按阈值。双键重启保存/重启在主循环执行，避免在 timer callback 写 flash。默认 A+B 重启开启；已有短/长按映射不改变。

## 配置迁移

Mocha 设置存储 schema 为 `0x4D01`，16 字节：保留官方位置的长按阈值，使用原尾部空间新增独立轮询间隔。官方 GET_DEVICE_SETTINGS 的 wire 版本/布局仍为 7；Mocha 身份通过独立命令读取。

- 官方 v1–v6 按原迁移步骤处理，再初始化 Mocha 设置；官方 v7 保留长按阈值，新轮询默认关闭、500ms。
- Mazha v8（16 字节）可识别：轮询间隔、启用位、双键重启位保留；长按阈值初始化为官方默认 1000ms，无效间隔回退 500ms。
- **Mazha v7 与官方 v7 同版本/同长度，无法可靠自动区分**；即使存在槽 v9，也可能是刷回官方后遗留。保守按官方 v7 解释，保留原字段为长按阈值，轮询关闭。已知来自 Mazha v7 时，用户需用 `interval` 恢复原间隔、`long-press 1000` 恢复官方阈值，再按需 `polling on`。不会根据数值猜来源并自动启用轮询。
- 槽配置 Mocha v10/132 字节：官方 v8/68 字节扩展后将 9–16 清零，并将旧保留位解释为不跳过；Mazha v9/132 字节保留全部槽与 skip 位。原注释虽称 v10，Mazha 实际使用 v9，Mocha 明确升级至 v10。
- 不修改各槽 dump/nickname 的已有 ID。修复 `fds_read_sync` 成功路径未关闭 record 的问题。
- 刷回官方不保证理解扩展设置/槽配置；恢复必须使用备份和对应固件工具。此包不含迁移或覆盖卡数据的外部脚本。

## 控制工具

Python + `pyserial==3.5`。先关闭官方 GUI 和其他串口客户端。工具需要显式指定端口，在每次连接后先读取命令 1100 严格匹配 Mocha v1 身份，失败时拒绝任何写操作。macOS 使用 TIOCEXCL 防止后续串口争用。以下是用法示例，本次未执行设备操作：

```sh
python tools/mocha.py --port /dev/cu.usbmodemYOUR_DEVICE status
python tools/mocha.py --port /dev/cu.usbmodemYOUR_DEVICE interval 500
python tools/mocha.py --port /dev/cu.usbmodemYOUR_DEVICE skip 0x8001  # 跳过槽1、16
python tools/mocha.py --port /dev/cu.usbmodemYOUR_DEVICE polling on
python tools/mocha.py --port /dev/cu.usbmodemYOUR_DEVICE button a long polling
python tools/mocha.py --port /dev/cu.usbmodemYOUR_DEVICE button b long dfu
python tools/mocha.py --port /dev/cu.usbmodemYOUR_DEVICE ab-reboot off
python tools/mocha.py --port /dev/cu.usbmodemYOUR_DEVICE select 16
```

| 编号 | Mocha 操作 | 数据 |
|---|---|---|
|1100|身份|返回 ASCII `Mocha/1;slots=16;base=5c99d4a`|
|1101 / 1102|读/写轮询开关|1字节 0/1|
|1103 / 1104|读/写间隔|2字节大端，100–5000|
|1105 / 1106|读/写双键重启|1字节 0/1|
|1107 / 1108|读/写跳过位|2字节大端；bit0=槽1|

官方 1041/1042 保持长按阈值读/写。工具的 `polling` 只使用 1102；仅显式 `long-press` 子命令会写官方 1042。

## 构建与验证（不连接设备）

ARM GNU 12.2.rel1，主机 `make` / `cc`，Python 3.9 或 3.10。源码仓库内附 SDK 与官方 DFU key，无需安装 Docker或构建 bootloader。Nordic nrfutil 的完整依赖要求较旧 BLE driver；本项目仅使用其打包 API，所以以下安装不引入 BLE driver：

```sh
python3.9 -m venv .build-venv
.build-venv/bin/pip install --no-deps nrfutil==6.1.7
.build-venv/bin/pip install -r tools/requirements-build.txt
GNU_INSTALL_ROOT=/path/to/arm-gnu-toolchain-12.2.rel1/bin/ \
PYTHON="$PWD/.build-venv/bin/python" tools/build_mocha.sh
```

`build_mocha.sh` 只清理/构建 application，运行主机测试并生成、验证 DFU。输出在 `dist/`。application version=1、hardware=0、SoftDevice requirement=0x0100，与官方 Ultra 包规则一致。源码目录若无 `.git`，构建时请设置 `MOCHA_SOURCE_REV=<build-info中的源码commit前7位>` 再运行构建脚本；归档恢复 Git 后则自动生成。ECDSA 签名含随机量，重建 ZIP 的 SHA256 可不同，固件 BIN 应一致。

测试编译实际设置与轮询源码，对官方/Mazha 迁移、持久化错误、间隔边界、无场、skip、16 槽跨半区、HF quiet/事务锁、LF burst 边界、手动取消、读卡模式、计时器回绕进行模拟；USB 测试编译实际动画函数核对 80/100ms 与 PWM 重置后的颜色、方向、步序；CLI 测试验证身份不符时只发送读身份命令。DFU 验证检查 manifest、镜像哈希、签名、硬件和 SD 条件及 Mocha 标识。

**验证边界**：已编译并做主机模拟；尚未进行新固件的实机 DFU、USB/BLE 灯光、持续场、HF/LF 门禁、认证/写卡事务和断电恢复测试。主机模拟不等于硬件验证。授权刷机后应先复核现有备份，再逐项现场验证；本次没有刷机授权。

## 灯效修复

USB 空闲充电呼吸灯只使用中间四灯，连续 PWM 输出期间只修改亮度；全暗后再切换颜色。移除每个亮度步进重启 PWM 及与卡槽动画共用的回调标志，接管时清除旧 GPIO 灯位。主机回归覆盖完整呼吸周期、暗态换色及 USB 扫描动画接管。

## USB 灯效切换

串口开关状态持续稳定 1 秒后才切换呼吸/通信灯效，防止 GUI 短暂设备探测打断呼吸动画。USB 收发不延迟。修复以短探测造成模式抖动为目标，仍需在 GUI 开启时实机观察确认。

版本号固定为 1.0.0；同版本修复使用固件字符串末尾的 Git 提交编号区分构建。

## RF 切槽和待机修复（版本仍为 1.0.0）

NFCT 重新初始化/关闭时清除场状态、过滤及激活校验状态，卡协议状态回到 IDLE。主循环检测稳定离场 100ms 后清除模拟标志并重新启动 3 秒待机计时，仍遵守 USB/蓝牙/读卡场发生器阻止深睡的规则。

### RF 唤醒与短暂断场

RF 唤醒路径先开启卡片响应，不播放阻塞式开机灯效；按键唤醒灯效保持原设置。轮询保持原有场消失后恢复原槽的行为。读卡器真正间歇开关场、或尚未 SELECT 时的正常 200ms 轮询，仍会显示实际活动槽位。

高频轮询切槽不再关闭/重建 NFCT：在未 SELECT 且读卡请求安静时暂停 RX/TX 中断，保留场和时钟状态，切换数据后重置协议状态并恢复接收；低频模块单独重新配置。手动切槽和离场恢复仍沿用原流程。

NFCT 启用时主动检查已有场，并通过驱动的正常 FIELD_DETECTED 路径启动激活校验和接收，覆盖场唤醒时缺少新场边沿的情况。

HF/LF 模拟共同持有 HFXO 请求，只有两个模块都关闭后才释放；避免 HF 轮询关闭 LF 模块时停止高频晶振。

只读诊断命令 1109 返回十二个网络序 uint32：场到来/离开、接收帧、SELECT 次数、FIELDSTATUS、HFCLKSTAT、中断掩码、协议状态、轮询暂停状态、感应状态、NFCTAGSTATE、RXD.AMOUNT。用于核对实际场、时钟与接收状态，不修改卡片。

只读命令 1110 返回九个网络序 uint32：设置加载后、BLE 初始化后、随机种子后、卡片加载后、唤醒处理前/后、进入模拟后、USB 电源事件开启后的累计 CPU 活动毫秒，以及复位原因。计时从应用入口开始，不包含引导程序及 CPU 停止时段，不能当作完整墙钟唤醒时间。
