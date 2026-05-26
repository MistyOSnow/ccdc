# ccplan 开发记录

## 项目概述

服务器资源分配看板，FastAPI + SQLite 后端，原生 JS 单页前端（单 HTML 文件），无构建工具。

## 文件结构

```
ccplan/
  main.py              后端，FastAPI + Pydantic + sqlite3 原生 SQL
  static/index.html    前端，原生 JS + Chart.js CDN，暗/亮主题
  init.sql             建表 + 种子数据（165节点、28租户、7组件模板）
  requirements.txt     fastapi / uvicorn / pydantic
  resource_dashboard.db 运行时生成
```

## 数据模型（9表）

```
hardware_config ──1:N── physical_node ──1:N── cpu_memory_allocation ──N:1── tenant
                         │                                          │
                         └──1:N── disk ──M:N── tenant (via disk_tenant)

component_template ──1:N── role_template
tenant ──1:N── tenant_component ──1:N── role_allocation ──N:1── physical_node
```

- **旧分配体系**：`cpu_memory_allocation`，简单租户-节点 CPU/内存映射
- **新分配体系**：`role_allocation` 通过 `tenant_component`，组件/角色粒度
- **磁盘分配体系**：`disk_tenant` 多对多关联表，一块磁盘可分配给多个租户

## 前端页面（5个 tab）

| 页面 | 元素ID | 功能 |
|------|--------|------|
| 总览 | `page-overview` | 4指标卡 + 3环形图 + 堆叠柱状图 |
| 服务器 | `page-nodes` | 系列筛选 + 搜索 + 服务器表 + 磁盘管理弹窗 |
| 租户 | `page-tenants` | 档位/状态筛选 + 租户表 + 资源分配弹窗 |
| 模板 | `page-templates` | 组件模板 CRUD |
| 可视面板 | `page-viz` | 组件视角 / 服务器视角，角色分配管理 |

## 弹窗（7个）

| 元素ID | 功能 |
|--------|------|
| `modal-tenant` | 新增/编辑租户 |
| `modal-alloc` | 资源分配（CPU/内存 + 磁盘） |
| `modal-disk` | 服务器磁盘管理 + 删除服务器 |
| `modal-node` | 新增服务器（含新增硬件配置子表单） |
| `modal-template` | 新增/编辑组件模板 |
| `modal-comp` | 新增租户组件实例 |
| `modal-role-alloc` | 新增/编辑角色分配 |

---

## 开发历程

### 第一阶段：基础功能补全

补全了前端缺失的 JS 函数（模板页、可视面板、组件实例弹窗、角色分配弹窗），新增 `esc()` 防 XSS 工具函数。

### 第二阶段：后端安全增强

`delete_node` 端点扩展活跃分配检查至 `role_allocation`，新增已分配磁盘检查，删除时清理角色分配孤儿数据。

### 第三阶段：前端体验修复

- 编辑租户 PATCH 加 `if (!r.ok)` 错误处理
- 删除服务器确认框正确显示节点编号
- `editAlloc()` 改为复用内联表单替代 `prompt()`
- 切换主题后图表颜色自动刷新
- 所有用户数据输出加 `esc()` 包裹防 XSS

### 第四阶段：磁盘管理增强

#### 4.1 磁盘大小内联编辑

磁盘管理弹窗中每行新增编辑/保存/取消按钮：
- 点击编辑：切换 `.disk-display` / `.disk-edit` CSS 类显隐
- `saveDiskRow()` 调用 `PATCH /api/disks/{id}` 保存磁盘名称和大小
- `cancelDiskRow()` 还原为显示模式

#### 4.2 批量修改磁盘大小

- 新增 `PATCH /api/disks/batch-update` 端点
- 前端磁盘列表每行增加 checkbox，支持全选
- 底部批量操作栏：显示已选数量、输入新大小、确认/取消
- **关键**：路由定义必须在 `PATCH /api/disks/{disk_id}` 之前，否则 FastAPI 会把 `batch-update` 当作路径参数匹配，返回 422

#### 4.3 多租户磁盘分配（M:N 模型）

**设计决策**：一块磁盘可分配给多个租户，纯记录性质，不涉及容量计算。

**数据模型变更**：
- 新增 `disk_tenant` 关联表（`disk_id`, `tenant_id`, `allocated_at`），UNIQUE 约束防重复
- 移除 `disk.tenant_id` 单一外键依赖（旧字段保留但不再使用）
- 启动时自动迁移：`_ensure_disk_tenant()` 将旧 `disk.tenant_id` 数据搬入新表

**后端 API 变更**：
- `GET /api/dashboard`：磁盘统计用 `DISTINCT disk_id` 计数（一块盘分配给2个租户算1块已用盘，不是2块）
- `GET /api/nodes/{id}/disks`：返回 `tenants` 数组替代 `tenant_id`
- `DELETE /api/disks/{id}`：级联删除 `disk_tenant` 记录
- 新增 `DELETE /api/disks/{disk_id}/tenants/{tenant_id}`：释放特定租户的磁盘关联
- `PATCH /api/disks/{id}`：仅修改磁盘属性，不再处理租户分配
- `GET /api/tenants/{id}/disks`：返回 `assigned_to_me` 标记和 `tenants` 数组
- `POST /api/disks/batch-assign`：INSERT INTO `disk_tenant`，已存在则跳过（返回 `assigned: 0`）
- `DELETE /api/nodes/{id}`：检查 `disk_tenant` 并清理后删除

