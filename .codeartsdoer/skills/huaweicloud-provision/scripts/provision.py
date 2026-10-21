#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""华为云 RDS / DCS 开通辅助工具（KooCLI 薄封装，仅依赖标准库）。

设计原则：
  1. 不硬编码任何参数名 —— 用 `probe` 在运行时从 hcloud 查出真实参数；
  2. 只依赖极少数 API 动作名（ListInstances / CreateInstance），
     其余能力都通过读取 ListInstances 的结果实现，降低版本差异风险；
  3. 创建默认是 dry-run，必须显式 --yes 才会真正执行；
  4. 密钥只从环境变量读取，绝不落盘。

用法示例：
  python scripts/provision.py probe rds CreateInstance
  python scripts/provision.py list rds
  python scripts/provision.py create rds --name codecraft-db --arg flavor=xxx --dry-run
  python scripts/provision.py create rds --name codecraft-db --arg flavor=xxx --yes
  python scripts/provision.py wait rds --id <实例ID>
  python scripts/provision.py show rds --id <实例ID>
  python scripts/provision.py env --out .env.local --rds-host 192.168.0.10

退出码：0 成功 ｜ 2 参数错误 ｜ 3 依赖或环境未就绪 ｜ 4 云端返回错误 ｜ 5 等待超时
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import hwenv

DEFAULT_REGION = "cn-north-4"

# 服务映射：短名 -> (hcloud 服务名, 列表动作, 创建动作)
SERVICES = {
    "rds": ("RDS", "ListInstances", "CreateInstance"),
    "dcs": ("DCS", "ListInstances", "CreateInstance"),
}

READY_STATES = {"ACTIVE", "AVAILABLE", "NORMAL", "RUNNING", "SUCCESS"}


# ---------------------------------------------------------------- 基础工具


def die(code, message):
    print(f"[错误] {message}", file=sys.stderr)
    sys.exit(code)


def region():
    return os.environ.get("HW_REGION", DEFAULT_REGION).strip() or DEFAULT_REGION


def require_hcloud():
    """定位 hcloud：不要求它在 PATH 里，HCLOUD_BIN 或已知安装目录都认。"""
    path = hwenv.find_hcloud()
    if not path:
        die(
            3,
            "未找到 hcloud 可执行文件。\n"
            "按顺序试：\n"
            "  1) $env:HCLOUD_BIN=\"<hcloud 完整路径>\"\n"
            "  2) 把 hcloud 所在目录加入 PATH，重开终端\n"
            "体检：python scripts/doctor.py",
        )
    return str(path)


def require_credentials():
    """凭据可来自环境变量，也可来自 KooCLI 的 config.json。"""
    if hwenv.env_credentials_present():
        return
    if hwenv.find_koocli_config(hwenv.find_hcloud()):
        return
    die(
        3,
        "没有可用凭据：环境变量 HUAWEICLOUD_SDK_AK/SK 未设置，"
        "也没找到 KooCLI 配置文件。\n"
        "解决办法二选一：\n"
        "  a) 设置环境变量\n"
        "  b) 执行 hcloud configure set\n"
        "体检：python scripts/doctor.py",
    )


def _decode(raw):
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def run_hcloud(args, timeout=180, dry=False):
    binary = require_hcloud()
    args = list(args)
    # 大响应接口（如 ListFlavors 返回 139KB）默认读超时不够，会报"调用API超时"
    if "--help" not in args and not any(a.startswith("--cli-read-timeout") for a in args):
        args.append(f"--cli-read-timeout={os.environ.get('HW_CLI_READ_TIMEOUT', '120')}")
    cmd = [binary] + args
    printable = " ".join(
        a if (" " not in a and "\t" not in a) else f'"{a}"' for a in cmd
    )
    if dry:
        print("[dry-run] " + printable)
        return 0, ""

    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=timeout, shell=False
        )
    except subprocess.TimeoutExpired:
        die(4, f"hcloud 执行超时（{timeout}s）：{printable}")
    except FileNotFoundError:
        die(3, "调用 hcloud 失败：命令不存在")

    out = _decode(proc.stdout).strip()
    err = _decode(proc.stderr).strip()

    if proc.returncode != 0:
        print(f"[命令] {printable}", file=sys.stderr)
        if out:
            print(out, file=sys.stderr)
        if err:
            print(err, file=sys.stderr)
        die(
            4,
            f"hcloud 返回非零退出码 {proc.returncode}。\n"
            "请对照 references/troubleshooting.md 排查。\n"
            "如果提示参数名不被识别，执行 probe 重新确认接口参数，不要凭猜改参数。",
        )
    return 0, out


