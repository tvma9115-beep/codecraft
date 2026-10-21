# DCS for Redis 创建参数清单

> **服务全名：分布式缓存服务 DCS**，创建时选 **Redis** 引擎。
> 同样：先用 `python scripts/provision.py probe dcs CreateInstance` 查出本区域真实的参数名。

---

## 一、一次性准备：网络类 ID

与 RDS 完全一样，**必须同区域、同 VPC、同子网**。

| 参数 | 从哪拿 |
|---|---|
| 区域 | 控制台左上角，例如 `cn-north-4` |
| VPC ID | 控制台 → 虚拟私有云 VPC → 我的 VPC → 详情页 |
| 子网 ID | 同上 → 子网标签 |
| 安全组 ID | 控制台 → 虚拟私有云 VPC → 安全组 |
| 可用区 | 与 ECS 同可用区，例如 `cn-north-4a` |

复用 RDS 阶段设置的环境变量即可：

```powershell
$env:HW_REGION            = "cn-north-4"
$env:HW_VPC_ID            = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
$env:HW_SUBNET_ID         = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
$env:HW_SECURITY_GROUP_ID = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

---

## 二、业务参数

| 参数 | 怎么定 | 本项目建议 |
|---|---|---|
| 实例名 | 同 RDS 命名风格 | `codecraft-cache` |
| 引擎 | Redis | Redis |
| 引擎版本 | 控制台默认稳定版 | 5.0 或 6.0+（看控制台提供哪些） |
| **实例类型** | 单机 / 主备 / 集群 | **单机**（演示用，主备是浪费钱） |
| **规格** | 内存容量，各区域不同，用 `probe` 或控制台查 | **1G 单机** 足够 |
| **计费方式** | 同 RDS | **按需** |
| 端口 | 默认 6379 | 6379 |
| 密码 | 创建时指定或创建后设置 | 强密码，存进 `.env.local` |
| 标签 | `Project=<项目名>`、`Owner=<姓名>` | 必加 |
| 公网访问 | **关闭** | 走 VPC 内网 |
| 备份策略 | 演示项目可关闭 | 关（省事省钱） |

---

## 三、为什么这个项目需要 Redis（写材料时用得上）

评委一定会问"你为什么用 Redis"。本项目的四个用途，每个都有不可替代的理由：

| Key | 类型 | 用途 | 为什么不能用 MySQL 代替 |
|---|---|---|---|
| `run:queue` | List | 代码执行任务队列 | 代码执行有**超时风险**，必须与 Web 请求解耦；数据库轮询既慢又给库加压 |
| `run:result:{runId}` | String + TTL 300 | 执行结果暂存 | 结果读取**极高频、生命周期只有秒级**，写数据库是纯浪费 |
| `run:limit:{sessionId}` | String + TTL 60 | 提交频率限制 | **TTL 天然实现滑动窗口**，用 SQL 计数还得自己清理过期记录 |
| `stats:hot_error` | Sorted Set | 最常错的 3 个知识点排行 | `ZINCRBY` 一步完成实时排行，SQL 每次都要 `GROUP BY + ORDER BY` |

**这段话建议原样放进材料的技术方案部分。**

---

## 四、创建后必做

### 1. 设置/确认密码

### 2. 配置白名单

DCS 侧通常有「白名单」或依赖安全组。**确认 ECS 的内网 IP 在允许范围内**，不要放通 `0.0.0.0/0`。

### 3. 验证连通性（在 ECS 上执行）

```bash
apt install -y redis-tools

redis-cli -h <Redis内网地址> -p 6379 -a '<密码>' ping
# 期望返回：PONG
```

再验一下我们要用的四个能力：

```bash
redis-cli -h <地址> -p 6379 -a '<密码>' \
  set run:test hello
redis-cli -h <地址> -p 6379 -a '<密码>' \
  lpush run:queue '{"task":1}'
redis-cli -h <地址> -p 6379 -a '<密码>' \
  zadd stats:hot_error 1 loop-boundary
```

---

## 五、常用命令速查

```bash
# 看接口真实参数名
python scripts/provision.py probe dcs CreateInstance

# 看现有实例
python scripts/provision.py list dcs

# 预览创建
python scripts/provision.py create dcs \
  --name codecraft-cache \
  --arg capacity=1 \
  --arg vpc_id=$HW_VPC_ID \
  --arg subnet_id=$HW_SUBNET_ID \
  --arg security_group_id=$HW_SECURITY_GROUP_ID \
  --dry-run

# 等就绪
python scripts/provision.py wait dcs --id <实例ID>
```

> ⚠️ 容量字段名可能是 `capacity` / `memory` / `spec_code`，**以 `probe` 输出为准**。

---

## 六、和 RDS 的取舍

如果时间紧、只想先开一个：

- **必须先开 RDS**（赛题点名了 RDS，且数据要落地）
- Redis 可以稍后开，先在本机用内存队列代替（代码里做个开关），但**最终提交前一定要接上**——
  赛题第二条明确写了"关联 RDS、REDIS 等华为云服务"，两个都不能缺。
