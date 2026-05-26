# 服务器资源分配看板

本地化部署的服务器资源管理看板，用于管理物理服务器的 CPU、内存、磁盘在不同租户（各地方局）之间的分配。

## 项目结构

```
ccplan/
├── main.py                # 后端（FastAPI + SQLite）
├── init.sql               # 建表 + 示例数据
├── requirements.txt       # Python 依赖
├── resource_dashboard.db  # SQLite 数据库文件（启动后自动生成）
└── static/
    └── index.html          # 前端页面
```

## 环境要求

- Python 3.9+
- 浏览器：Chrome / Edge / Firefox

## 快速开始

### 1. 初始化数据库

首次使用需要先建表和导入示例数据。在项目目录下执行：

```bat
python -c "import sqlite3; f=open('init.sql','r',encoding='utf-8'); sql=f.read(); f.close(); c=sqlite3.connect('resource_dashboard.db'); c.executescript(sql); c.commit(); c.close(); print('Done')"
```

> 也可以用 DBeaver 连接 SQLite 文件后执行 `init.sql`。脚本可重复执行（开头有 DROP TABLE）。

### 2. 安装依赖

```bat
pip install -r requirements.txt
```

依赖内容：`fastapi`、`uvicorn`、`pydantic`。

### 3. 启动服务

```bat
python main.py
```

启动成功后终端显示：

```
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 4. 访问看板

浏览器打开 http://localhost:8000

---

## 功能说明

### 总览页

- 4 张指标卡：节点总数、CPU 总核数、内存总量、磁盘总容量
- 3 个环形图：CPU / 内存 / 磁盘分配率
- 1 个柱状图：各系列 CPU 使用分布

### 服务器页

- 按系列（A/B/C/D）筛选，支持搜索节点编号或机器名
- 表格展示每台服务器的配置、CPU / 内存 / 磁盘使用情况、已绑租户
- 点击**机器名**打开磁盘管理弹窗
- 右上角**"+ 新增服务器"**按钮

**磁盘管理弹窗**（点击机器名打开）：

| 操作 | 说明 |
|---|---|
| 新增磁盘 | 填写名称、容量、状态（默认自动建议 disk5/disk6...） |
| 内联编辑 | 点击编辑按钮，直接修改磁盘名称和大小，保存或取消 |
| 批量修改大小 | 勾选多块磁盘，底部操作栏输入新大小，一键批量修改 |
| 标记待替换 / 正常 | 切换磁盘状态 |
| 移除磁盘 | 删除单块磁盘 |
| 删除服务器 | 红色按钮，需二次确认（有生效分配时拒绝） |

**磁盘多租户**：一块磁盘可分配给多个租户，弹窗中显示所有关联租户名称列表。

**新增服务器弹窗**：

- 填写节点编号、机器名、选择硬件配置、系列、状态
- 硬件配置下拉框旁有**"新增配置"**按钮，可当场添加新配置
- 新增服务器自动创建 4 块 10TB 磁盘

### 租户页

- 按档位 / 状态筛选，支持搜索租户名称或地区
- 表格展示每个租户的 CPU、内存、磁盘占用
- 右上角**"+ 新增租户"**按钮，每行有**编辑**和**分配**按钮

**新增 / 编辑租户弹窗**：

- 新增时填写编码、名称、地区、档位、状态；编辑时编码不可改

**资源分配弹窗**（点击"分配"打开）：

| 操作 | 说明 |
|---|---|
| 新增 CPU/内存分配 | 选择服务器，填写 CPU 和内存（自动提示可用容量，超配校验） |
| 修改分配 | 调整已有分配的 CPU / 内存数量 |
| 回收分配 | 删除分配记录 |
| 磁盘分配 | 勾选磁盘后批量分配给当前租户，支持一块磁盘分配给多个租户 |
| 磁盘回收 | 释放当前租户与磁盘的关联（不影响其他租户对该磁盘的使用） |
| 共享标记 | 已分配给多个租户的磁盘显示 "(共享: N)" 标记 |

### 模板页

- 组件模板 CRUD，每个模板包含多个角色定义
- 新增/编辑模板弹窗，可动态增删角色行

### 可视面板

- **组件视角**：按租户 → 组件 → 角色层级展开，管理角色分配
- **服务器视角**：按服务器卡片展示，含 CPU 用量进度条，可直接新增/编辑角色分配

---

## API 列表

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/dashboard` | 获取全部看板数据 |
| `GET` | `/api/tenants` | 租户列表 |
| `POST` | `/api/tenants` | 新增租户 |
| `PATCH` | `/api/tenants/{id}` | 修改租户信息 |
| `GET` | `/api/tenants/{id}/allocations` | 租户的 CPU/内存分配列表 |
| `GET` | `/api/tenants/{id}/disks` | 租户关联磁盘列表（含 assigned_to_me 标记） |
| `POST` | `/api/allocations` | 新增分配（含超配校验） |
| `PATCH` | `/api/allocations/{id}` | 修改分配（含超配校验） |
| `DELETE` | `/api/allocations/{id}` | 回收分配 |
| `GET` | `/api/hardware-configs` | 硬件配置列表 |
| `POST` | `/api/hardware-configs` | 新增硬件配置 |
| `POST` | `/api/nodes` | 新增服务器（自动创建磁盘） |
| `DELETE` | `/api/nodes/{id}` | 删除服务器（级联删磁盘和分配） |
| `GET` | `/api/nodes/{id}/disks` | 节点磁盘列表（含 tenants 数组） |
| `POST` | `/api/nodes/{id}/disks` | 新增磁盘 |
| `PATCH` | `/api/disks/{id}` | 修改磁盘属性（名称、大小、状态） |
| `DELETE` | `/api/disks/{id}` | 删除磁盘（级联删除 disk_tenant） |
| `PATCH` | `/api/disks/batch-update` | 批量修改磁盘大小 |
| `POST` | `/api/disks/batch-assign` | 批量分配磁盘给租户 |
| `DELETE` | `/api/disks/{disk_id}/tenants/{tenant_id}` | 释放磁盘与租户的关联 |
| `GET` | `/api/component-templates` | 组件模板列表 |
| `POST` | `/api/component-templates` | 新增组件模板 |
| `PATCH` | `/api/component-templates/{id}` | 修改组件模板 |
| `DELETE` | `/api/component-templates/{id}` | 删除组件模板 |
| `GET` | `/api/tenants/{id}/components` | 租户的组件实例 |
| `POST` | `/api/tenants/{id}/components` | 新增组件实例 |
| `DELETE` | `/api/tenant-components/{id}` | 删除组件实例 |
| `POST` | `/api/role-allocations` | 新增角色分配 |
| `PATCH` | `/api/role-allocations/{id}` | 修改角色分配 |
| `DELETE` | `/api/role-allocations/{id}` | 删除角色分配 |
| `GET` | `/api/visualization/component-view` | 可视面板组件视角 |
| `GET` | `/api/visualization/node-view` | 可视面板服务器视角 |
| `GET` | `/api/visualization/node-summary` | 服务器资源汇总 |

