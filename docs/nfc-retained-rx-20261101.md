# NFC 短场后接收恢复（2026-11-01）

修复固件：`Mocha-1.0.0-c163649-rfdiag2`，基于 c163649，保留 Access Trace 1.6。

## 问题与修复

电池 SYSTEMOFF 经 iPhone NFC 短场唤醒后可能持续无弹窗。失败现场为 NFC reset reason，35 次进场/35 次离场、仅首次 READY、0 次完整 RX、0 次选卡。6 次超时没有对应应用 TX，不能据此认定回复发送超时。

驱动离场时关闭 RX/TX 中断，但保留 NFCT 激活状态 3 秒。下一次进场若硬件仍为 Idle，ACTIVATE 不一定再次产生 READY；应用此前只在 READY 恢复 RX。修复在再次进场且 NFCT 已 Idle、未被轮询暂停时恢复接收；Disabled/RampUp 继续等待 READY，Receive/FrameDelay/Transmit 不改 DMA 缓冲。

29 项主机测试通过，ARM 构建及应用层 DFU 签名校验通过。安装后 16 槽数据与导出配置逐项匹配。用户实测确认电池近场唤醒正常，以及手动 4→5→4 切换正常。以上为该设备/iPhone 验证，不代表所有手机或所有卡类型已验证。

## RAM 诊断接口

256 条循环日志，每条 32 字节，收发截取前 16 字节，重启清空，不写 Flash；日志会轻微增加运行时开销。升级包仍保留诊断。命令 1111 只读，不切槽、不重载数据。

请求 `<IB`：小端序号起点、1–8 条数量。响应头 `<4I`：版本1、最早保留序号、下一序号、条数。事件 `<IIBBBBHH16s`：序号、RTC ticks、类型、从0起槽号、软件状态、硬件状态、帧位数、截取字节数、前缀。

类型1–11：field_on、field_off、rx、tx_start、tx_end、timeout、ready、sense_on、sense_off、tx_request、rearm。tx_request 在提交 STARTTX 后记录；tx_end 才是硬件发送完成。ticks 不包括 bootloader；按 SDK RTC 配置换算，注意计数回绕。

导出：`python tools/rf_diag.py --port <port> --output <local.json>`。工具固定首次读取的结束序号，并检测导出时覆盖。日志可能包含卡片交互数据，请保存在本地；本仓库不附带用户原始日志或卡片数据。

## 另一个独立问题

Classic 的 field_off_do_reset 全局运行策略在切换到非 Classic 后未清除。这不属于 rfdiag2 的修复范围，后续代码修复需独立提交，不能声称上述 iPhone 验证已覆盖它。
