# RDS for MySQL 创建参数清单

> **不要凭记忆填参数。** 先用 `python scripts/provision.py probe rds CreateInstance` 查出本区域、本版本真实的参数名，再对照本表确认哪些必填。

---

## 一、一次性准备：拿到这些 ID

创建实例需要的网络类 ID 都不在华为云控制台的显眼处，先把它们抄下来。

| 参数 | 从哪拿 |
|---|---|
| **区域（region）** | 控制台左上角区域选择器。例如 `cn-north-4`（华北-北京四）。**必须与 ECS 完全相同** |
| **VPC ID** | 控制台 → 虚拟私有云 VPC → 我的 VPC → 点进目标 VPC，详情页有 ID |
| **子网 ID** | 同上，VPC 详情页 → 子网标签 → 目标子网的 ID |
| **安全组 ID** | 控制台 → 虚拟私有云 VPC → 安全组 → 目标安全组的 ID |
| **可用区（availability_zone）** | 创建 ECS 时选的那个可用区，例如 `cn-north-4a`。**与 ECS 同可用区延迟最低** |

把这几个值设为环境变量，后续命令就不用反复粘贴：

```powershell
$env:HW_REGION              = "cn-north-4"
$env:HW_VPC_ID              = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
$env:HW_SUBNET_ID           = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
$env:HW_SECURITY_GROUP_ID   = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

---

## 二、业务参数

| 参数 | 怎么定 | 本项目建议 |
|---|---|---|
| 实例名 | 自定义，字母开头，见名知意 | `codecraft-db` |
| 数据库引擎 | `MySQL` | MySQL |
| 引擎版本 | 选控制台默认的稳定版 | 5.7 或 8.0（团队熟悉哪个选哪个） |
| **规格（flavor）** | **各区域、各版本不同，不能写死**。用 `probe`、控制台购买页的下拉框，或 `hcloud RDS ListFlavors` 查 | **该列表里最低的通用型** |
| 存储类型 | 默认 | 云盘（SSD）即可 |
| 存储空间 | 最小档 | 40G |
| **计费方式** | 见下方「按需 vs 包月」 | **按需** |
| 实例类型 | 单机 / 主备 | **单机**（我们是演示，不是生产） |
| 端口 | 默认 3306 | 3306 |
| 密码 | **创建时就要给，或创建后去控制台设** | 用强密码，存进 `.env.local`，不进 Git |
| 标签 | `Project=<项目名>`、`Owner=<姓名>` | 必加，方便对账与清理 |
| 公网访问 | **关闭** | 走 VPC 内网 |

### 按需 vs 包月

| | 按需 | 包月 |
|---|---|---|
| 适合 | **前 3–5 天验证阶段** | 验证通过后、需要挂到 11/30 之后 |
| 优点 | 随时可删，试错成本低 | 通常更便宜 |
| 注意 | 删实例前先备份（我们没重要数据，一般不需要） | **一次买够，别只买 1 个月**，评审期链接不能断 |

**本项目建议路径**：先按需最低配 → 跑通 → 确认要长期用 → 改包月覆盖到 **12 月中旬**。

---

## 三、创建后必做的三件事（脚本不会替你做）

### 1. 设置密码

创建时没指定密码的话，去控制台 → RDS 实例 → 重置密码。

### 2. 配置白名单 / 安全组

- RDS 侧有「白名单」设置，需要允许 ECS 的内网 IP（或直接放通整个子网段）
- **不要**为了省事填 `0.0.0.0/0`

### 3. 建库建表

```sql
CREATE DATABASE codecraft CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

表结构由应用侧的迁移脚本负责，不在本技能范围。

---

## 四、验证连通性

在 **ECS 上**（不是在你自己电脑上）执行：

```bash
# 装个客户端
apt install -y mysql-client

# 用内网地址连
mysql -h <RDS内网地址> -P 3306 -u root -p
```

连不上的排查顺序见 `troubleshooting.md`。

---

## 五、常用命令速查

```bash
# 看接口真实参数名
python scripts/provision.py probe rds CreateInstance

# 看现有实例
python scripts/provision.py list rds

# 预览创建命令（不执行）
python scripts/provision.py create rds \
  --name codecraft-db \
  --arg flavor=<规格ID> \
  --arg vpc_id=$HW_VPC_ID \
  --arg subnet_id=$HW_SUBNET_ID \
  --arg security_group_id=$HW_SECURITY_GROUP_ID \
  --arg availability_zone=cn-north-4a \
  --dry-run

# 确认后执行
python scripts/provision.py create rds --name codecraft-db --arg flavor=<规格ID> ... --yes

# 等就绪
python scripts/provision.py wait rds --id <实例ID>
```

> ⚠️ 参数名（`flavor` / `flavor_ref` / `spec_code` 之类）在不同 API 版本可能不同。
> **以 `probe` 的输出为准**，本表只说明"需要哪些信息"，不保证字段名。

---

## 六、成本提醒

- 按需实例**从创建那一刻开始计费**，不是从第一次连接开始
- 验证完不用的实例**当天删**，别忘
- 月底在费用中心按 `Project` 标签筛选，一眼看清这个项目花了多少
