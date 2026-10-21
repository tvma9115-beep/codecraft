#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""环境探测工具：定位 hcloud 可执行文件、判断凭据来源。

被 doctor.py 和 provision.py 共用。

设计要点：
  - hcloud 不一定在 PATH 里（常见于解压即用的绿色版），所以除了 PATH 还要查已知安装目录
  - 凭据可能来自环境变量，也可能来自 KooCLI 自己的 config.json（且是加密存储）
  - 因此**不解析凭据内容**，只判断"有没有"，真正的验证交给一次 live 调用
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

EXE = "hcloud.exe" if os.name == "nt" else "hcloud"

# 常见安装位置（解压即用 / 安装包 / 官方安装器）
KNOWN_DIRS = [
    r"D:\huaweicloud-cli-windows-amd64",
    r"C:\huaweicloud-cli-windows-amd64",
    r"D:\huaweicloud-cli",
    r"C:\huaweicloud-cli",
    r"C:\Program Files\HuaweiCloud\KooCLI",
    r"C:\Program Files (x86)\HuaweiCloud\KooCLI",
]

# KooCLI 配置文件的候选位置
CONFIG_CANDIDATES = [
    os.path.join(os.path.expanduser("~"), ".hcloud", "config.json"),
    os.path.join(os.path.expanduser("~"), ".hcloud", "config.json.enc"),
    os.path.join(os.path.expanduser("~"), ".huaweicloud", "config.json"),
]


def extra_dirs():
    """把可能存在的额外目录也纳入候选。"""
    dirs = list(KNOWN_DIRS)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(os.path.join(local, "HuaweiCloud", "KooCLI"))
    roaming = os.environ.get("APPDATA")
    if roaming:
        dirs.append(os.path.join(roaming, "HuaweiCloud", "KooCLI"))
    return [d for d in dirs if d]


def find_hcloud():
    """返回 hcloud 的绝对路径；找不到返回 None。

    优先级：HCLOUD_BIN 环境变量 > PATH > 已知目录
    """
    env_bin = os.environ.get("HCLOUD_BIN", "").strip().strip('"')
    if env_bin:
        p = Path(env_bin)
        if p.is_file():
            return p
        if p.is_dir() and (p / EXE).is_file():
            return p / EXE

    which = shutil.which("hcloud")
    if which:
        return Path(which)

    for d in extra_dirs():
        p = Path(d) / EXE
        if p.is_file():
            return p

    return None


def hcloud_cmd():
    """返回可直接用于 subprocess 的命令前缀。"""
    found = find_hcloud()
    return str(found) if found else "hcloud"


def in_path():
    return bool(shutil.which("hcloud"))


def find_koocli_config(hcloud_path=None):
    """找出 KooCLI 的配置文件（只判断存在，不解析加密内容）。"""
    env_cfg = os.environ.get("HCLOUD_CONFIG", "").strip().strip('"')
    candidates = []
    if env_cfg:
        candidates.append(env_cfg)
    candidates.extend(CONFIG_CANDIDATES)
    if hcloud_path:
        base = Path(hcloud_path).parent
        candidates.append(str(base / "config.json"))
        candidates.append(str(base / ".hcloud" / "config.json"))

    for c in candidates:
        if c and Path(c).is_file():
            return Path(c)
    return None


def env_credentials_present():
    return bool(
        os.environ.get("HUAWEICLOUD_SDK_AK", "").strip()
        and os.environ.get("HUAWEICLOUD_SDK_SK", "").strip()
    )


def run(args, timeout=120, hcloud_path=None):
    """执行 hcloud 命令，返回 (returncode, stdout, stderr)。不抛异常。"""
    binary = str(hcloud_path) if hcloud_path else hcloud_cmd()
    try:
        proc = subprocess.run(
            [binary] + args, capture_output=True, timeout=timeout, shell=False
        )
    except subprocess.TimeoutExpired:
        return 124, "", f"命令超时（{timeout}s）"
    except FileNotFoundError:
        return 127, "", f"找不到可执行文件：{binary}"
    except Exception as exc:  # noqa: BLE001
        return 1, "", str(exc)

    return proc.returncode, _decode(proc.stdout), _decode(proc.stderr)


def _decode(raw):
    if not raw:
        return ""
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def classify_credential_error(text):
    """把一次失败的调用归类，便于给出可执行的建议。"""
    low = text.lower()
    if any(k in low for k in ("401", "apigw.0301", "unauthorized", "ak/sk", "鉴权", "认证失败")):
        return "auth"
    if any(k in low for k in ("403", "apigw.0302", "forbidden", "无权")):
        return "permission"
    if any(k in low for k in ("timeout", "timed out", "timedout", "connect", "dns", "unreachable")):
        return "network"
    if any(k in low for k in ("not found", "unknown", "invalid", "parameter")):
        return "parameter"
    return "unknown"


if __name__ == "__main__":
    # 自检入口：python hwenv.py
    print("hcloud 路径 :", find_hcloud())
    print("是否在 PATH :", in_path())
    print("KooCLI 配置 :", find_koocli_config(find_hcloud()))
    print("环境变量凭据:", env_credentials_present())
    print("PYTHONIOENCODING" in os.environ, sys.version.split()[0])
