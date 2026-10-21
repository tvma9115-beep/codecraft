---
name: huaweicloud-provision
description: 开通、查询和维护华为云 RDS for MySQL 与 DCS for Redis 实例。当需要为本项目创建数据库或缓存实例、检查已有实例是否可用、获取连接地址与端口、等待实例创建完成、或排查实例连通性问题时使用。不用于创建 ECS、域名、OBS 等其他云服务，也不用于修改实例规格。
---

# 华为云资源开通（RDS / DCS）

## 这个技能解决什么

本项目需要两个云服务：

| 服务 | 产品 | 用途 |
|---|---|---|
| 关系型数据库 | **RDS for MySQL** | 组件知识库、题库、项目、运行记录 |
| 缓存/队列 | **DCS for Redis** | 执行队列、结果缓存、限流、热榜 |

**目标**：把"在控制台点几十下开通实例"变成"对话里一条指令"，并保证规格、网络、计费方式都符合项目约定。

---

## 何时使用这个技能

- 需要**新开通**一个 RDS 或 DCS 实例
- 不确定**已有实例是否还活着**、连接地址是多少
- 实例刚创建，需要**等它变成可用状态**
- 应用连不上数据库/缓存，需要**排查是不是实例侧的问题**

**不要用于**：创建 ECS、申请域名、改实例规格、改计费方式。这些走控制台或别的技能。

---

## 前置条件（缺一条就会失败，先跑体检）

1. 华为云账号**已实名认证**（个人认证通常当天通过）
2. 已获得 **AK/SK**（控制台 → 我的凭证 → 访问密钥）
3. 已安装 **KooCLI**（命令 `hcloud`）
4. **环境变量已设置**：`HUAWEICLOUD_SDK_AK`、`HUAWEICLOUD_SDK_SK`
5. 已知本项目的**区域**（`HW_REGION`，默认 `cn-north-4`）

### 第一步永远是体检

```bash
python scripts/doctor.py
```

它会检查：Python 版本、AK/SK 是否设置、`hcloud` 是否安装、网络是否可达、`.env` 是否已被 `.gitignore` 忽略。

**体检不通过就不要往下走。** 按它输出的修复建议处理，不要靠猜。

---

## 环境变量约定

| 变量 | 必填 | 说明 |
|---|---|---|
| `HUAWEICLOUD_SDK_AK` | 是 | 访问密钥 ID |
| `HUAWEICLOUD_SDK_SK` | 是 | 访问密钥 Key |
| `HW_REGION` | 否 | 默认 `cn-north-4`（华北-北京四） |
| `HW_PROJECT_ID` | 否 | 部分接口需要，体检脚本会提示 |
| `HW_VPC_ID` | 否 | 创建实例时用，建议设为项目变量 |
| `HW_SUBNET_ID` | 否 | 同上 |
| `HW_SECURITY_GROUP_ID` | 否 | 同上 |

> ⚠️ **AK/SK 只能来自环境变量，绝对不能写进脚本、SKILL.md、`.env` 的已提交版本或 Git。**
> 如果发现已被提交：立刻去控制台**删除并重建**密钥——改写 Git 历史不够，密钥已经泄漏了。

---

## 核心流程

### 流程 1：先看清楚现状（永远先做这一步）

```bash
# 列出当前区域已有的 RDS 实例
python scripts/provision.py list rds

# 列出当前区域已有的 DCS 实例
python scripts/provision.py list dcs
```

**如果已经有可用实例，不要重复创建。** 直接跳到「流程 3：拿到连接信息」。

### 流程 2：创建实例

**关键设计：不要凭记忆硬编码参数名。** 华为云 API 各服务、各版本的参数名可能不同。先探明：

```bash
# 查看 RDS CreateInstance 的完整参数说明
python scripts/provision.py probe rds CreateInstance

# 查看 DCS CreateInstance 的完整参数说明
python scripts/provision.py probe dcs CreateInstance
```

然后**先 dry-run 看命令，再执行**：

```bash
# 1) 只打印将要执行的命令，不真的创建
python scripts/provision.py create rds \
  --name codecraft-db \
  --arg flavor=<规格ID> \
  --arg vpc_id=$HW_VPC_ID \
  --arg subnet_id=$HW_SUBNET_ID \
  --arg security_group_id=$HW_SECURITY_GROUP_ID \
  --dry-run

# 2) 确认命令正确后，加 --yes 真的执行
python scripts/provision.py create rds --name codecraft-db --arg flavor=<规格ID> ... --yes
```

`--arg KEY=VALUE` 会原样透传给 `hcloud`（拼成 `--KEY=VALUE`），所以**任何参数都能传，不受脚本写死的限制**。

**具体该传哪些参数、规格 ID 怎么查**，见：
- `references/params-rds.md`
- `references/params-dcs.md`

### 流程 3：等实例就绪

创建是异步的，创建命令返回只代表**任务已提交**。

```bash
python scripts/provision.py wait rds --id <实例ID> --timeout 1800
```