# ---------------------------------------------------------------- JSON 处理


def parse_json(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # hcloud 有时在 JSON 前后夹带提示行，尝试截取第一个 { 到最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def walk_dicts(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk_dicts(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_dicts(item)


def find_by_id(data, target_id):
    """在任意嵌套结构里找出所有「某个字段值等于 target_id」的对象。"""
    if not target_id:
        return []
    hits = []
    for obj in walk_dicts(data):
        for value in obj.values():
            if isinstance(value, str) and value == target_id:
                hits.append(obj)
                break
    return hits


def looks_like_instance(obj):
    keys = {k.lower() for k in obj.keys()}
    return bool(keys & {"id", "instanceid", "instance_id", "name"})


def collect_instances(data):
    """从 ListInstances 的返回里挑出实例对象列表。"""
    if data is None:
        return []
    candidates = []
    for key in ("instances", "Instances", "instance_list", "records", "data"):
        node = data.get(key) if isinstance(data, dict) else None
        if isinstance(node, list):
            candidates.extend(x for x in node if isinstance(x, dict))
    if candidates:
        return candidates
    # 兜底：找最像实例的字典
    return [o for o in walk_dicts(data) if looks_like_instance(o)]


def pick_status(obj):
    for key in ("status", "Status", "state", "State", "statusText"):
        if key in obj and isinstance(obj[key], str):
            return obj[key]
    return ""


def summarize(obj):
    """挑几个关键字段用于人类阅读。"""
    interesting = (
        "id", "Id", "ID", "instanceId", "instance_id", "name", "Name",
        "status", "Status", "state", "State", "engine", "engineVersion",
        "type", "flavor", "flavorRef", "privateIp", "private_ips", "ip",
        "port", "Port", "endpoint", "connection_string",
    )
    out = {}
    for key, value in obj.items():
        if key in interesting and not isinstance(value, (dict, list)):
            out[key] = value
    return out or obj


# ---------------------------------------------------------------- 子命令


def cmd_probe(args):
    svc, _list_action, _create_action = SERVICES[args.service]
    require_hcloud()
    if args.action:
        print(f"# hcloud {svc} {args.action} --help")
        code, out = run_hcloud(
            [svc, args.action, "--help"], timeout=60, dry=args.dry_run
        )
    else:
        print(f"# hcloud {svc} --help")
        code, out = run_hcloud([svc, "--help"], timeout=60, dry=args.dry_run)
    if out:
        print(out)
    else:
        print("（没有输出。若参数/动作名不被识别，请用 `hcloud --help` 查看可用服务名）")
    return 0


def fetch_instances(service, dry=False):
    svc, list_action, _ = SERVICES[service]
    args = [svc, list_action, f"--cli-region={region()}"]
    _code, out = run_hcloud(args, timeout=120, dry=dry)
    if dry:
        return None, None
    data = parse_json(out)
    if data is None:
        print("[提示] 返回值不是合法 JSON，原样输出如下：")
        print(out)
        return None, None
    return data, collect_instances(data)


def cmd_list(args):
    require_hcloud()
    require_credentials()
    data, instances = fetch_instances(args.service, dry=args.dry_run)
    if args.dry_run:
        return 0
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    if not instances:
        print(f"当前区域（{region()}）没有查到 {args.service.upper()} 实例。")
        print("如果需要创建，先 probe 确认参数，再用 create 的 --dry-run 预览。")
        return 0

    print(f"区域 {region()} 共 {len(instances)} 个 {args.service.upper()} 实例：")
    for i, inst in enumerate(instances, 1):
        info = summarize(inst)
        print(f"\n  [{i}]")
        for key, value in info.items():
            print(f"      {key}: {value}")
    return 0


def cmd_show(args):
    require_hcloud()
    require_credentials()
    data, instances = fetch_instances(args.service, dry=args.dry_run)
    if args.dry_run:
        return 0
    if data is None:
        return 4

    hits = find_by_id(data, args.id)
    if not hits:
        print(f"未找到 ID 为 {args.id} 的 {args.service.upper()} 实例。")
        print("可用 list 子命令查看现有实例的 ID。")
        return 4

    obj = hits[0]
    print(f"实例详情（{args.service.upper()}）：")
    for key, value in summarize(obj).items():
        print(f"  {key}: {value}")
    if args.json:
        print("\n完整原始对象：")
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    return 0


def cmd_create(args):
    require_hcloud()
    require_credentials()
    svc, _list_action, create_action = SERVICES[args.service]

    cmd = [svc, create_action, f"--cli-region={region()}"]

    if args.name:
        cmd.append(f"--name={args.name}")

    extra = {}
    for item in args.arg or []:
        if "=" not in item:
            die(2, f"--arg 需要 KEY=VALUE 形式，收到：{item}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            die(2, f"--arg 的键不能为空：{item}")
        extra[key] = value
        cmd.append(f"--{key}={value}")

    # 自动补项目标签（如果调用方没自己给）
    if not any(k.lower() in {"tags", "tag"} for k in extra):
        print("# 提醒：本次未传 tags 参数，建议补 --arg tags=<项目名> 以便对账与清理")

    print(f"# 将执行：hcloud {' '.join(cmd)}")

    if not args.yes:
        print("\n[dry-run] 未加 --yes，仅预览，不执行。")
        print("确认参数无误后，在命令末尾加 --yes 真正创建。")
        print("\n创建前请自查：")
        print("  - 计费方式是否为按需（避免买了退不掉）")
        print("  - 区域 / VPC / 子网是否与 ECS 完全一致")
        print("  - 规格是否为最低可用档")
        return 0

    print("\n开始创建（按需计费，从此刻开始产生费用）…")
    _code, out = run_hcloud(cmd, timeout=args.timeout)
    data = parse_json(out)
    if data is not None:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        ids = [
            v for o in walk_dicts(data)
            for k, v in o.items()
            if k.lower() in {"id", "instanceid", "instance_id"} and isinstance(v, str)
        ]
        if ids:
            print(f"\n实例 ID：{ids[0]}")
            print(f"下一步：python scripts/provision.py wait {args.service} --id {ids[0]}")
    else:
        print(out)

    print("\n完成。请注意：")
    print("  1) 密码不在 API 返回值里，需要去控制台设置或在创建参数里指定")
    print("  2) RDS/DCS 使用内网地址，只有同 VPC 的 ECS 能访问")
    print("  3) 别忘了配置 RDS 白名单 / 安全组")
    return 0


def cmd_wait(args):
    require_hcloud()
    require_credentials()
    deadline = time.time() + args.timeout
    last = ""
    attempt = 0

    print(f"等待 {args.service.upper()} 实例 {args.id} 就绪（最多 {args.timeout}s）…")

    while True:
        attempt += 1
        data, _instances = fetch_instances(args.service)
        if data is not None:
            hits = find_by_id(data, args.id)
            if hits:
                status = pick_status(hits[0]) or "未知"
                if status != last:
                    print(f"  [{attempt}] 状态：{status}")
                    last = status
                if status.upper() in READY_STATES:
                    print(f"\n实例已就绪：{status}")
                    print(f"查看连接信息：python scripts/provision.py show {args.service} --id {args.id}")
                    return 0
            elif attempt == 1:
                print("  暂未在列表中查到该实例，可能刚提交还在排队…")

        if time.time() >= deadline:
            print(f"\n[超时] {args.timeout}s 内未等到就绪状态（最后状态：{last or '未知'}）。")
            print("建议：去控制台确认实例是否创建失败，或适当加大 --timeout。")
            return 5

        time.sleep(args.interval)


ENV_TEMPLATE = """# ---------------------------------------------------------------------------
# 本地开发环境变量（此文件不应提交到 Git）
# 由 huaweicloud-provision 技能生成，请补齐三处密码后使用
# ---------------------------------------------------------------------------

# ---- RDS for MySQL ----
DB_HOST={rds_host}
DB_PORT={rds_port}
DB_USER={rds_user}
DB_PASSWORD=<在此填写 RDS 密码>
DB_NAME={db_name}

# ---- DCS for Redis ----
REDIS_HOST={dcs_host}
REDIS_PORT={dcs_port}
REDIS_PASSWORD=<在此填写 Redis 密码>
REDIS_DB=0

# ---- 应用 ----
NODE_ENV=development
PORT=3000

# ---- 注意 ----
# 1. 以上地址均为内网地址，只能从同一 VPC 内的 ECS 访问
# 2. 不要把此文件的真实内容提交到仓库；仓库里应只有 .env.example
# 3. AK/SK 不要写在这里，使用环境变量 HUAWEICLOUD_SDK_AK / HUAWEICLOUD_SDK_SK
"""


def cmd_env(args):
    out_path = Path(args.out)
    if out_path.exists() and not args.force:
        die(2, f"{out_path} 已存在。确认要覆盖请加 --force")

    text = ENV_TEMPLATE.format(
        rds_host=args.rds_host or "127.0.0.1",
        rds_port=args.rds_port or "3306",
        rds_user=args.rds_user or "root",
        db_name=args.db_name or "codecraft",
        dcs_host=args.dcs_host or "127.0.0.1",
        dcs_port=args.dcs_port or "6379",
    )
    out_path.write_text(text, encoding="utf-8")
    print(f"已写入：{out_path.resolve()}")
    print("请补齐 DB_PASSWORD 与 REDIS_PASSWORD 两处，并确认该文件已被 .gitignore 忽略。")
    return 0


# ---------------------------------------------------------------- 入口


def build_parser():
    ap = argparse.ArgumentParser(
        description="华为云 RDS / DCS 开通辅助工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python scripts/provision.py list rds\n"
            "  python scripts/provision.py probe rds CreateInstance\n"
            "  python scripts/provision.py create rds --name db1 --arg flavor=xxx --dry-run\n"
            "  python scripts/provision.py wait rds --id <ID>\n"
            "  python scripts/provision.py env --out .env.local --rds-host 192.168.0.10\n"
        ),
    )
    sub = ap.add_subparsers(dest="command", required=True)

    common = {"choices": sorted(SERVICES), "help": "服务：rds 或 dcs"}

    p = sub.add_parser("probe", help="打印 hcloud 的接口参数帮助")
    p.add_argument("service", **common)
    p.add_argument("action", nargs="?", help="接口动作名，例如 CreateInstance")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("list", help="列出实例")
    p.add_argument("service", **common)
    p.add_argument("--json", action="store_true", help="输出原始 JSON")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show", help="查看单个实例详情")
    p.add_argument("service", **common)
    p.add_argument("--id", required=True)
    p.add_argument("--json", action="store_true", help="附带完整原始对象")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("create", help="创建实例（默认 dry-run）")
    p.add_argument("service", **common)
    p.add_argument("--name", help="实例名")
    p.add_argument(
        "--arg", action="append", metavar="KEY=VALUE",
        help="透传给 hcloud 的参数，可重复，例如 --arg flavor=xxx",
    )
    p.add_argument("--yes", action="store_true", help="真正执行（不加则只预览）")
    p.add_argument("--dry-run", action="store_true", help="显式预览（默认为预览，等价于不加 --yes）")
    p.add_argument("--timeout", type=int, default=600, help="执行超时秒数")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("wait", help="轮询直到实例就绪")
    p.add_argument("service", **common)
    p.add_argument("--id", required=True)
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--interval", type=int, default=15)
    p.set_defaults(func=cmd_wait)

    p = sub.add_parser("env", help="生成 .env.local 模板")
    p.add_argument("--out", default=".env.local")
    p.add_argument("--rds-host")
    p.add_argument("--rds-port")
    p.add_argument("--rds-user")
    p.add_argument("--db-name")
    p.add_argument("--dcs-host")
    p.add_argument("--dcs-port")
    p.add_argument("--force", action="store_true", help="覆盖已存在的文件")
    p.set_defaults(func=cmd_env)

    return ap


def main():
    ap = build_parser()
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