---

## 数据模型

```
hardware_config ──1:N──> physical_node ──1:N──> cpu_memory_allocation ──N:1──> tenant
                        physical_node ──1:N──> disk ──M:N──> tenant (via disk_tenant)

component_template ──1:N──> role_template
tenant ──1:N──> tenant_component ──1:N──> role_allocation ──N:1──> physical_node
```

| 表 | 说明 |
|---|---|
| `hardware_config` | 硬件配置模板（配置二 96核/512G、配置三 96核/768G 等） |
| `physical_node` | 物理服务器（A/B/C/D 系列，状态：active / standby） |
| `tenant` | 租户（档位：1=第一档 / 2=第二档，状态：active / pending / reserved / returned） |
| `cpu_memory_allocation` | CPU / 内存分配记录（关联节点 + 租户，状态：active / pending） |
| `disk` | 磁盘（每块有 disk_name、disk_status=normal/replace） |
| `disk_tenant` | 磁盘-租户多对多关联（UNIQUE(disk_id, tenant_id) 防重复） |
| `component_template` | 组件模板 |
| `role_template` | 角色模板（属于组件模板） |
| `tenant_component` | 租户的组件实例 |
| `role_allocation` | 角色分配（关联租户组件 + 物理节点） |

---

## 常见问题

**Q：启动报 `unable to open database file`**

数据库文件与 `main.py` 在同一目录即可，路径通过 `__file__` 自动定位。若从其他目录启动，确认目录结构正确。

**Q：页面显示"数据加载失败：HTTP 500"**

数据库表未初始化，需要先执行 `init.sql` 导入建表和数据。

**Q：修改端口**

编辑 `main.py` 最后一行的 `port` 参数：

```python
uvicorn.run("main:app", host="0.0.0.0", port=9000, reload='true')
```

**Q：Windows 后台常驻运行**

PowerShell 后台启动（关闭窗口即停止）：

```powershell
Start-Process python -ArgumentList "main.py" -WorkingDirectory "C:\Users\hshua\Desktop\python\workbuddy\ccplan" -WindowStyle Hidden
```

任务计划程序开机自启：触发器选「计算机启动时」，程序填 `python`，参数填 `main.py`，起始目录填项目路径。

**Q：重置数据库**

重新执行 `init.sql` 即可（脚本开头会 DROP 旧表重建）：

```bat
python -c "import sqlite3; f=open('init.sql','r',encoding='utf-8'); sql=f.read(); f.close(); c=sqlite3.connect('resource_dashboard.db'); c.executescript(sql); c.commit(); c.close(); print('Done')"
```

**Q：从旧版本升级（磁盘多租户）**

直接启动新版 `main.py` 即可，启动时自动执行迁移：创建 `disk_tenant` 表，将旧 `disk.tenant_id` 数据搬入新表，无需手动操作。
