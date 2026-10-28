# 联想小新平板 11 2025（TB335FC）永久解锁 Bootloader + Magisk Root 指南

> **实测通过** · 2026-10-28 · Lenovo TB335FC / MediaTek MT6835 (MT8755) / Android 15 / ZUXOS 1.1.10.522
>
> **无需等待联想审核** · **无需第三方付费工具** · **BL 与 Root 均为永久生效**

---

## 目录

- [成果与代价](#成果与代价)
- [为什么会卡住（背景）](#为什么会卡住背景)
- [前置条件](#前置条件)
- [完整步骤](#完整步骤)
  - [第 1 步：获取 64 位 Bootloader_SN](#第-1-步获取-64-位-bootloader_sn)
  - [第 2 步：从官方 CDN 下载 sn.img](#第-2-步从官方-cdn-下载-snimg)
  - [第 3 步：降级 LK（关键）](#第-3-步降级-lk关键)
  - [第 4 步：执行解锁](#第-4-步执行解锁)
  - [第 5 步：Magisk 永久 Root](#第-5-步magisk-永久-root)
- [故障排除](#故障排除)
- [常见问题](#常见问题)
- [备份与回滚](#备份与回滚)
- [参考资料](#参考资料)

---

## 成果与代价

**成功后：**

```
ro.boot.flash.locked      = 0           ← BL 已解锁
ro.boot.verifiedbootstate = orange      ← 解锁状态
su -c id  → uid=0(root) context=u:r:magisk:s0
magisk -v → 30.7:MAGISK:R
```

**重启后依然有效**，因为解锁状态写入了 `seccfg` 分区，root 写在 `init_boot` 分区。

**代价：**

- ⚠️ **全部数据被清空**（Android 解锁机制的硬性要求，无法绕过）
- ⚠️ 失去官方保修
- ⚠️ 每次开机可能出现"设备未验证"的橙色警告（属正常现象）

---

## 为什么会卡住（背景）

如果你之前尝试过官方流程，大概率遇到这些报错：

| 报错 | 含义 | 本文解法 |
|---|---|---|
| `Invalid unlock image header` | 你拿到的是旧格式 sn.img（5386 字节） | 改用 CDN 新格式（356 字节） |
| `Sn Image Auth fail` | sn.img 没刷进去，或格式不对 | 先 `flash unlock` 再解锁 |
| `unknown reason` | LK 拒绝 / 确认超时 | 降级 LK + 用 `unlock-go` |
| `unknow command` | 新版 LK 封堵了 `flashing unlock` | **必须降级 LK** |
| `Device dose not allow unlock` | OEM 解锁开关没开 | 手动拨动开关 |

**核心问题有两个：**

1. **联想官方解锁网站给你的 sn.img 可能是旧格式**，TB335FC 已经不认了。但服务器上其实为每台设备预生成了新的、设备专属的镜像，可以直接按 URL 取到——**不需要申请、不需要审核**。
2. **设备出厂固件（2025-11 之后）的 LK 把解锁命令封了**。刷回 2025-04 的旧版 LK 即可恢复功能。

---

## 前置条件

**设备要求**

- 联想小新平板 11 2025（TB335FC，代号 `sycamore`）
- 理论上同代号机型通用（`ro.build.fingerprint` 里能看到 `sycamore`）

**电脑环境**

- Windows / Linux / macOS 均可
- [Android SDK Platform-Tools](https://developer.android.com/studio/releases/platform-tools)（提供 `adb` 和 `fastboot`）
- `curl`（用于下载）

**设备设置**

1. 设置 → 关于平板 → 连续点击「版本号」7 次，开启开发者选项
2. 设置 → 系统 → 开发者选项：
   - 打开 **「USB 调试」**
   - 打开 **「OEM 解锁」**（会弹确认框，勾选后点启用）

> ⚠️ **「OEM 解锁」必须亲手拨动开关**。
> 用 `adb shell settings put global oem_unlock_allowed 1` 只改数据库，**不会真正通知 bootloader**，
> 后面解锁照样失败。

---

## 完整步骤

### 第 1 步：获取 64 位 Bootloader_SN

```bash
adb shell getprop ro.boot.serialno        # 8 位序列号
adb shell getprop ro.boot.bootload_sn     # ★ 64 位哈希，这个才是关键
```

**必须用 64 位的那个**（`bootload_sn`，注意拼写是 `bootload` 不是 `bootloader`）。8 位序列号拼不出正确的 URL。

预期输出类似：

```
serialno      AB12CD34
bootload_sn   <64 个十六进制字符，由 Part1+Part2 各 32 位拼接而成>
```

把它记下来，后面两步都要用。

---

### 第 2 步：从官方 CDN 下载 sn.img

**这是整个流程最关键的一步——不需要向联想申请。**

```bash
BLSn=$(adb shell getprop ro.boot.bootload_sn | tr -d '\r')
curl -fL -o sn.img "http://cdn.zui.lenovomm.com/developer/enhancedboot/${BLSn}/sn.img"
```

**验证：**

```bash
wc -c sn.img
```

**应该是 356 字节**（`enhancedboot` 新格式）。

如果拿到的是 5386 字节（旧格式），说明用的 URL 不对或者用了申请来的旧文件——旧格式在 TB335FC 上会报 `Invalid unlock image header`。

**注意事项：**

- 用 **http**，不要用 https（https 走不通）
- 这个文件是**你设备专属**的，内含你的 64 位 SN 明文 + 签名
- **绝对不要分享给他人**，也不要上传到公开仓库

---

### 第 3 步：降级 LK（关键）

**为什么必须做**：设备出厂固件（2025-11 版）的 LK 封堵了解锁命令。

先验证当前 LK 版本：

```bash
adb reboot bootloader
fastboot getvar version-bootloader
```

如果版本日期是 `2025xxxx` 之后，且下面命令报 `unknow command`，就需要降级：

```bash
fastboot flashing unlock           # 大概率 unknow command
fastboot flashing unlock_critical  # 大概率 unknow command
```

**获取旧版 LK：**

从 `mirrors.lolinet.com` 下载较旧的完整固件包，提取其中的 `lk.img`：

```
路径示例：
firmware/lenowow/2025/Tab_K11_Gen2/TB336FU/
  TB336FU_ROW_OPEN_USER_M1317.3_V_ZUI_17.0.10.260_ST_250424.zip   ← 2025-04，推荐
```

**提取技巧（不用下完 7GB）：**

zip 的中央目录在文件末尾，可以用 HTTP Range 只读目录，再按偏移精确下载 `lk.img`：

```bash
# 1. 读末尾 256KB 找 ZIP64 EOCD
# 2. 解析中央目录，定位 lk.img 的 local header offset 和 compressed size
# 3. Range 下载那一段，解压得到 lk.img
```

整个 `lk.img` 约 **2,912,192 字节**，实际只需下载约 3MB。

> ⚠️ 旧版固件包是**扁平结构**，条目名直接是 `lk.img`（没有 `image/` 前缀），
> 新版包里才是 `xxx/image/lk.img`。

**刷入旧版 LK：**

```bash
fastboot flash lk lk_old.img
fastboot reboot bootloader
fastboot getvar version-bootloader
```

**验证是否成功**：版本号应该变成类似

```
sycamore_row_wifi_824c62d_202504232127
        ↑                     ↑
     你的代号            2025-04-23（旧版）
```

如果看到 `sycamore` 说明型号完全匹配，可以继续。如果报 `Incompatible hardware`，说明 LK 与其他机型不兼容，**不要继续**。

---

### 第 4 步：执行解锁

```bash
# 确认还在 bootloader 模式
fastboot devices

# 刷入 sn.img
fastboot flash unlock sn.img
```

**预期输出：**

```
Warning: skip copying unlock image avb footer (unlock partition size: 0, unlock image size: 356)
Sending 'unlock' (0 KB)                            OKAY
Writing 'unlock'                                   OKAY     ← 只要这里是 OKAY 就成功了
Finished.
```

> `unlock partition size: 0` 的 warning **是正常的**，因为这个分区不是 GPT 里的真实分区，
> 只是传给 LK 的临时数据。

**紧接着执行解锁（不要重启）：**

```bash
fastboot oem unlock-go
```

**预期输出：**

```
(bootloader) Start unlock flow
(bootloader) unlock success
OKAY
```

**验证：**

```bash
fastboot getvar unlocked
# 期望：unlocked: yes

fastboot reboot
adb shell getprop ro.boot.flash.locked
# 期望：0
```

**到这一步 BL 已经永久解锁了。**

> ⚠️ 一定要用 `oem unlock-go`，**不要用 `oem unlock`**。
> 后者会走"请用户在几秒内按音量键确认"的流程，时间非常短，很容易超时导致 `unknown reason`。
> 失败的话重新 `flash unlock` + `unlock-go` 即可，不会损坏设备。

---

### 第 5 步：Magisk 永久 Root

**关键认知：Android 13+ 的 root 目标是 `init_boot` 分区，不是 `boot`。**

- `init_boot` 只有 8~12MB（`boot` 是 67MB）
- 它只装 ramdisk、不含内核，**跨版本兼容性高得多**

**① 备份原版 init_boot（重要！）**

解锁后可以用 root 或 BROM 方式 dump，也可以事先准备好固件包里的原版。

**② 用 Magisk 打补丁**

在平板上安装 [Magisk App](https://github.com/topjohnwu/Magisk/releases)，然后：

```
Magisk → 安装 → 选择并修补一个文件 → 选择 init_boot.img
```

生成的补丁在 `/sdcard/Download/magisk_patched-xxxxx_xxxxx.img`。

**③ 刷入**

```bash
# 确认当前槽
adb shell getprop ro.boot.slot_suffix
# 输出 _a 或 _b

adb reboot bootloader

# ⚠️ 必须带槽后缀！短名会报 partition does not exist
fastboot flash init_boot_b magisk_init_boot.img

fastboot reboot
```

**④ 验证**

```bash
adb shell su -c id
# 期望：uid=0(root) gid=0(root) context=u:r:magisk:s0

adb shell magisk -v
# 期望：30.7:MAGISK:R
```

**重启一次再验证，确认是永久 root。**

---

## 故障排除

### `fastboot flash unlock` 报 `Invalid unlock image header`

用的是旧格式 sn.img（5386 字节）。必须用 CDN 上的 356 字节新格式，见[第 2 步](#第-2-步从官方-cdn-下载-snimg)。

### `fastboot oem unlock` 报 `unknown reason`

两种可能：

1. **用了 `oem unlock` 而不是 `oem unlock-go`** —— 前者需要几秒内按键确认，容易超时
2. **LK 没降级** —— 检查 `fastboot getvar version-bootloader` 的日期

重新执行：

```bash
fastboot flash unlock sn.img
fastboot oem unlock-go
```

### `fastboot flashing unlock` 报 `unknow command`

新版 LK 封堵了这个命令（注意是 `unknow` 少个 n，LK 的拼写错误）。必须[降级 LK](#第-3-步降级-lk关键)。

### `fastboot flash init_boot` 报 `partition does not exist`

必须用带槽后缀的完整名：

```bash
fastboot flash init_boot_b xxx.img    # ✅
fastboot flash init_boot   xxx.img    # ❌
```

`getvar partition-type:init_boot` 也会返回空，看着像分区不存在，其实是命名问题。

### `fastboot getvar unlock_ability` 返回空

用错命令了。正确的是：

```bash
fastboot flashing get_unlock_ability
# 期望：unlock_ability is true
```

### 刷机过程中设备黑屏、插电脑只响一下

**这是电池耗尽，不是砖。**

原因：设备停在 BROM（芯片级下载模式）时，**充电管理程序不运行**，电池会持续耗电直到耗尽。此时插充电器也不会充。

**解法：**

1. 拔掉所有线
2. **长按电源键 30-60 秒**（不是 10 秒，要够长，让芯片彻底退出 BROM）
3. 静置 1 分钟
4. 用**原装充电器**充 30 分钟（电脑 USB 只有 0.5A，不够）
5. 正常开机

判断依据：USB 里看到 `VID_0000&PID_0002 设备描述符请求失败` 就是这种状态。

---

## 常见问题

**Q：解锁后能恢复保修吗？**

理论上刷回官方固件、重新上锁可以，但设备会有解锁记录（`verifiedbootstate` 的变化可能被检测）。实操上不建议指望保修。

**Q：能重新上锁吗？**

```bash
fastboot oem lock
```

**但强烈不建议**。上锁后如果系统已被修改，设备会直接无法启动，且因为已经上锁没法再刷机抢救。**只有完全恢复官方固件后才考虑上锁。**

**Q：数据真的全丢了吗？**

是的。解锁会触发 Android 的强制清数据机制，这是安全设计，绕不过去。请在开始前备份。

**Q：旧版 LK 有安全风险吗？**

旧版 LK 只是 2025-04 的官方固件，不是第三方修改版，功能上没有后门。但如果联想在后续版本里修补了安全漏洞，旧版 LK 也意味着这些漏洞仍然存在。解锁状态本身已经是"不安全"的，这是取舍。

**Q：能刷回新版 LK 吗？**

可以，而且**不会重新上锁**（解锁状态记录在 `seccfg` 分区，与 LK 无关）：

```bash
fastboot flash lk lk_stock.img
```

**Q：这个流程对其他联想 MTK 平板通用吗？**

大体思路通用（CDN 取 sn.img + 降级 LK），但**具体 URL 路径、LK 版本、分区名可能不同**。
`enhancedboot` URL 是否通用未验证，`lenovoboot` 是另一种路径。请自行验证。

---

## 备份与回滚

**强烈建议在动手前备份这些分区**（解锁后用 root 或 BROM 方式 dump）：

| 分区 | 大小 | 重要性 |
|---|---|---|
| `init_boot_a` / `init_boot_b` | 8MB / 12MB | ★★★ root 出问题时恢复 |
| `boot_a` / `boot_b` | 67MB | ★★★ 内核，刷坏了靠它 |
| `seccfg` | 8MB | ★★★ 锁定状态，最容易变砖 |
| `lk_a` / `lk_b` | 16MB | ★★ bootloader |
| `vbmeta_a` | 8MB | ★★ 验证启动 |

**回滚方式：**

```bash
# 恢复 init_boot
fastboot flash init_boot_b stock_init_boot.img

# 恢复 LK
fastboot flash lk lk_stock.img
```

**BROM（芯片级）救砖** 也是可行的，MTK 设备基本不会真正变砖，最坏情况用 MTK 下载工具重刷官方固件。

---

## 姊妹篇

- **[DA 逆向复盘：8 小时失败的完整记录](docs/da-reverse-engineering-retrospective.md)** — 在找到官方路径之前，我们尝试逆向 MTK 官方 DA 直接修改 seccfg。虽然最终失败，但过程里挖到了 MTK 平台安全机制的大量细节（DA 芯片表、CUSTOM 命令、SEJ 加密链、分区属性表、ARM32 反汇编）。**如果你也对 MTK 内部机制感兴趣，这篇的信息密度比本文更高。**

---

## 参考资料

- [How to Obtain the Correct sn.img and Unlock the Lenovo TB336FU Bootloader](https://xdaforums.com/t/how-to-obtain-the-correct-sn-img-and-unlock-the-lenovo-tb336fu-bootloader.4797087) — 同平台机型的完整解析，本文的 CDN 路径和命令选择依据
- [Unofficial Unlocking Lenovo Xiaoxin Pad Pro 2025 (TB375FC)](https://xdaforums.com/t/unofficial-unlocking-lenovo-xiaoxin-pad-pro-2025-tb375fc.4717695) — 刷 patched LK + `unlock_critical` 的早期方案
- [How to Create SN File for Lenovo Bootloader Unlocking](https://droidwin.com/how-to-create-sn-file-for-lenovo-bootloader-unlocking) — 官方申请流程与 CDN 直链的出处
- [Magisk](https://github.com/topjohnwu/Magisk) — 官方仓库
- [mirrors.lolinet.com](https://mirrors.lolinet.com/firmware/lenowow/) — 联想平板固件镜像站

---

## 免责声明

**解锁 Bootloader 与获取 Root 权限会：**

- 清空设备全部数据（不可逆）
- 使设备失去官方保修
- 降低系统安全性（任何人都能在物理接触时读取/修改数据）
- 存在变砖风险（虽然 MTK 设备通常可通过 BROM 抢救）

**本文仅为个人实测记录，按此操作的风险由你自己承担。** 不同批次、不同固件版本的设备可能存在差异。

---

## 更新日志

- **2026-10-28** — 首次记录，TB335FC / ZUXOS 1.1.10.522 / Android 15 实测通过
