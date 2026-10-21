#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技能包合规校验：导入 CodeArts 之前先跑一遍，避免"目录名与 name 不一致"这类导入失败。

用法：
    python scripts/validate_skill.py              # 校验自己所在的技能目录
    python scripts/validate_skill.py <技能目录>    # 校验指定目录
    python scripts/validate_skill.py --zip <zip>  # 校验 zip 包的顶层结构

检查项：
  1. 目录名 == SKILL.md 的 name
  2. name 命名规则（小写字母/数字/连字符，1~64，首尾非连字符，无连续连字符）
  3. description 存在且 <= 1024 字符
  4. SKILL.md 无 BOM、无 CRLF
  5. 技能的捆绑资源目录里没有 __pycache__ / .DS_Store 等垃圾
  6. 总大小 <= 5MB（官方导入上限）
  7. SKILL.md 里提到的相对路径文件真实存在
  8. 没有写死的密钥

退出码：0 通过 ｜ 3 不合规
"""

import argparse
import os
import re
import sys
import zipfile
from pathlib import Path

# 小写字母/数字/连字符；连字符不可连续、不可首尾
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SIZE_LIMIT = 5 * 1024 * 1024
JUNK_NAMES = {"__pycache__", ".DS_Store", ".git", "Thumbs.db", ".idea", ".vscode"}

# 真实的 SK 是一长串字面量；示例里的 "..." / "$env:X" 不该命中
SECRET_RE = re.compile(
    r"(?:huaweicloud_sdk_sk|access_key_secret|secret_key|secretkey)"
    r"\s*[=:]\s*[\"']?([A-Za-z0-9/+=]{24,})[\"']?",
    re.I,
)
SECRET_SAFE_MARKERS = ("$env:", "os.environ", "getenv", "你的", "your_", "<", "...")

results = []  # (level, message)


def add(level, message):
    results.append((level, message))


def parse_frontmatter(text):
    if not text.startswith("---"):
        return None, "SKILL.md 必须以 '---' 开头"
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return None, "frontmatter 未正确闭合（需要第二行 '---'）"
    block = m.group(1)
    data = {}
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data, None


def validate_dir(skill_dir):
    skill_dir = Path(skill_dir).resolve()
    dir_name = skill_dir.name

    add("INFO", f"校验目录：{skill_dir}")
    add("INFO", f"目录名：{dir_name}")

    # ---- SKILL.md
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        add("FAIL", f"缺少 SKILL.md（必须在技能目录根下：{md}）")
        return
    raw = md.read_bytes()

    if raw.startswith(b"\xef\xbb\xbf"):
        add("FAIL", "SKILL.md 带 UTF-8 BOM，会导致 frontmatter 解析失败")
    else:
        add("OK", "无 BOM")

    crlf_count = raw.count(b"\r\n")
    if crlf_count:
        add("FAIL", f"SKILL.md 含 CRLF 换行（{crlf_count} 处），建议统一为 LF")
    else:
        add("OK", "换行为 LF")

    text = raw.decode("utf-8-sig")
    fm, err = parse_frontmatter(text)
    if err:
        add("FAIL", err)
        return

    # ---- name
    name = fm.get("name", "")
    add("INFO", f"name 字段：{repr(name)}")

    if not name:
        add("FAIL", "frontmatter 缺少 name")
    elif name != dir_name:
        add(
            "FAIL",
            f"目录名与 name 不一致：目录={dir_name!r}，name={name!r}\n"
            f"       官方要求 name 必须与 skill-name（目录名）保持一致",
        )
    else:
        add("OK", f"目录名 == name（{name}）")

    if name:
        if not (1 <= len(name) <= 64):
            add("FAIL", f"name 长度 {len(name)}，要求 1~64")
        elif not NAME_RE.match(name):
            add(
                "FAIL",
                f"name 命名不合规：{name!r}\n"
                "       只允许小写字母、数字、连字符；首尾不能是连字符；连字符不可连续",
            )
        else:
            add("OK", "name 命名合规")

    # ---- description
    desc = fm.get("description", "")
    if not desc:
        add("FAIL", "frontmatter 缺少 description")
    elif len(desc) > 1024:
        add("FAIL", f"description 长度 {len(desc)}，超过 1024 字符上限")
    else:
        add("OK", f"description 长度 {len(desc)}（上限 1024）")

    # ---- 垃圾文件
    junk = []
    total = 0
    for root, dirs, files in os.walk(skill_dir):
        for d in list(dirs):
            if d in JUNK_NAMES or d.startswith("."):
                junk.append(str(Path(root, d).relative_to(skill_dir)))
        for f in files:
            if f in JUNK_NAMES:
                junk.append(str(Path(root, f).relative_to(skill_dir)))
            else:
                total += Path(root, f).stat().st_size

    if junk:
        add("WARN", "包含不应打包的生成物：" + ", ".join(junk[:8]) +
            "\n       打包脚本会自动排除它们；也可以手动删掉")
    else:
        add("OK", "无 __pycache__ / 隐藏目录等垃圾")

    if total > SIZE_LIMIT:
        add("FAIL", f"总大小 {total / 1024 / 1024:.2f} MB，超过 5MB 导入上限")
    else:
        add("OK", f"总大小 {total / 1024:.1f} KB（上限 5MB）")

    # ---- 引用完整性
    missing = []
    for rel in re.findall(r"`((?:references|scripts|assets)/[^`\s]+)`", text):
        if not (skill_dir / rel).exists():
            missing.append(rel)
    if missing:
        add("WARN", "SKILL.md 引用了不存在的文件：" + ", ".join(sorted(set(missing))))
    else:
        add("OK", "SKILL.md 引用的文件均存在")

    # ---- 密钥扫描
    hits = []
    for p in skill_dir.rglob("*"):
        if not p.is_file() or p.suffix not in {".py", ".md", ".json", ".yaml", ".yml"}:
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        for i, line in enumerate(content.splitlines(), 1):
            if any(marker in line for marker in SECRET_SAFE_MARKERS):
                continue
            if SECRET_RE.search(line):
                hits.append(f"{p.relative_to(skill_dir)}:{i}")
    if hits:
        add("FAIL", "疑似写死密钥：" + ", ".join(hits[:5]))
    else:
        add("OK", "未发现写死的密钥")


def validate_zip(zip_path):
    zip_path = Path(zip_path).resolve()
    add("INFO", f"校验 zip：{zip_path}")
    if not zip_path.is_file():
        add("FAIL", "文件不存在")
        return

    if zip_path.stat().st_size > SIZE_LIMIT:
        add("FAIL", f"zip 大小 {zip_path.stat().st_size / 1024 / 1024:.2f} MB，超过 5MB")

    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n and not n.endswith("/")]
        if not names:
            add("FAIL", "zip 是空的")
            return

        tops = {n.split("/", 1)[0] for n in names}
        add("INFO", f"顶层条目：{sorted(tops)}")

        if len(tops) > 1:
            add(
                "FAIL",
                f"zip 顶层有多个条目 {sorted(tops)}，官方要求单次一个 zip，"
                "且顶层应只有一个技能文件夹",
            )
        else:
            top = tops.pop()
            if top in {".codeartsdoer", "skills"}:
                add(
                    "FAIL",
                    f"zip 顶层是 {top!r}，多套了一层目录——这正是「目录名与 name 不一致」的典型原因。\n"
                    f"       zip 内应为：{top}/… 改成直接是技能文件夹本身",
                )
            else:
                add("OK", f"zip 顶层只有一个文件夹：{top}")
                # 该文件夹里必须有 SKILL.md
                if f"{top}/SKILL.md" not in names:
                    add("FAIL", f"zip 里 {top}/SKILL.md 不存在（SKILL.md 必须在技能文件夹根下）")
                else:
                    add("OK", f"{top}/SKILL.md 存在")
                    # 核对 name
                    with zipfile.ZipFile(zip_path) as z2:
                        content = z2.read(f"{top}/SKILL.md").decode("utf-8-sig")
                    fm, err = parse_frontmatter(content)
                    if err:
                        add("FAIL", err)
                    elif fm.get("name") != top:
                        add(
                            "FAIL",
                            f"zip 内目录名 {top!r} 与 SKILL.md 的 name {fm.get('name')!r} 不一致",
                        )
                    else:
                        add("OK", f"zip 内目录名 == name（{top}），可直接导入")

        junk = [n for n in names if "__pycache__" in n or n.endswith(".DS_Store")]
        if junk:
            add("WARN", "zip 内包含垃圾文件：" + ", ".join(junk[:5]))


def main():
    ap = argparse.ArgumentParser(description="CodeArts 技能包合规校验")
    ap.add_argument("path", nargs="?", help="技能目录，默认取本脚本所在技能")
    ap.add_argument("--zip", dest="zip_path", help="校验 zip 包")
    args = ap.parse_args()

    if args.zip_path:
        validate_zip(args.zip_path)
    else:
        skill_dir = args.path or Path(__file__).resolve().parent.parent
        validate_dir(skill_dir)

    icon = {"OK": "[ OK ]", "WARN": "[WARN]", "FAIL": "[FAIL]", "INFO": "[INFO]"}
    for level, msg in results:
        for i, line in enumerate(msg.splitlines()):
            prefix = icon[level] + " " if i == 0 else "       "
            print(f"{prefix}{line}")

    fails = [r for r in results if r[0] == "FAIL"]
    warns = [r for r in results if r[0] == "WARN"]
    print("-" * 60)
    if fails:
        print(f"结论：不合规，{len(fails)} 项必须修复，{len(warns)} 项提醒。")
        return 3
    print(f"结论：合规，可以导入（{len(warns)} 项提醒）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