**前端变更**：
- 磁盘管理弹窗：显示租户名称列表替代"已分配/空闲"
- 租户分配弹窗：已分配磁盘显示所有租户名 + "(共享: X)" 标记
- `releaseDisk()` 改为调用 `DELETE /api/disks/{id}/tenants/{tid}`

---

## 开发理念

### 1. 子查询预聚合，避免 SQL 扇出

当多表 JOIN 导致行数膨胀（如节点 JOIN 磁盘 JOIN 分配）时，不在主查询中直接 COUNT，而是用子查询预聚合：

```sql
-- 错误：扇出导致节点级别统计翻倍
SELECT n.*, COUNT(d.id), COUNT(dt.id) FROM node n LEFT JOIN disk d LEFT JOIN disk_tenant dt ...

-- 正确：子查询预聚合
SELECT n.*, dd.total, dd2.used FROM node n
LEFT JOIN (SELECT node_id, COUNT(*) total FROM disk GROUP BY node_id) dd
LEFT JOIN (SELECT node_id, COUNT(DISTINCT disk_id) used FROM disk_tenant ... GROUP BY node_id) dd2
```

### 2. UNIQUE 约束 > 应用层校验

`disk_tenant` 表的 `UNIQUE(disk_id, tenant_id)` 在数据库层防止重复关联，`INSERT OR IGNORE` 优雅跳过重复。比应用层先查后插更可靠，避免并发竞态。

### 3. 路由定义顺序即匹配优先级

FastAPI 按代码定义顺序匹配路由。字面路径（`/batch-update`）必须定义在参数路径（`/{disk_id}`）之前，否则参数路由会吞掉字面路径。

### 4. 自动迁移，零停机

`_ensure_disk_tenant()` 在启动时执行，`CREATE TABLE IF NOT EXISTS` + `INSERT OR IGNORE`，首次运行建表迁移，后续运行幂等无副作用。不需要手动跑迁移脚本。

### 5. 优雅降级，不报错跳过

`batch-assign` 遇到已有关联时返回 `assigned: 0` 而非报错，前端无需额外处理重复分配场景。

---

## API 端点（33个）

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/dashboard` | 总览数据（summary + nodes + tenants） |
| GET/POST/PATCH | `/api/tenants`, `/api/tenants/{id}` | 租户 CRUD |
| GET | `/api/tenants/{id}/allocations` | 租户的 CPU/内存分配 |
| GET | `/api/tenants/{id}/disks` | 租户关联磁盘（含 assigned_to_me 标记） |
| GET/POST | `/api/tenants/{id}/components` | 租户组件实例 |
| POST/DELETE | `/api/allocations`, `/api/allocations/{id}` | 旧式分配 CRUD |
| PATCH | `/api/allocations/{id}` | 修改分配（含超配校验） |
| GET/POST | `/api/hardware-configs` | 硬件配置 |
| POST/DELETE | `/api/nodes`, `/api/nodes/{id}` | 服务器增删 |
| GET/POST | `/api/nodes/{id}/disks` | 节点磁盘 |
| PATCH/DELETE | `/api/disks/{id}` | 磁盘改/删 |
| PATCH | `/api/disks/batch-update` | 批量修改磁盘大小 |
| DELETE | `/api/disks/{disk_id}/tenants/{tenant_id}` | 释放磁盘租户关联 |
| POST | `/api/disks/batch-assign` | 批量分配磁盘给租户 |
| GET/POST/PATCH/DELETE | `/api/component-templates`, `/api/component-templates/{id}` | 组件模板 CRUD |
| DELETE | `/api/tenant-components/{id}` | 删除组件实例 |
| POST/PATCH/DELETE | `/api/role-allocations`, `/api/role-allocations/{id}` | 角色分配 CRUD |
| GET | `/api/visualization/component-view` | 可视面板组件视角 |
| GET | `/api/visualization/node-view` | 可视面板服务器视角 |
| GET | `/api/visualization/node-summary` | 服务器资源汇总 |

---

## 已知遗留问题

1. **Dashboard 统计不完整**：`GET /api/dashboard` 的 CPU/内存已用只查 `cpu_memory_allocation`，不含 `role_allocation`，总览分配率偏低
2. **超配校验不对称**：旧式分配 API 不查 `role_allocation`，可能绕过限制；新式 API 两张表都查
3. **删除服务器不清理 `role_allocation`**：`delete_node` 只删 disk + cpu_memory_allocation（第二次修改中已部分修复，增加了 role_allocation 检查和清理）
4. **租户磁盘列表依赖旧分配**：`GET /api/tenants/{id}/disks` 只显示 cpu_memory_allocation 节点下的磁盘
5. **disk.tenant_id 旧字段残留**：`disk` 表的 `tenant_id` 列仍存在但不再使用，数据已迁移至 `disk_tenant`
