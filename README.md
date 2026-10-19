# CodeCraft 积木教练

> **积木把「语法错误」消灭了，于是学生失去了最重要的学习信号。**

一个「拼得出、跑得动、讲得清」的积木编程教练：积木负责语法，云端运行暴露逻辑问题，AI 只讲错因、不给答案。

核心能力是**从运行错误回溯到具体积木块**：系统生成 Python 代码时同步记录 source map（行号 ↔ blockId），代码报错时把 traceback 行号映射回学生拖的那块积木并高亮，再按三级提示阶梯引导思考。

---

## 当前状态

| 里程碑 | 状态 |
|---|---|
| G1 平台打通（10/21） | 🚧 进行中 |
| G2 source map 验证（10/24） | ⬜ 未开始 |
| P2 最小闭环 / G3（11/03） | ⬜ 未开始 |
| P3 诊断与题库 / G4（11/13） | ⬜ 未开始 |
| v1.0 发布冻结（11/20） | ⬜ 未开始 |

> 本仓库目前是**目录骨架**，业务代码从 P2（10/25）开始落地。

---

## 目录结构

```
CodeCraft/
├── frontend/       Blockly 工作台（Vite + React + TypeScript）
├── api/            后端 API（Express + TypeScript）
├── worker/         执行队列消费者（BRPOP → 调度沙箱）
├── sandbox/        Python 执行沙箱镜像（Dockerfile + 执行器）
├── infra/          docker-compose、nginx 配置、部署脚本
├── db/             建表 SQL 与种子数据
├── data/           题库、组件讲解、错因模板（JSON）
├── docs/
│   ├── gates/      G1–G4 闸门记录
│   ├── metrics/    指标口径与实测结果
│   └── DECISIONS.md  范围与减量的决策日志
└── 留痕/            CodeArts/Skill 使用证据（申报材料用）
    ├── 01-需求理解/
    ├── 02-代码生成/
    ├── 03-项目构建/
    ├── 04-问题修复/
    └── 05-部署上线/
```

---

## 本地启动

> ⚠️ 依赖 P2 阶段完成后才可用。当前骨架阶段只保证目录与约定就位。

### 环境要求

| 依赖 | 版本 |
|---|---|
| Node.js | ≥ 20 |
| Docker + Docker Compose | 最新稳定版 |
| MySQL | 8.0（本地可用 Docker 起） |
| Redis | 5.0+ |

### 步骤

```bash
# 1. 克隆
git clone https://github.com/tvma9115-beep/CodeCraft.git
cd CodeCraft

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入本地 MySQL / Redis 地址

# 3. 起本地依赖（MySQL + Redis）
cd infra
docker compose up -d mysql redis
cd ..

# 4. 初始化数据库
mysql -h 127.0.0.1 -u root -p < db/schema.sql
mysql -h 127.0.0.1 -u root -p codecraft < db/seed-minimal.sql

# 5. 安装依赖并启动（P2 完成后可用）
cd frontend && npm install && npm run dev
cd ../api && npm install && npm run dev
cd ../worker && npm install && npm run dev
```

### 访问

| 服务 | 地址 |
|---|---|
| 前端工作台 | http://localhost:5173 |
| API | http://localhost:3000 |

---

## 分支与提交约定

### 分支

| 分支 | 用途 |
|---|---|
| `main` | 可演示、可部署的稳定版本，只接受合并 |
| `feat/<模块>-<简述>` | 功能开发，如 `feat/api-run-queue` |
| `fix/<简述>` | 修复，如 `fix/sourcemap-line-offset` |
| `docs/<简述>` | 文档与材料 |

**所有改动走分支 → 提 PR → 至少 1 人 review → 合并到 main。** 不直接推 main。

### 提交信息

```
<type>(<scope>): <简述>

类型：feat / fix / docs / refactor / test / chore
范围：frontend / api / worker / sandbox / infra / db / data / docs
```

示例：

```
feat(api): 生成 source map 并写入 project 表
fix(sandbox): 修正 3 秒超时被杀后仍返回 success 的问题
docs(gates): 记录 G2 结论
```

### 合并前检查

- [ ] 没有把 `.env`、`*.pem`、AK/SK 提交进去
- [ ] 本地能启动，改动有说明
- [ ] 若是范围变更，已更新 `docs/DECISIONS.md`

---

## 技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| 积木编辑器 | Blockly（官方） | 不重复造轮子，省 30–50h |
| 前端 | React + TypeScript + Vite | 与 CodeArts 生成代码默认口味一致 |
| 后端 | Node.js (Express) + TypeScript | 前后端同语言 |
| 数据库 | 华为云 RDS for MySQL 8.0 | 真实数据持久化，6 张表 |
| 队列/缓存 | 华为云 DCS for Redis 5.0+ | 队列解耦、结果缓存、限流、热榜 |
| 沙箱 | Docker（`--network none` + 资源限制） | 隔断网络、限内存/CPU/超时 |
| 部署 | 单台 ECS + Docker Compose | 44 天用不着 K8s |

---

## 明确不做

手机 App / HarmonyOS 适配 · React Flow 节点工作流 · 代码反向转积木 · 第三方库与多语言 · 本地大模型 / 离线模式 · 用户系统 / 班级管理 / 教师后台

---

## 许可

参赛作品，暂未选定开源许可。