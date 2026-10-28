# 逆向 MTK 官方 DA 尝试解锁 seccfg —— 8 小时失败的完整复盘

> **结论先说**：这条路最终**走不通**，我们转向官方解锁通道后 20 分钟就成功了。
> 但过程中挖到的信息对理解 MTK 平台的安全机制有价值，完整记录备查。
>
> 平台：MediaTek MT6835（Dimensity 6100+ / MT8755） · 设备：Lenovo TB335FC · Android 15

---

## 目录

- [目标与起点](#目标与起点)
- [第一层：DA 上传为什么卡住](#第一层da-上传为什么卡住)
- [第二层：官方 DA 不支持 CUSTOM 命令](#第二层官方-da-不支持-custom-命令)
- [第三层：seccfg 写保护](#第三层seccfg-写保护)
- [第四层：seccfg 签名算法](#第四层seccfg-签名算法)
- [第五层：DA 内部的安全策略表](#第五层da-内部的安全策略表)
- [两次 patch 尝试与崩溃分析](#两次-patch-尝试与崩溃分析)
- [为什么这条路必然失败](#为什么这条路必然失败)
- [挖到的可复用技巧](#挖到的可复用技巧)
- [教训](#教训)

---

## 目标与起点

**目标**：解锁 Bootloader（即把 `seccfg` 分区的 `lock_state` 从 1 改成 3），不依赖官方解锁码。

**起点**：设备在 BROM 模式下可通信，`mtkclient` 能握手读芯片信息：

```
CPU: MT6835V/ZA    HW code: 0x1209    BROM mode detected
SBC enabled: True
SLA enabled: False      ← 安全启动（Serial Link Auth）是关的
DAA enabled: True       ← 但下载代理认证是开的
Memory read auth: True
Cmd 0xC8 blocked: True
```

`SLA enabled: False` 这一点很关键——**说明 BROM 阶段不验签**，理论上可以上传自己的 DA。这给了我们希望。

---

## 第一层：DA 上传为什么卡住

`mtkclient` 一直报：

```
DaHandler - Device is protected.
DaHandler - [LIB]: Failed to dump preloader from ram
DAconfig - [LIB]: No da_loader config set up
DAXML - [LIB]: No valid da loader found... aborting.
```

### 定位过程

先怀疑是 preloader 没给对。但给了 dump 出来的 preloader 后仍然失败。

于是去看 `DAconfig.setup()` 的判定逻辑：

```python
# mtkclient/Library/DA/daconfig.py:207
def setup(self):
    dacode = self.config.chipconfig.dacode          # MT6835 = 0x1209
    if dacode in self.dasetup:                       # 关键：必须在 DA 文件里找到这个 hw_code
        loaders = self.dasetup[dacode]
        ...
    if self.da_loader is None:
        self.error("No da_loader config set up")     # ← 就是这里
```

**也就是说：DA 文件内部必须有一个 `hw_code == 0x1209` 的条目，否则直接放弃。**

### 用 mtkclient 自己的 DA 解析器枚举

```python
import sys, struct
sys.path.insert(0, '.')
from mtkclient.Library.DA.daconfig import DA

f = open('mtkclient/Loader/MTK_DA_V6.bin', 'rb')
hdr = f.read(0x68)
count = struct.unpack('<I', f.read(4))[0]
v6  = b'MTK_DA_v6' in hdr
f.seek(0x6C + 0xD8)
old = (f.read(2) == b'\xDA\xDA')
offset = 0xD8 if old else 0xDC

for i in range(count):
    f.seek(0x6C + i * offset)
    d = DA(f.read(offset), old, v6)
    print(f'hw_code=0x{d.hw_code:04X} hwver=0x{d.hw_version:X} v6={d.v6}')
```

**输出：**

```
hw_code=0x0907
hw_code=0x0992
hw_code=0x1066
hw_code=0x1129
hw_code=0x1172
hw_code=0x1208   ← MT6833
hw_code=0x1229
hw_code=0x1296
hw_code=0x1471
```

**没有 0x1209。差一个号。**

MT6833（0x1208）在里面，MT6835（0x1209）不在。所以社区版 `MTK_DA_V6.bin` **永远不可能**支持这颗芯片——不是参数问题，是文件里根本没有这份数据。

### 一个容易误判的细节

`payloads/` 目录下那些 `mt6833_payload.bin`、`mt6853_payload.bin` 等，看起来像是有对应芯片的 payload。

**实际上全是 612 字节的占位 stub**，不是真正的 payload。真正被当作 payload 用的是 `da_xml_64.bin`（23,640 字节）、`da_x.bin`（16,428 字节）这些。

**更关键**：`da_xml_64.bin` **不是 DA**，它是 `v6.py` 的 `patch()` 阶段加载的 **daextension（补丁扩展）**。把它当 `--loader` 传给 BROM，等于给芯片喂 23KB 垃圾——芯片会「接受（OKAY）但无响应」。

这个误解让我浪费了好几轮。

### 解决

从官方固件包的 `download_agent/` 提取 `DA_BR.bin`：

```
MTK_DOWNLOAD_AGENT
MTK_DA_v6_2026-01-06 20:05:10
→ hw_code = 0x1209   hw_sub = 0x8A00   hwver = 0xCA00   v6 = True
```

换上之后：**stage1 上传成功、stage2 上传成功、DA 正常启动**。

```
DAXML - Uploading xflash stage 1 from DA_BR.bin
DAXML - Successfully uploaded stage 1, jumping ..
Preloader - Jumping to 0x2000000: ok.
DAXML - Uploading stage 2...  100% (0x5CDAC)
DAXML - Successfully booted to stage 2
DAXML - DA XML SLA is disabled
```

**这一层通了。** 顺带确认：这台设备连 auth 文件都不需要（`SLA is disabled`）。

---

## 第二层：官方 DA 不支持 CUSTOM 命令

DA 起来后，mtkclient 会尝试加载 XML 扩展（用来注册自定义命令、支持 UFS/eMMC/RPMB 等）：

```python
# xml_lib.py:714
xmlcmd = self.cmd.create_cmd("CUSTOM")
if self.xsend(xmlcmd):
    data = self.get_response()
    if data == 'OK':
        ...发送扩展代码...
```

加诊断后拿到 DA 的原话：

```
[PATCHDBG] xdata_len=16652
[PATCHDBG] CUSTOM resp='ERR!UNSUPPORTED'
DA XML Extensions failed.
→ DeviceClass - USBError(5, 'Input/Output Error')
```

**零售固件里的官方 DA 没有编译 CUSTOM 命令。** 而 mtkclient 的整套高级功能都建立在这个命令上。

而且更麻烦的是：CUSTOM 失败之后，**后续所有命令都跟着 USB 报错**，整个会话废掉。

### 解法：`--stock`

看 `xml_lib.py:298`：

```python
if self.mtk.daloader.patch or not self.config.target_config["sbc"] and not self.config.stock:
    da1, da2 = self.patch_da(da1, da2)
    self.mtk.daloader.patch = True
else:
    self.mtk.daloader.patch = False     # ← --stock 走这里
```

加 `--stock` 后 `daloader.patch = False`，`patch()` 不被调用，扩展不加载，DA 就完全正常：

```
printgpt  → 完整 GPT 表输出正常
r seccfg  → 成功 dump 8MB
```

**这一层也通了**，代价是没有 XML 扩展（某些高级操作不可用）。

> 顺便记一个有用的信息：GPT 里 `seccfg` 在 `Offset 0x19800000, Length 0x800000`，
> `init_boot_a @ 0x30f00000`，`lk_a @ 0x27f00000`，`lk_b @ 0x3df80000`，
> `lenovolock @ 0x30b000000`（512KB，联想自定义分区）。

---

## 第三层：seccfg 写保护

直接写分区：

```bash
python mtk.py w seccfg seccfg_unlocked.bin --stock --loader DA_BR.bin ...
```

**失败：**

```
Failed to write ... to sector 104448 with sector count 2048.
```

先怀疑地址算错（`sector 104448 × 512 = 53MB`，而 seccfg 实际在 `0x19800000` = 427MB）。但核对后发现：

```
xml_lib.py:826   self.config.pagesize = 4096
104448 × 4096 = 427,819,008 = 0x19800000   ✓ 地址是对的
```

所以不是地址问题。加诊断看 DA 的原始回应：

```python
# 在 writeflash() 里插入
self.info(f"[WDBG] addr={hex(addr)} length={length} parttype={parttype}")
self.send_command(self.cmd.cmd_write_flash(...), noack=True)
cmd, fileopresult = self.get_command_result()
self.info(f"[WDBG] resp_cmd={cmd!r} type={type(fileopresult).__name__}")
```

**输出：**

```
[WDBG]  addr=0x19800000  length=512  parttype=UFS-LUA2       ← 参数全对
[WDBG]  resp_cmd='CMD:FILE-SYS-OPERATION' type=FileSysOp
[WDBG]  FSO key='FILE-SIZE' path='MEM://0x8000000:0x200'      ← key 也对
[WDBG2] cmd='CMD:END'  val='Security deny for [seccfg].'      ← ★ 真凶
```

**DA 用一句话把门关上了：`Security deny for [seccfg].`**

不是参数、不是地址、不是长度，是**固件层的安全策略**。

这也解释了一开始那个矛盾现象：`r seccfg`（读）能成功，`w seccfg`（写）必死。

---

## 第四层：seccfg 签名算法

既然直接写不行，那走 `seccfg` 命令（内部读-改-重签-写）。但这条路要求先能解析现存的 seccfg。

### seccfg V4 结构（逆向自 mtkclient/Library/Hardware/seccfg.py）

```
0x00  magic      "MMMM" (0x4D4D4D4D)
0x04  version    4
0x08  size       60 (0x3C)
0x0C  lock_state 1=LOCKED, 3=UNLOCK
0x10  dm_verity_state
0x14  sboot_runtime
0x18  endflag    0x45454545 ("EEEE")
0x1C  32 字节签名
补齐到 0x200 (512) 的倍数
```

实机 dump 出来完全吻合：`lock_state = 1`（锁定），签名在 0x1C，全分区只有 48 个非零字节。

### 签名是纯软件 AES，密钥硬编码

```python
# mtkclient/Library/Hardware/hwcrypto_sej.py:958
@staticmethod
def sej_sec_cfg_sw(data, encrypt=True):
    ctx = CryptUtils.Aes()
    return ctx.aes_cbc(
        key=b"25A1763A21BC854CD569DC23B4782B63",          # ← 硬编码 16 字节
        iv=bytes.fromhex("57325A5A125497661254976657325A5A"),
        data=data, decrypt=not encrypt)
```

生成逻辑（`seccfg.py:137 create()`）：

```python
seccfg_data = pack("<IIIIIII", magic, ver, size, lock_state,
                   dm_verity, sboot, 0x45454545)
dec_hash = sha256(seccfg_data).digest()
enc_hash = sej_sec_cfg_sw(dec_hash, encrypt=True)   # hwtype == "SW" 时
indata = seccfg_data + enc_hash
while len(indata) % 0x200: indata += b"\x00"
```

**看起来完全可以在本地构造一个解锁版 seccfg。**

### 但原机是硬件签名

用硬编码密钥去解原机的 32 字节签名，得到的东西和 `sha256(头)` **不匹配**：

```
sha256(头)  = 7ec2e74193dbe969bd1e899c0e5a9d9b...
SW 解密结果 = b661f4f925cc5e78b04b72cac102ecfe...
→ 不匹配
```

说明原机 seccfg 用的是 **SEJ 硬件加密单元**（密钥在 eFuse 里，读不出来），不是软件算法。

`parse()` 的完整判定链：

```python
_hash = sha256(seccfg_data)
dec_hash = sej_sec_cfg_sw(self.hash, False)
if _hash == dec_hash:
    hwtype = "SW"
else:
    self.custom_sej_hw = None
    if self.custom_sej_hw is not None:      # 永远 False，被置空了
        ...
    else:
        dec_hash = sej_sec_cfg_hw_V3(self.hash, False, legacy=False)   # ← 硬件
        if _hash == dec_hash: hwtype = "V3"
        else: ... legacy=True → "V4" ...
        else: ... sej_sec_cfg_hw → "V2"
        else: return False
```

**我们卡在 `sej_sec_cfg_hw_V3` 这一步。**

### 硬件加密卡在哪

`sej_sec_cfg_hw_V3` → `hw_aes128_cbc_encrypt` → `SEJ_V3_Init`，需要读写 SEJ 寄存器（`sej_base = 0x1000a000`）。

而 v6.py 的寄存器读写**完全依赖 CUSTOM 命令**：

```python
# v6.py:978（原始代码）
def readmem(self, addr, dwords=1):
    if dwords < 0x20:
        res = self.custom_readregister(addr, dwords)      # ← CUSTOM
    else:
        res = self.custom_read(addr, dwords * 4)          # ← CUSTOM
    ...
    self.debug(f"RX: {hex(addr)} -> {hex(res)}")          # res 是 None 时这里崩
```

而 CUSTOM 在第二层已经证明**不被支持**。

**闭环了：要重签 seccfg → 要 SEJ 硬件加密 → 要读寄存器 → 要 CUSTOM → 不支持。**

---

## 第五层：DA 内部的安全策略表

既然 README 这条路堵死，那就看看 `Security deny` 到底是哪段代码判的，能不能 patch。

### 定位

DA2 布局：文件偏移 472,976 起，380,588 字节，加载到 `0x40000000`，**ARM 模式**（不是 Thumb）。

```python
import sys; sys.path.insert(0, 'mtkclient')
from mtkclient.Library.Exploit.exptools.arm_tools import ArmTools

d = open('DA_BR.bin', 'rb').read()
da2 = bytearray(d[472976:472976 + 380588 - 256])
at = ArmTools(da2, 0x40000000)

print(at.find_string_xref('Security deny for [%s].\n'))   # → 0x25d8
```

### 反汇编 0x25xx

```asm
0x25A0: sub      r1, fp, #0x90        ; 输出缓冲区
0x25A4: mov      r0, r7               ; 分区名
0x25A8: bl       #0x40030db8          ; 获取分区信息 → 填充 [fp,#-0x90]
0x25B8: ldrb     r1, [fp, #-0x8f]     ; buf[1]
0x25BC: movw     r0, #0x7085
0x25C0: ldrb     r2, [fp, #-0x8e]     ; buf[2]
0x25C4: movt     r0, #0x4004          ; → "hash_binding:%d, img_auth_required:%d\n"
0x25C8: bl       #0x40008b80          ; 打印
0x25CC: ldrb     r0, [fp, #-0x8d]     ; buf[3]
0x25D0: cmp      r0, #0
0x25D4: beq      #0x400025ec          ; buf[3]==0 → 放行
0x25D8: movw     r0, #0x70ac
0x25DC: movt     r0, #0x4004          ; → "Security deny for [%s].\n"
0x25E0: mov      r1, r7
0x25E4: bl       #0x40009808          ; 打印
0x25E8: b        #0x4000252c          ; 错误退出
0x25EC: ...                            ; 继续
```

字符串确认：

```
0x47085: "hash_binding:%d, img_auth_required:%d\n"
0x470AC: "Security deny for [%s].\n"
```

**逻辑很清楚：`buf[3]` 非 0 → 拒绝；为 0 → 放行。**

### buf[3] 从哪来

```asm
0x30DB8: cmp      r1, #0
0x30DBC: bxeq     lr
0x30DC0: push     {r4, r5, r6, sl, fp, lr}
0x30DC8: mov      r4, r1               ; r4 = 输出缓冲区
0x30DCC: mov      r5, r0               ; r5 = 分区名
0x30DD0: bl       #0x400309d0          ; 取得句柄 → r6
0x30DD8: bl       #0x40030bbc
0x30DDC: strb     r0, [r4, #1]         ; buf[1]
0x30DE0: mov      r0, r6
0x30DE4: bl       #0x40030d70
0x30DE8: strb     r0, [r4, #2]         ; buf[2] = img_auth_required
0x30DEC: mov      r0, r6
0x30DF0: bl       #0x40030d84
0x30DF4: strb     r0, [r4, #3]         ; buf[3] = 拒绝判断依据
0x30DF8: mov      r0, r6
0x30DFC: bl       #0x40030b0c
0x30E00: str      r0, [r4, #4]
```

两个小函数：

```asm
0x30D70: push {fp,lr}; mov fp,sp; bl #0x40030bd0; ubfx r0,r0,#1,#1; pop {fp,pc}   ; 取 bit1
0x30D84: push {fp,lr}; mov fp,sp; bl #0x40030bd0; and  r0,r0,#1;    pop {fp,pc}   ; 取 bit0
```

底层 `0x30BD0` 会去查一张**静态分区属性表**：

```asm
0x30C4C: movw r0, #0xbf40
0x30C50: movt r0, #0x4005             ; 表基址 0x4005BF40
0x30C54: add  r0, r0, r4, lsl #5      ; 每项 0x20 字节
0x30C58: ldrb r0, [r0, #0x14]         ; 读 +0x14 字段
```

表在 DA2 内偏移 `0x5BF40`，逐项 dump 出来：

```
项 0: default      项 1: preloader   项 2: lk        项 3: logo
项 4: init_boot    项 5: boot        项 6: vendor_boot 项 7: recovery
项 8: system       项 9: vendor      项10: odm       项11: vbmeta
...
项48: lenovolock   项49: lenovosku_1 项50: lenovosku_2 项51: lenovoraw
项52: lenovocust   项53: NULL
```

**全表 54 项，没有 `seccfg`。**

**这就是根因**：seccfg 查表必然落空 → 拿到越界数据 → 判定为「需要认证」→ 拒绝写入。

---

## 两次 patch 尝试与崩溃分析

### 第一次：改跳转分支（失败）

把 `0x25D4` 的 `beq` 改成无条件 `b`，强制跳过拒绝分支：

```python
# 0x25D4: 0x0A000004 (beq) → 0xEA000004 (b)
d[472976 + 0x25D4 : 472976 + 0x25D4 + 4] = bytes([0x04, 0x00, 0x00, 0xEA])
```

**结果：DA 起来就废。**

```
DeviceClass - USBError(5, 'Input/Output Error')
DAXML - [LIB]: Error: Cannot Reinit daconfig
TypeError: '<=' not supported between instances of 'int' and 'NoneType'
```

连分区表都读不到（`get_gpt → fh.seek(0) → filesize 是 None`）。

**原因**：强行跳过了拒绝分支，但后面的代码依赖 `buf[]` 里其他字段已被正确初始化。跳过导致拿到未初始化数据 → 崩。

### 第二次：改字段计算函数（也失败）

不动分支，改成让 `buf[2]` 和 `buf[3]` 恒为 0：

```python
# 0x30D7C: ubfx r0,r0,#1,#1 (0xE7E000D0) → mov r0,#0 (0xE3A00000)
# 0x30D90: and  r0,r0,#1    (0xE2000001) → mov r0,#0 (0xE3A00000)
MOV0 = bytes([0x00, 0x00, 0xA0, 0xE3])
```

先用调用点扫描确认安全性：

```python
# 暴力扫 BL 指令
for off in range(0, len(da2) - 3, 4):
    ins = struct.unpack('<I', da2[off:off+4])[0]
    if (ins & 0xFF000000) == 0xEB000000:        # BL
        imm = ins & 0xFFFFFF
        if imm & 0x800000: imm -= 0x1000000
        tgt = BASE + off + 8 + imm * 4
        ...
```

结果：

```
0x30D70 (buf[2]): 被调用 1 次 → 0x30DE4
0x30D84 (buf[3]): 被调用 1 次 → 0x30DF0
```

**各自只有一个调用点，看起来非常安全。** 但实际刷进去后：

```
DeviceClass - USBError(5, 'Input/Output Error') × 3
```

**同样崩了。**

### 为什么"只有一个调用点"还是崩了

关键在于：`0x30DB8`（获取分区信息）这个函数**每次读写任何分区都会被调用**，不只是 seccfg。

把它的两个字段恒置为 0，等于**对所有分区宣称"不需要镜像认证"**。DA 后续流程拿到未经认证的分区数据，在某个环节（如校验 vbmeta 或加载 UFS 参数）直接崩掉。

**这不是"patch 位置不对"，而是"这个检查是全局的，不能局部绕过"。**

---

## 为什么这条路必然失败

总结下来是三层嵌套的阻塞，必须全部解决才有戏：

```
要解锁 → 要改 seccfg
要改 seccfg → 要过 DA 的 Security deny
要过 Security deny → 要 seccfg 出现在属性表里（结构性问题，改不了）
或 要重签合法 seccfg → 要 SEJ 硬件加密
要 SEJ 硬件加密 → 要读写寄存器
要读写寄存器 → 要 CUSTOM 命令
要 CUSTOM 命令 → 要厂商定制版 DA（零售固件里没有）
```

**每一环都是死结。** 而 patch 掉中间任何一环都会破坏整个安全模型的完整性假设，导致 DA 崩溃。

**根本矛盾**：`seccfg` 是设计上受保护的分区，所有"绕过"最终都会撞到某个不可绕过的完整性前提。

---

## 挖到的可复用技巧

虽然结论是失败，但过程里有几个东西是可复用的。

### 1. 用 mtkclient 自己的类解析 DA 支持的芯片

```python
from mtkclient.Library.DA.daconfig import DA
# 见第一层代码
```

比手工猜偏移可靠得多。

### 2. HTTP Range 精确提取大 ZIP 里的单个文件

固件包 7~9GB，但只需要 `lk.img`（3MB）。zip 中央目录在末尾，可以只读目录再精确 Range 下载：

```python
# 1. 读末尾 256KB，rfind(b'PK\x06\x07') 找 ZIP64 EOCD
# 2. 解析出中央目录 offset/size，Range 读目录
# 3. 解析条目表，拿到目标文件的 lho（local header offset）和 csize
# 4. 读 local header（30 字节 + filename + extra）确定数据起始
# 5. Range 下载 csize 字节，zlib.decompressobj(-15) 解压
```

仓库里的 `scripts/extract-from-zip.py` 就是干这个的，实测从 7.2GB 包里提取 3MB 文件，只用了 1.8 秒。

> ⚠️ 一个坑：`https` + Python `urllib` 在 lolinet 上会 `SSL: UNEXPECTED_EOF_WHILE_READING`，
> 换 `curl --noproxy '*' -r start-end` 立刻正常。

### 3. ARM32/ARM64 里找字符串引用的正确姿势

- **ARM32**：`ADRP` 不存在，用 `ArmTools.find_string_xref()` 即可
- **ARM64**：`ADRP + ADD` 组合，`ADRP` 掩码 `(ins & 0x9F000000) == 0x90000000`，
  `immlo = (ins >> 29) & 3`，`immhi = (ins >> 5) & 0x7FFFF`，
  页对齐用 `(off & ~0xFFF) + imm * 4096`

**校准方法**：先找一个已知的 `ADRP+ADD`，看 capstone 算出的目标和实际字符串偏移是否一致，确认映射关系后再批量搜。

### 4. 判断一个函数能否安全 patch：扫调用点

```python
# 暴力扫 BL（不依赖 capstone，不怕数据段打断反汇编）
for off in range(0, len(code) - 3, 4):
    ins = struct.unpack('<I', code[off:off+4])[0]
    if (ins & 0xFF000000) == 0xEB000000:      # ARM BL
        imm = ins & 0xFFFFFF
        if imm & 0x800000: imm -= 0x1000000
        target = BASE + off + 8 + imm * 4
```

比 capstone 线性反汇编可靠——后者遇到数据段会中断（实测只跑了 287 条就停了）。

### 5. 诊断加在关键返回点，别猜

这次最有价值的发现全部来自"加一行 log 看 DA 到底回了什么"：

```python
self.info(f"[WDBG2] cmd={cmd!r} type={type(result).__name__} val={str(result)[:160]}")
```

直接拿到 `val='Security deny for [seccfg].'`。
如果只是盯着 `Failed to write` 猜，永远猜不到真正原因。

---

## 教训

1. **先确认"有没有"再研究"怎么做"。** 我们花大量时间研究怎么让 mtkclient 支持 MT6835，其实第一步就该枚举 DA 的芯片表——一眼就能看出 0x1209 不在里面，省下整整一层工作量。

2. **"只有一个调用点"不等于"改它安全"。** 要看那个调用点所在的函数被谁调用、调用频率如何。`0x30DB8` 每次读写分区都调，patch 它等于全局改行为。

3. **某些保护是结构性的，不是逻辑性的。** `seccfg` 不在属性表里，这不是一个 if 判断，而是数据结构的缺失。任何 patch 都无法凭空补上一条表项。

4. **及时止损。** 我们在 DA 逆向上花了 8 小时，转向官方通道后 20 分钟成功。虽然挖到的东西有价值，但如果一开始就先去查官方资源，这 8 小时可以省下来。

5. **失败也要写下来。** 这篇文档里"哪些方法不行、为什么不行"的信息密度，其实比成功流程更高——它能帮别人省掉同样的 8 小时。

---

## 参考

- [mtkclient](https://github.com/bkerler/mtkclient) — 本文所有 DA 解析、ArmTools 反汇编能力都来自它
- [MT6835 BROM 配置](https://github.com/bkerler/mtkclient/blob/main/mtkclient/config/brom_config.py) — `damode=DAmodes.XML`, `dacode=0x1209`
- [ARMv8 A64 指令编码](https://developer.arm.com/documentation/ddi0596/latest/) — ADRP/ADD 的 immhi/immlo 位域
- 姊妹篇：[《TB335FC 永久解锁 BL + Magisk Root 指南》](../README.md) —— 最终成功的路径
