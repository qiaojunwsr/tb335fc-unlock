#!/usr/bin/env python3
"""
从远程 ZIP（含 ZIP64）中精确提取单个文件，不需要下载整个包。

适用场景：固件包动辄 7~9GB，但只需要其中的 lk.img（约 3MB）之类的小文件。
原理：ZIP 的中央目录在文件末尾，用 HTTP Range 只读目录，
      再按条目的 local header offset 精确下载那一段，deflate 解压。

用法：
    python extract-from-zip.py <zip_url> <entry_suffix> <output_path>

示例：
    python extract-from-zip.py \
        "https://example.com/firmware.zip" \
        "/image/lk.img" \
        "./lk.img"

注意：
  - 如果 Python urllib 报 SSL: UNEXPECTED_EOF，改用 curl 模式（--use-curl）
  - 某些站点对 urllib 的 TLS 握手不友好，curl 反而稳定
"""
import sys, os, struct, zlib, subprocess, argparse

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def fetch_urllib(url, start, end, timeout=240):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Range": f"bytes={start}-{end}"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def fetch_curl(url, start, end, timeout=300):
    tmp = ".range.tmp"
    subprocess.run(["curl", "-sL", "--noproxy", "*", "-r", f"{start}-{end}",
                    "-o", tmp, url], check=True, timeout=timeout)
    data = open(tmp, "rb").read()
    os.remove(tmp)
    return data


def get_size(url, fetch):
    # 请求 1 字节，从 Content-Range 读总大小
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-0"})
    resp = urllib.request.urlopen(req, timeout=60)
    cr = resp.headers.get("Content-Range", "")
    resp.read()
    if "/" in cr:
        return int(cr.split("/")[-1])
    raise RuntimeError("服务器未返回 Content-Range，可能不支持 Range 请求")


def parse_central_directory(cd):
    entries = {}
    p = 0
    while p < len(cd) - 4 and cd[p:p + 4] == b"PK\x01\x02":
        f = struct.unpack("<IHHHHHHIIIHHHHHII", cd[p:p + 46])
        method, csize, usize = f[4], f[8], f[9]
        nlen, elen, clen, lho = f[10], f[11], f[12], f[16]
        name = cd[p + 46:p + 46 + nlen].decode("utf-8", "replace")

        # ZIP64 extra field
        if 0xFFFFFFFF in (csize, usize, lho):
            ex = cd[p + 46 + nlen:p + 46 + nlen + elen]
            q = 0
            while q < len(ex) - 4:
                hid, hsz = struct.unpack("<HH", ex[q:q + 4])
                if hid == 1:
                    body = ex[q + 4:q + 4 + hsz]
                    r = 0
                    if usize == 0xFFFFFFFF:
                        usize = struct.unpack("<Q", body[r:r + 8])[0]; r += 8
                    if csize == 0xFFFFFFFF:
                        csize = struct.unpack("<Q", body[r:r + 8])[0]; r += 8
                    if lho == 0xFFFFFFFF:
                        lho = struct.unpack("<Q", body[r:r + 8])[0]; r += 8
                q += 4 + hsz

        entries[name] = dict(method=method, csize=csize, usize=usize, lho=lho)
        p += 46 + nlen + elen + clen
    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("entry_suffix", help="条目名后缀，如 /image/lk.img 或 lk.img")
    ap.add_argument("output")
    ap.add_argument("--use-curl", action="store_true",
                    help="用 curl 代替 urllib（遇到 SSL 错误时用）")
    args = ap.parse_args()

    fetch = fetch_curl if args.use_curl else fetch_urllib

    size = get_size(args.url, fetch)
    print(f"[*] 远程文件大小: {size:,} 字节 ({size / 2**30:.2f} GB)")

    # 1. 读末尾 256KB 找 ZIP64 EOCD
    tail_len = min(262144, size)
    tail = fetch(args.url, size - tail_len, size - 1)
    i64 = tail.rfind(b"PK\x06\x07")
    if i64 < 0:
        raise RuntimeError("未找到 ZIP64 EOCD，可能不是 ZIP64 格式")

    eocd64_off = struct.unpack("<Q", tail[i64 + 8:i64 + 16])[0]
    e64 = fetch(args.url, eocd64_off, eocd64_off + 55)
    n_total, cd_size, cd_off = struct.unpack("<QQQ", e64[32:56])
    print(f"[*] 条目数: {n_total}, 中央目录: {cd_size} 字节 @ {cd_off:,}")

    # 2. 读中央目录
    cd = fetch(args.url, cd_off, cd_off + cd_size - 1)
    entries = parse_central_directory(cd)
    print(f"[*] 解析出 {len(entries)} 个条目")

    # 3. 匹配条目
    candidates = [k for k in entries if k.endswith(args.entry_suffix)]
    if not candidates:
        print(f"[!] 未找到 {args.entry_suffix}")
        print("[*] 包含该关键字的条目：")
        kw = args.entry_suffix.strip("/").split("/")[-1]
        for k in entries:
            if kw in k:
                print(f"    {k}")
        sys.exit(1)

    target = candidates[0]
    e = entries[target]
    print(f"[+] 目标: {target}  ({e['usize']:,} 字节压缩后 {e['csize']:,})")

    # 4. 读 local header 拿文件名/extra 长度
    lh = fetch(args.url, e["lho"], e["lho"] + 29)
    nlen, elen = struct.unpack("<HH", lh[26:30])
    data_off = e["lho"] + 30 + nlen + elen

    # 5. Range 下载压缩数据
    print(f"[*] 下载数据段 {e['csize']:,} 字节...")
    comp = fetch(args.url, data_off, data_off + e["csize"] - 1)

    # 6. 解压
    if e["method"] == 0:
        raw = comp
    elif e["method"] == 8:
        raw = zlib.decompressobj(-15).decompress(comp)
    else:
        raise RuntimeError(f"不支持的压缩方法: {e['method']}")

    with open(args.output, "wb") as f:
        f.write(raw)

    import hashlib
    print(f"[✓] 已保存 {args.output}")
    print(f"    大小: {len(raw):,} 字节 (期望 {e['usize']:,})")
    print(f"    MD5:  {hashlib.md5(raw).hexdigest()}")


if __name__ == "__main__":
    main()