脚本会轮询直到状态可用，或超时退出。

### 流程 4：拿到连接信息并落到项目里

```bash
# 查看实例详情（连接地址、端口等）
python scripts/provision.py show rds --id <实例ID>

# 把连接信息写成项目的 .env.local 模板
python scripts/provision.py env --out .env.local \
  --rds-host <RDS内网地址> --rds-port 3306 \
  --dcs-host <Redis内网地址> --dcs-port 6379
```

**必须向用户明确说明的两件事：**
1. **密码不在 API 返回值里**，需要在控制台或创建时设置，脚本不会也不能替你填
2. **RDS/DCS 用内网地址**，只有同一 VPC 内的 ECS 能访问

---

## 命令参考

| 命令 | 作用 |
|---|---|
| `doctor.py` | 环境体检（独立脚本） |
| `provision.py probe <service> [<action>]` | 打印 `hcloud` 的参数帮助，用于确认参数名 |
| `provision.py list <service>` | 列出实例 |
| `provision.py show <service> --id <ID>` | 查看实例详情 |
| `provision.py create <service> --name <N> --arg K=V ... [--dry-run] [--yes]` | 创建实例 |
| `provision.py wait <service> --id <ID> [--timeout S]` | 轮询直到可用 |
| `provision.py env --out <路径> [--rds-host ...] [--dcs-host ...]` | 生成环境变量模板 |

`<service>` 取值：`rds` 或 `dcs`

**退出码约定**：`0` 成功 ｜ `2` 参数错误 ｜ `3` 缺少依赖或环境未就绪 ｜ `4` 云端返回错误 ｜ `5` 等待超时

---

## 硬性约束（每次创建都要遵守，别问用户要不要）

| 约束 | 值 | 理由 |
|---|---|---|
| **计费方式** | **按需** | 验证阶段别买包年包月，避免退不掉 |
| **规格** | **该服务的最低可用档** | 我们只做队列和缓存，不做压测 |
| **区域** | 与 ECS **完全一致** | 跨区域内网不通 |
| **VPC / 子网** | 与 ECS **完全一致** | 否则 ECS 连不上 |
| **标签** | `Project=<项目名>`、`Owner=<姓名>` | 月底对账、方便清理 |
| RDS 磁盘 | 最低档（如 40G） | 数据量很小 |
| DCS 规格 | 最低档（如 1G 单机） | 只存队列和缓存 |
| **公网访问** | **一律关闭** | 走 VPC 内网。开放公网是安全问题 |

---

## 失败时怎么做

**不要反复重试。** 先看 `references/troubleshooting.md`，按错误码对号入座。

最常见的三类：

| 现象 | 大概率原因 |
|---|---|
| 401 / 403 | AK/SK 错误、权限不足、或**未实名认证** |
| 配额不足 / QuotaExceeded | 该区域实例数达到上限，需提工单 |
| VPC / Subnet not found | 区域选错，或 ID 不属于该区域 |

如果错误信息里出现参数名相关提示，**说明 `hcloud` 的该接口参数与预期不同**——回到流程 2 的 `probe` 重新确认，不要凭猜改参数。

---

## 完成后的输出要求

做完任何一步，都要**明确告诉用户**：

1. 做了什么（创建 / 查询 / 等待）
2. 实例 ID、状态、连接地址与端口
3. 下一步该做什么（例如"去控制台设置密码"）
4. **产生了什么费用**（按需实例从创建那一刻起计费）

---

## 遗留事项（诚实记录，别假装没这回事）

| 事项 | 说明 |
|---|---|
| 实例密码 | API 返回值不含密码，需控制台设置或创建时指定 |
| 规格 ID | 各区域不同，必须用 `probe` 或控制台查，不能写死 |
| 白名单/安全组 | 创建后可能还要在 RDS 侧配置允许访问的 IP，需人工确认 |
| 数据库初始化 | 建库建表不在本技能范围，由应用侧迁移脚本负责 |

---

## 参考资料

| 文件 | 内容 |
|---|---|
| `scripts/validate_skill.py` | **导入前自检**：目录名是否等于 name、description 长度、BOM/CRLF、垃圾文件、5MB 上限、引用完整性 |
| `references/params-rds.md` | RDS for MySQL 创建所需参数清单与获取方式 |
| `references/params-dcs.md` | DCS for Redis 创建所需参数清单与获取方式 |
| `references/troubleshooting.md` | 错误码对照与排查顺序 |

---

## 导入前自检（改过 SKILL.md 后必做）

```bash
# 校验目录形态
python scripts/validate_skill.py

# 校验打包后的 zip（顶层只能有一个技能文件夹）
python scripts/validate_skill.py --zip ../../dist/huaweicloud-provision.zip
```

**最常见的导入失败原因**：zip 里多套了一层目录（顶层变成 `.codeartsdoer` 或 `skills`），
导致实际技能文件夹名与 `name` 不一致。正确结构是 zip 内**直接**是 `huaweicloud-provision/`。
