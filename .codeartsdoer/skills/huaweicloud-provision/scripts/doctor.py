#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""环境体检：确认开通华为云资源所需的条件是否齐备。

用法：
    python scripts/doctor.py [--project-root <路径>] [--no-live]

--no-live  跳过真实 API 调用（离线或不想访问网络时用）

退出码：0 = 可以继续   3 = 有阻塞项
"""

import argparse
import os
import re
import socket
import sys
from pathlib import Path

import hwenv

MIN_PY = (3, 8)
CHECKS = []


def record(name, level, message, fix=""):
    CHECKS.append((name, level, message, fix))


# ------------------------------------------------------------ 检查项


def check_python():
    ver = sys.version_info
    cur = f"{ver.major}.{ver.minor}.{ver.micro}"
    if (ver.major, ver.minor) >= MIN_PY:
        record("Python 版本", "OK", cur)
    else:
        record("Python 版本", "FAIL", cur, f"需要 >= {MIN_PY[0]}.{MIN_PY[1]}")


def check_hcloud_binary():
    path = hwenv.find_hcloud()
    if not path:
        record(
            "hcloud 可执行文件", "FAIL", "未找到 hcloud",
            "按顺序尝试：\n"
            "  1) 把 hcloud 加入 PATH\n"
            "  2) 设置环境变量 HCLOUD_BIN=<hcloud 完整路径>\n"
            "常见位置：" + "; ".join(hwenv.extra_dirs()[:3]),
        )
        return None

    if hwenv.in_path():
        record("hcloud 可执行文件", "OK", f"{path}（已在 PATH 中）")
    else:
        record(
            "hcloud 可执行文件", "WARN",
            f"找到了：{path}\n        但它不在 PATH 中",
            "本技能的脚本会自动使用上面的路径，所以不影响使用。\n"
            "但建议加入 PATH，这样智能体可以直接调用 `hcloud`：\n"
            f"  $env:Path += \";{path.parent}\"   (仅当前会话)\n"
            f"  或永久：把 {path.parent} 加进「用户环境变量 Path」\n"
            f"  或临时：$env:HCLOUD_BIN=\"{path}\"",
        )
    return path


def check_hcloud_version(path):
    if not path:
        return
    code, out, err = hwenv.run(["version"], timeout=30, hcloud_path=path)
    text = (out or err).strip()
    if code == 0:
        record("hcloud 版本", "OK", text.splitlines()[0][:80] if text else "可执行")
    else:
        record("hcloud 版本", "FAIL", f"执行失败：{text[:200]}",
               "重装 KooCLI，或检查文件是否完整")


def check_credentials():
    """凭据可能来自环境变量，也可能来自 KooCLI 的 config.json。"""
    env_ok = hwenv.env_credentials_present()
    hcloud_path = hwenv.find_hcloud()
    cfg = hwenv.find_koocli_config(hcloud_path)

    if env_ok and cfg:
        record("凭据", "OK", f"环境变量已设置 + KooCLI 配置存在（{cfg}）")
    elif env_ok:
        record("凭据", "OK", "环境变量 HUAWEICLOUD_SDK_AK / SK 已设置")
    elif cfg:
        record("凭据", "OK", f"来自 KooCLI 配置文件：{cfg}（无需环境变量）")
    else:
        record(
            "凭据", "FAIL", "既没有环境变量，也没找到 KooCLI 配置",
            "二选一：\n"
            "  a) $env:HUAWEICLOUD_SDK_AK=\"...\"; $env:HUAWEICLOUD_SDK_SK=\"...\"\n"
            "  b) 执行 hcloud configure set 交互式配置 AK/SK",
        )


def check_live(region):
    """真实调一次只读接口 —— 这是唯一能同时验证凭据与网络的方法。"""
    path = hwenv.find_hcloud()
    if not path:
        record("实调用验证", "WARN", "跳过：没有 hcloud")
        return

    code, out, err = hwenv.run(
        ["RDS", "ListInstances", f"--cli-region={region}"],
        timeout=90, hcloud_path=path,
    )
    combined = f"{out}\n{err}".strip()

    if code == 0:
        # 尽量读出实例数，读不到也不影响结论
        detail = "认证有效，接口可用"
        for token in ("total_count", "totalCount"):
            idx = combined.find(token)
            if idx != -1:
                snippet = combined[idx: idx + 40].replace("\n", " ")
                detail += f"（{snippet}）"
                break
        record("实调用验证", "OK", f"RDS ListInstances @ {region} → {detail}")
        return

    kind = hwenv.classify_credential_error(combined)
    fix_by_kind = {
        "auth": "AK/SK 无效或已过期：去控制台「我的凭证」重建，并重新 hcloud configure set",
        "permission": "账号缺少 RDS 权限，或未完成实名认证",
        "network": f"region {region} 的网络不可达。换一个可达的 region，或检查代理/防火墙",
        "parameter": "命令参数或动作名不被识别，先用 `hcloud RDS --help` 确认动作名",
        "unknown": "查看下面的原始输出，按 troubleshooting.md 排查",
    }
    record(
        "实调用验证", "FAIL",
        f"调用失败（exit={code}）\n        原始输出：{combined[:300]}",
        fix_by_kind.get(kind, fix_by_kind["unknown"]),
    )


def check_region():
    region = os.environ.get("HW_REGION", "").strip()
    if region:
        record("区域 HW_REGION", "OK", region)
    else:
        record("区域 HW_REGION", "WARN", "未设置，脚本默认 cn-north-4",
               '$env:HW_REGION="cn-north-4"')


def check_vpc():
    vpc = os.environ.get("HW_VPC_ID", "").strip()
    subnet = os.environ.get("HW_SUBNET_ID", "").strip()
    sg = os.environ.get("HW_SECURITY_GROUP_ID", "").strip()
    if vpc and subnet:
        extra = f"，安全组={sg}" if sg else "（安全组未设）"
        record("VPC / 子网", "OK", f"VPC={vpc}，子网={subnet}{extra}")
    else:
        record(
            "VPC / 子网", "WARN", "还没设置 —— 创建实例时才需要，现在可以先跳过",
            "控制台 → 虚拟私有云 VPC → 查看 VPC / 子网 ID\n"
            "      必须与 ECS 使用同一个 VPC 和子网\n"
            "      $env:HW_VPC_ID=\"...\"; $env:HW_SUBNET_ID=\"...\"",
        )


def check_network():
    try:
        with socket.create_connection(("www.huaweicloud.com", 443), timeout=4):
            record("基础网络", "OK", "www.huaweicloud.com:443 可达")
    except Exception as exc:  # noqa: BLE001
        record("基础网络", "WARN", f"不可达（{exc}）",
               "若使用代理，确认 hcloud 也走代理；否则以实调用验证的结果为准")


def find_project_root(start):
    cur = Path(start).resolve()
    for _ in range(4):
        if (cur / ".git").exists() or (cur / ".codeartsdoer").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return Path(start).resolve()


def check_gitignore(project_root):
    gi = project_root / ".gitignore"
    if not gi.exists():
        record(".gitignore", "WARN", f"{gi} 不存在",
               "至少包含：.env\n.env.*\n!.env.example\n*.pem\n*.key")
        return
    try:
        content = gi.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        record(".gitignore", "WARN", f"读取失败：{exc}")
        return

    lines = {ln.strip() for ln in content.splitlines()}
    has_env = any(ln in (".env", ".env*", ".env.*", "*env*") for ln in lines)
    keep_example = any(ln in ("!.env.example", "!*.env.example") for ln in lines)
    if has_env and keep_example:
        record(".gitignore", "OK", "已忽略 .env，且保留 .env.example")
    elif has_env:
        record(".gitignore", "WARN", "未保留 .env.example", "追加：!.env.example")
    else:
        record(".gitignore", "FAIL", "未忽略 .env，密钥泄漏风险",
               "追加：.env / .env.* / !.env.example / *.pem / *.key")


# 真实的 SK 是一长串字面量（约 40 位）；示例里的 "..." 或 "$env:X" 都不该命中
SECRET_RE = re.compile(
    r"(?:huaweicloud_sdk_sk|access_key_secret|secret_key|secretkey)"
    r"\s*[=:]\s*[\"']?([A-Za-z0-9/+=]{24,})[\"']?",
    re.I,
)
SECRET_SAFE_MARKERS = ("$env:", "os.environ", "getenv", "你的", "your_", "<", "...")


def check_secrets_in_skill():
    skill_dir = Path(__file__).resolve().parent.parent
    hits = []
    for p in skill_dir.rglob("*"):
        if not p.is_file() or p.suffix not in {".py", ".md", ".json", ".yaml", ".yml"}:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if any(marker in line for marker in SECRET_SAFE_MARKERS):
                continue
            if SECRET_RE.search(line):
                hits.append(f"{p.relative_to(skill_dir)}:{i}")
    if hits:
        record("技能目录密钥扫描", "FAIL", "疑似写死密钥：" + ", ".join(hits[:5]),
               "立刻删除并重建该密钥")
    else:
        record("技能目录密钥扫描", "OK", "未发现写死的密钥")


# ------------------------------------------------------------ 入口


def main():
    ap = argparse.ArgumentParser(description="华为云开通环境体检")
    ap.add_argument("--project-root", default=os.getcwd())
    ap.add_argument("--no-live", action="store_true", help="跳过真实 API 调用")
    args = ap.parse_args()

    project_root = find_project_root(args.project_root)
    region = os.environ.get("HW_REGION", "").strip() or "cn-north-4"

    print("=" * 64)
    print(" 华为云资源开通 — 环境体检")
    print(f" 项目根目录：{project_root}")
    print(f" 目标区域  ：{region}")
    print("=" * 64)

    check_python()
    path = check_hcloud_binary()
    check_hcloud_version(path)
    check_credentials()
    if args.no_live:
        record("实调用验证", "WARN", "已跳过（--no-live）")
    else:
        check_live(region)
    check_region()
    check_vpc()
    check_network()
    check_gitignore(project_root)
    check_secrets_in_skill()

    icon = {"OK": "[ OK ]", "WARN": "[WARN]", "FAIL": "[FAIL]"}
    for name, level, message, fix in CHECKS:
        print(f"{icon[level]} {name}: {message}")
        if fix:
            for line in fix.splitlines():
                print(f"        → {line}")

    fails = [c for c in CHECKS if c[1] == "FAIL"]
    warns = [c for c in CHECKS if c[1] == "WARN"]

    print("-" * 64)
    if fails:
        print(f"结论：{len(fails)} 项阻塞、{len(warns)} 项提醒。先解决 [FAIL]。")
        return 3

    print(f"结论：体检通过（{len(warns)} 项提醒）。下一步：")
    print("  python scripts/provision.py list rds")
    print("  python scripts/provision.py probe rds CreateInstance")
    print("  python scripts/provision.py create rds --name <名字> --arg <键>=<值> --dry-run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
