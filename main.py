from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
import os

# ── SQLite 数据库路径 ──────────────────────────────────────
# 数据库文件与 main.py 放在同一目录，用 __file__ 定位，
# 避免从不同目录启动时找不到文件
import os as _os
DB_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "resource_dashboard.db")

def get_conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con

# ── 启动时确保 disk_tenant 关联表存在 ─────────────────────────
def _ensure_disk_tenant():
    con = get_conn()
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS disk_tenant (
                id           INTEGER PRIMARY KEY,
                disk_id      INTEGER NOT NULL REFERENCES disk(id) ON DELETE CASCADE,
                tenant_id    INTEGER NOT NULL REFERENCES tenant(id),
                allocated_at TEXT,
                UNIQUE(disk_id, tenant_id)
            )
        """)
        # 迁移旧数据：将 disk.tenant_id 搬入 disk_tenant
        rows = con.execute("SELECT id, tenant_id, allocated_at FROM disk WHERE tenant_id IS NOT NULL").fetchall()
        for r in rows:
            try:
                con.execute("INSERT OR IGNORE INTO disk_tenant (disk_id, tenant_id, allocated_at) VALUES (?,?,?)",
                            (r["id"], r["tenant_id"], r["allocated_at"]))
            except Exception:
                pass
        con.commit()
    finally:
        con.close()

_ensure_disk_tenant()

app = FastAPI(title="资源分配看板 API")

# static 目录同样用绝对路径，Windows 下 cd 到其他目录启动不会找不到
_base = _os.path.dirname(_os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=_os.path.join(_base, "static")), name="static")

@app.get("/")
def root():
    return FileResponse(_os.path.join(_base, "static", "index.html"))


# ════════════════════════════════════════════════════════════
# GET /api/dashboard
# ════════════════════════════════════════════════════════════
@app.get("/api/dashboard")
def get_dashboard():
    con = get_conn()
    try:
        # 1. 总量
        hw = dict(con.execute("""
            SELECT COALESCE(SUM(h.cpu_cores),0) AS total_cpu,
                   COALESCE(SUM(h.memory_gb),0) AS total_mem
            FROM   physical_node n
            JOIN   hardware_config h ON h.id = n.hardware_config_id
            WHERE  n.status != 'maintenance'
        """).fetchone())

        alloc = dict(con.execute("""
            SELECT COALESCE(SUM(cpu_allocated),0)    AS used_cpu,
                   COALESCE(SUM(memory_allocated),0) AS used_mem
            FROM   cpu_memory_allocation
            WHERE  alloc_status = 'active'
        """).fetchone())

        dk = dict(con.execute("""
            SELECT COUNT(*)                          AS total_disks,
                   COALESCE(SUM(disk_size_tb),0)    AS total_tb
            FROM   disk
        """).fetchone())
        dk2 = dict(con.execute("""
            SELECT COUNT(DISTINCT dt.disk_id) AS used_disks,
                   COALESCE(SUM(d.disk_size_tb),0) AS used_tb
            FROM   disk_tenant dt
            JOIN   disk d ON d.id = dt.disk_id
        """).fetchone())
        dk["used_disks"] = dk2["used_disks"]
        dk["used_tb"] = dk2["used_tb"]

        summary = {
            "cpu":  {"total": hw["total_cpu"],  "used": alloc["used_cpu"]},
            "mem":  {"total": hw["total_mem"],  "used": alloc["used_mem"]},
            "disk": {"total_disks": dk["total_disks"], "total_tb": dk["total_tb"],
                     "used_disks": dk["used_disks"],   "used_tb":  dk["used_tb"]},
        }

        # 2. 节点列表
        node_rows = con.execute("""
            SELECT n.id, n.node_code, n.machine_name, n.series, n.status,
                   h.config_name, h.cpu_cores, h.memory_gb,
                   COALESCE(ca.cpu_used,0)    AS cpu_used,
                   COALESCE(ca.mem_used,0)    AS mem_used,
                   COALESCE(dd.total_disks,0) AS total_disks,
                   COALESCE(dd2.used_disks,0)  AS used_disks,
                   COALESCE(dd.total_disk_tb,0) AS total_disk_tb,
                   COALESCE(dd2.used_disk_tb,0)  AS used_disk_tb
            FROM   physical_node n
            JOIN   hardware_config h ON h.id = n.hardware_config_id
            LEFT JOIN (
                SELECT node_id,
                       SUM(cpu_allocated)    AS cpu_used,
                       SUM(memory_allocated) AS mem_used
                FROM   cpu_memory_allocation
                WHERE  alloc_status = 'active'
                GROUP  BY node_id
            ) ca ON ca.node_id = n.id
            LEFT JOIN (
                SELECT d.node_id,
                       COUNT(*)              AS total_disks,
                       SUM(d.disk_size_tb)   AS total_disk_tb
                FROM   disk d
                GROUP  BY d.node_id
            ) dd ON dd.node_id = n.id
            LEFT JOIN (
                SELECT d2.node_id,
                       COUNT(DISTINCT dt.disk_id) AS used_disks,
                       SUM(d2.disk_size_tb)       AS used_disk_tb
                FROM   disk_tenant dt
                JOIN   disk d2 ON d2.id = dt.disk_id
                GROUP  BY d2.node_id
            ) dd2 ON dd2.node_id = n.id
            ORDER  BY n.series, n.node_code
        """).fetchall()
        nodes = [dict(r) for r in node_rows]

        # 挂租户信息
        tenant_rows = con.execute("""
            SELECT a.node_id, t.tenant_name, a.cpu_allocated,
                   a.memory_allocated, a.alloc_status
            FROM   cpu_memory_allocation a
            JOIN   tenant t ON t.id = a.tenant_id
            ORDER  BY a.node_id
        """).fetchall()
        ntmap = {}
        for r in tenant_rows:
            ntmap.setdefault(r["node_id"], []).append({
                "name": r["tenant_name"], "cpu": r["cpu_allocated"],
                "mem": r["memory_allocated"], "status": r["alloc_status"],
            })
        for n in nodes:
            n["tenants"] = ntmap.get(n["id"], [])

        # 3. 租户列表
        tenant_rows2 = con.execute("""
            SELECT t.id, t.tenant_name, t.region, t.tier, t.status,
                   COALESCE(ca.cpu_total,0)    AS cpu_total,
                   COALESCE(ca.mem_total,0)    AS mem_total,
                   COALESCE(dd.disk_count,0)   AS disk_count,
                   COALESCE(dd.disk_tb,0)      AS disk_tb
            FROM   tenant t
            LEFT JOIN (
                SELECT tenant_id,
                       SUM(cpu_allocated)    AS cpu_total,
                       SUM(memory_allocated) AS mem_total
                FROM   cpu_memory_allocation
                WHERE  alloc_status = 'active'
                GROUP  BY tenant_id
            ) ca ON ca.tenant_id = t.id
            LEFT JOIN (
                SELECT dt.tenant_id,
                       COUNT(DISTINCT dt.disk_id) AS disk_count,
                       SUM(d.disk_size_tb)        AS disk_tb
                FROM   disk_tenant dt
                JOIN   disk d ON d.id = dt.disk_id
                GROUP  BY dt.tenant_id
            ) dd ON dd.tenant_id = t.id
            ORDER  BY t.tier, t.id
        """).fetchall()
        tenants = [dict(r) for r in tenant_rows2]

    finally:
        con.close()

    return {"summary": summary, "nodes": nodes, "tenants": tenants}


# ════════════════════════════════════════════════════════════
# GET /api/nodes/{node_id}/disks
# ════════════════════════════════════════════════════════════
@app.get("/api/nodes/{node_id}/disks")
def get_node_disks(node_id: int):
    con = get_conn()
    try:
        rows = con.execute("""
            SELECT d.id, d.node_id, d.disk_name, d.disk_size_tb, d.disk_status
            FROM disk d
            WHERE d.node_id = ?
            ORDER BY d.id
        """, (node_id,)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            tenants = con.execute("""
                SELECT dt.tenant_id, dt.allocated_at, t.tenant_name
                FROM disk_tenant dt
                JOIN tenant t ON t.id = dt.tenant_id
                WHERE dt.disk_id = ?
            """, (r["id"],)).fetchall()
            d["tenants"] = [dict(t) for t in tenants]
            result.append(d)
        return result
    finally:
        con.close()


# ════════════════════════════════════════════════════════════
# POST /api/nodes/{node_id}/disks
# ════════════════════════════════════════════════════════════
class DiskCreate(BaseModel):
    disk_name: str
    disk_size_tb: int
    disk_status: str = "normal"

@app.post("/api/nodes/{node_id}/disks")
def create_disk(node_id: int, body: DiskCreate):
    con = get_conn()
    try:
        node = con.execute("SELECT id FROM physical_node WHERE id=?", (node_id,)).fetchone()
        if not node:
            raise HTTPException(status_code=404, detail="node not found")
        cur = con.execute(
            "INSERT INTO disk (node_id, disk_name, disk_size_tb, disk_status) VALUES (?,?,?,?)",
            (node_id, body.disk_name, body.disk_size_tb, body.disk_status),
        )
        con.commit()
        return {"ok": True, "id": cur.lastrowid}
    finally:
        con.close()


# ════════════════════════════════════════════════════════════
# DELETE /api/disks/{disk_id}
# ════════════════════════════════════════════════════════════
@app.delete("/api/disks/{disk_id}")
def delete_disk(disk_id: int):
    con = get_conn()
    try:
        con.execute("DELETE FROM disk_tenant WHERE disk_id=?", (disk_id,))
        cur = con.execute("DELETE FROM disk WHERE id=?", (disk_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="disk not found")
        con.commit()
    finally:
        con.close()
    return {"ok": True}


# ════════════════════════════════════════════════════════════
# DELETE /api/disks/{disk_id}/tenants/{tenant_id}  — 回收磁盘对某租户的分配
# ════════════════════════════════════════════════════════════
@app.delete("/api/disks/{disk_id}/tenants/{tenant_id}")
def release_disk_tenant(disk_id: int, tenant_id: int):
    con = get_conn()
    try:
        cur = con.execute(
            "DELETE FROM disk_tenant WHERE disk_id=? AND tenant_id=?",
            (disk_id, tenant_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="该磁盘未分配给此租户")
        con.commit()
    finally:
        con.close()
    return {"ok": True}


# PATCH /api/disks/batch-update
# ════════════════════════════════════════════════════════════
class DiskBatchUpdate(BaseModel):
    disk_ids: List[int]
    disk_size_tb: int

@app.patch("/api/disks/batch-update")
def batch_update_disks(body: DiskBatchUpdate):
    if not body.disk_ids:
        raise HTTPException(status_code=400, detail="未选择磁盘")
    if body.disk_size_tb < 1:
        raise HTTPException(status_code=400, detail="磁盘大小不能小于1")
    con = get_conn()
    try:
        placeholders = ",".join("?" for _ in body.disk_ids)
        cur = con.execute(
            f"UPDATE disk SET disk_size_tb=? WHERE id IN ({placeholders})",
            [body.disk_size_tb] + body.disk_ids,
        )
        con.commit()
        return {"ok": True, "updated": cur.rowcount}
    finally:
        con.close()


# PATCH /api/disks/{disk_id}
# ════════════════════════════════════════════════════════════
class DiskUpdate(BaseModel):
    disk_name: Optional[str] = None
    disk_size_tb: Optional[int] = None
    disk_status: Optional[str] = None

@app.patch("/api/disks/{disk_id}")
def update_disk(disk_id: int, body: DiskUpdate):
    con = get_conn()
    try:
        fields = {}
        if body.disk_name is not None:
            fields["disk_name"] = body.disk_name
        if body.disk_size_tb is not None:
            fields["disk_size_tb"] = body.disk_size_tb
        if body.disk_status is not None:
            fields["disk_status"] = body.disk_status

        if not fields:
            raise HTTPException(status_code=400, detail="no fields to update")
        set_clause = ", ".join(f"{k}=?" for k in fields)
        values = list(fields.values()) + [disk_id]
        con.execute(f"UPDATE disk SET {set_clause} WHERE id=?", values)
        con.commit()
    finally:
        con.close()
    return {"ok": True}


# ════════════════════════════════════════════════════════════
# GET /api/tenants/{tenant_id}/allocations
# ════════════════════════════════════════════════════════════
@app.get("/api/tenants/{tenant_id}/allocations")
def get_tenant_allocations(tenant_id: int):
    con = get_conn()
    try:
        rows = con.execute("""
            SELECT a.id, a.node_id, a.cpu_allocated, a.memory_allocated, a.alloc_status,
                   n.node_code, n.machine_name
            FROM cpu_memory_allocation a
            JOIN physical_node n ON n.id = a.node_id
            WHERE a.tenant_id = ?
            ORDER BY n.node_code
        """, (tenant_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


# ════════════════════════════════════════════════════════════
# GET /api/tenants/{tenant_id}/disks
# ════════════════════════════════════════════════════════════
@app.get("/api/tenants/{tenant_id}/disks")
def get_tenant_disks(tenant_id: int):
    con = get_conn()
    try:
        rows = con.execute("""
            SELECT d.id, d.node_id, d.disk_name, d.disk_size_tb, d.disk_status,
                   n.node_code, n.machine_name,
                   CASE WHEN dt.disk_id IS NOT NULL THEN 1 ELSE 0 END AS assigned_to_me
            FROM disk d
            JOIN physical_node n ON n.id = d.node_id
            LEFT JOIN disk_tenant dt ON dt.disk_id = d.id AND dt.tenant_id = ?
            WHERE d.node_id IN (
                SELECT DISTINCT node_id FROM cpu_memory_allocation WHERE tenant_id = ?
            )
            ORDER BY n.node_code, d.id
        """, (tenant_id, tenant_id)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            tenants = con.execute("""
                SELECT dt2.tenant_id, dt2.allocated_at, t.tenant_name
                FROM disk_tenant dt2
                JOIN tenant t ON t.id = dt2.tenant_id
                WHERE dt2.disk_id = ?
            """, (r["id"],)).fetchall()
            d["tenants"] = [dict(t) for t in tenants]
            result.append(d)
        return result
    finally:
        con.close()


class DiskBatchAssign(BaseModel):
    disk_ids: List[int]
    tenant_id: int

@app.post("/api/disks/batch-assign")
def batch_assign_disks(body: DiskBatchAssign):
    con = get_conn()
    try:
        tenant = con.execute("SELECT id FROM tenant WHERE id=?", (body.tenant_id,)).fetchone()
        if not tenant:
            raise HTTPException(status_code=404, detail="租户不存在")
        now = "datetime('now','localtime')"
        assigned = 0
        for did in body.disk_ids:
            existing = con.execute(
                "SELECT 1 FROM disk_tenant WHERE disk_id=? AND tenant_id=?",
                (did, body.tenant_id),
            ).fetchone()
            if existing:
                continue
            disk = con.execute("SELECT id FROM disk WHERE id=?", (did,)).fetchone()
            if not disk:
                continue
            con.execute(
                f"INSERT INTO disk_tenant (disk_id, tenant_id, allocated_at) VALUES (?,?,{now})",
                (did, body.tenant_id),
            )
            assigned += 1
        con.commit()
        return {"ok": True, "assigned": assigned}
    finally:
        con.close()



# ════════════════════════════════════════════════════════════
# PATCH /api/allocations/{alloc_id}
# ════════════════════════════════════════════════════════════
class AllocUpdate(BaseModel):
    cpu_allocated:    Optional[int] = None
    memory_allocated: Optional[int] = None
    alloc_status:     Optional[str] = None

@app.patch("/api/allocations/{alloc_id}")
def update_allocation(alloc_id: int, body: AllocUpdate):
    fields = {k: v for k, v in body.dict().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")
    con = get_conn()
    try:
        # validate capacity if cpu or memory changed
        if "cpu_allocated" in fields or "memory_allocated" in fields:
            alloc = con.execute("SELECT node_id, cpu_allocated, memory_allocated FROM cpu_memory_allocation WHERE id=?", (alloc_id,)).fetchone()
            if not alloc:
                raise HTTPException(status_code=404, detail="allocation not found")
            node_id = alloc["node_id"]
            new_cpu = fields.get("cpu_allocated", alloc["cpu_allocated"])
            new_mem = fields.get("memory_allocated", alloc["memory_allocated"])
            hw = dict(con.execute("""
                SELECT h.cpu_cores, h.memory_gb
                FROM physical_node n JOIN hardware_config h ON h.id = n.hardware_config_id
                WHERE n.id = ?
            """, (node_id,)).fetchone())
            used = dict(con.execute("""
                SELECT COALESCE(SUM(cpu_allocated),0) AS used_cpu,
                       COALESCE(SUM(memory_allocated),0) AS used_mem
                FROM cpu_memory_allocation
                WHERE node_id = ? AND alloc_status = 'active' AND id != ?
            """, (node_id, alloc_id)).fetchone())
            if new_cpu > hw["cpu_cores"] - used["used_cpu"]:
                raise HTTPException(status_code=400, detail=f"CPU 超配：该节点剩余 {hw['cpu_cores'] - used['used_cpu']} 核")
            if new_mem > hw["memory_gb"] - used["used_mem"]:
                raise HTTPException(status_code=400, detail=f"内存超配：该节点剩余 {hw['memory_gb'] - used['used_mem']} GB")
        set_clause = ", ".join(f"{k}=?" for k in fields)
        values = list(fields.values()) + [alloc_id]
        cur = con.execute(f"UPDATE cpu_memory_allocation SET {set_clause} WHERE id=?", values)
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="allocation not found")
        con.commit()
    finally:
        con.close()
    return {"ok": True}


# ════════════════════════════════════════════════════════════
# POST /api/tenants
# ════════════════════════════════════════════════════════════
class TenantCreate(BaseModel):
    tenant_code: str
    tenant_name: str
    region: Optional[str] = None
    tier: int = 2
    status: str = "pending"

@app.post("/api/tenants")
def create_tenant(body: TenantCreate):
    con = get_conn()
    try:
        cur = con.execute(
            "INSERT INTO tenant (tenant_code,tenant_name,region,tier,status) VALUES (?,?,?,?,?)",
            (body.tenant_code, body.tenant_name, body.region, body.tier, body.status),
        )
        con.commit()
        return {"ok": True, "id": cur.lastrowid}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="tenant_code 已存在")
    finally:
        con.close()


# ════════════════════════════════════════════════════════════
# PATCH /api/tenants/{tenant_id}
# ════════════════════════════════════════════════════════════
class TenantUpdate(BaseModel):
    tenant_name: Optional[str] = None
    region: Optional[str] = None
    tier: Optional[int] = None
    status: Optional[str] = None

@app.patch("/api/tenants/{tenant_id}")
def update_tenant(tenant_id: int, body: TenantUpdate):
    fields = {k: v for k, v in body.dict().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")
    set_clause = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [tenant_id]
    con = get_conn()
    try:
        cur = con.execute(f"UPDATE tenant SET {set_clause} WHERE id=?", values)
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="tenant not found")
        con.commit()
    finally:
        con.close()
    return {"ok": True}


# ════════════════════════════════════════════════════════════
# GET /api/tenants (for modal dropdowns)
# ════════════════════════════════════════════════════════════
@app.get("/api/tenants")
def list_tenants():
    con = get_conn()
    try:
        rows = con.execute("SELECT id, tenant_code, tenant_name, region, tier, status FROM tenant ORDER BY tier, id").fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


# ════════════════════════════════════════════════════════════
# POST /api/allocations
# ════════════════════════════════════════════════════════════
class AllocCreate(BaseModel):
    node_id: int
    tenant_id: int
    cpu_allocated: int = 0
    memory_allocated: int = 0

@app.post("/api/allocations")
def create_allocation(body: AllocCreate):
    con = get_conn()
    try:
        # check node exists
        node = con.execute("SELECT id FROM physical_node WHERE id=?", (body.node_id,)).fetchone()
        if not node:
            raise HTTPException(status_code=404, detail="node not found")
        # check tenant exists
        tenant = con.execute("SELECT id FROM tenant WHERE id=?", (body.tenant_id,)).fetchone()
        if not tenant:
            raise HTTPException(status_code=404, detail="tenant not found")
        # check cpu capacity
        hw = dict(con.execute("""
            SELECT h.cpu_cores, h.memory_gb
            FROM physical_node n JOIN hardware_config h ON h.id = n.hardware_config_id
            WHERE n.id = ?
        """, (body.node_id,)).fetchone())
        used = dict(con.execute("""
            SELECT COALESCE(SUM(cpu_allocated),0) AS used_cpu,
                   COALESCE(SUM(memory_allocated),0) AS used_mem
            FROM cpu_memory_allocation
            WHERE node_id = ? AND alloc_status = 'active'
        """, (body.node_id,)).fetchone())
        if body.cpu_allocated > hw["cpu_cores"] - used["used_cpu"]:
            raise HTTPException(status_code=400, detail=f"CPU 超配：该节点剩余 {hw['cpu_cores'] - used['used_cpu']} 核")
        if body.memory_allocated > hw["memory_gb"] - used["used_mem"]:
            raise HTTPException(status_code=400, detail=f"内存超配：该节点剩余 {hw['memory_gb'] - used['used_mem']} GB")
        cur = con.execute(
            "INSERT INTO cpu_memory_allocation (node_id,tenant_id,cpu_allocated,memory_allocated,alloc_status) VALUES (?,?,?,?,?)",
            (body.node_id, body.tenant_id, body.cpu_allocated, body.memory_allocated, "active"),
        )
        con.commit()
        return {"ok": True, "id": cur.lastrowid}
    finally:
        con.close()


# ════════════════════════════════════════════════════════════
# DELETE /api/allocations/{alloc_id}
# ════════════════════════════════════════════════════════════
@app.delete("/api/allocations/{alloc_id}")
def delete_allocation(alloc_id: int):
    con = get_conn()
    try:
        cur = con.execute("DELETE FROM cpu_memory_allocation WHERE id=?", (alloc_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="allocation not found")
        con.commit()
    finally:
        con.close()
    return {"ok": True}


# ════════════════════════════════════════════════════════════
# GET /api/hardware-configs
# ════════════════════════════════════════════════════════════
@app.get("/api/hardware-configs")
def list_hardware_configs():
    con = get_conn()
    try:
        rows = con.execute("SELECT id, config_name, cpu_cores, memory_gb, description FROM hardware_config ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


# ════════════════════════════════════════════════════════════
# POST /api/hardware-configs
# ════════════════════════════════════════════════════════════
class HwConfigCreate(BaseModel):
    config_name: str
    cpu_cores: int
    memory_gb: int
    description: Optional[str] = None

@app.post("/api/hardware-configs")
def create_hardware_config(body: HwConfigCreate):
    con = get_conn()
    try:
        cur = con.execute(
            "INSERT INTO hardware_config (config_name, cpu_cores, memory_gb, description) VALUES (?,?,?,?)",
            (body.config_name, body.cpu_cores, body.memory_gb, body.description),
        )
        con.commit()
        return {"ok": True, "id": cur.lastrowid}
    finally:
        con.close()


# ════════════════════════════════════════════════════════════
# POST /api/nodes
# ════════════════════════════════════════════════════════════
class NodeCreate(BaseModel):
    node_code: str
    machine_name: str
    hardware_config_id: int
    series: str
    status: str = "active"

@app.post("/api/nodes")
def create_node(body: NodeCreate):
    con = get_conn()
    try:
        hw = con.execute("SELECT id FROM hardware_config WHERE id=?", (body.hardware_config_id,)).fetchone()
        if not hw:
            raise HTTPException(status_code=400, detail="hardware_config 不存在")
        cur = con.execute(
            "INSERT INTO physical_node (node_code, machine_name, hardware_config_id, series, status) VALUES (?,?,?,?,?)",
            (body.node_code, body.machine_name, body.hardware_config_id, body.series, body.status),
        )
        node_id = cur.lastrowid
        # auto-create 4 disks
        for i in range(1, 5):
            con.execute(
                "INSERT INTO disk (node_id, disk_name, disk_size_tb, disk_status) VALUES (?,?,?,?)",
                (node_id, f"disk{i}", 10, "normal"),
            )
        con.commit()
        return {"ok": True, "id": node_id}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="node_code 已存在")
    finally:
        con.close()


# ════════════════════════════════════════════════════════════
# DELETE /api/nodes/{node_id}
# ════════════════════════════════════════════════════════════
@app.delete("/api/nodes/{node_id}")
def delete_node(node_id: int):
    con = get_conn()
    try:
        # check if node has active allocations (both old-style and role-based)
        active_old = con.execute(
            "SELECT COUNT(*) FROM cpu_memory_allocation WHERE node_id=? AND alloc_status='active'",
            (node_id,),
        ).fetchone()[0]
        active_role = con.execute(
            "SELECT COUNT(*) FROM role_allocation WHERE node_id=? AND status='active'",
            (node_id,),
        ).fetchone()[0]
        total_active = active_old + active_role
        if total_active > 0:
            raise HTTPException(status_code=400, detail=f"该节点仍有 {total_active} 条生效分配，请先回收")
        # also check assigned disks
        assigned_disks = con.execute(
            """SELECT COUNT(DISTINCT dt.disk_id) FROM disk_tenant dt
               JOIN disk d ON d.id = dt.disk_id WHERE d.node_id=?""",
            (node_id,),
        ).fetchone()[0]
        if assigned_disks > 0:
            raise HTTPException(status_code=400, detail=f"该节点仍有 {assigned_disks} 块已分配磁盘，请先回收")
        # delete role allocations, disk_tenant, disks, old-style allocations, then node
        con.execute("DELETE FROM disk_tenant WHERE disk_id IN (SELECT id FROM disk WHERE node_id=?)", (node_id,))
        con.execute("DELETE FROM role_allocation WHERE node_id=?", (node_id,))
        con.execute("DELETE FROM disk WHERE node_id=?", (node_id,))
        con.execute("DELETE FROM cpu_memory_allocation WHERE node_id=?", (node_id,))
        cur = con.execute("DELETE FROM physical_node WHERE id=?", (node_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="node not found")
        con.commit()
    finally:
        con.close()
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="localhost", port=8000, reload='true')


# ════════════════════════════════════════════════════════════
# 组件模板 API
# ════════════════════════════════════════════════════════════
@app.get("/api/component-templates")
def list_component_templates():
    con = get_conn()
    try:
        rows = con.execute("""
            SELECT ct.id, ct.name, ct.description,
                   GROUP_CONCAT(rt.role_name, ',') AS roles
            FROM component_template ct
            LEFT JOIN role_template rt ON rt.component_id = ct.id
            GROUP BY ct.id
            ORDER BY ct.id
        """).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["roles"] = d["roles"].split(",") if d["roles"] else []
            result.append(d)
        return result
    finally:
        con.close()


class ComponentTemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    roles: List[str] = []


@app.post("/api/component-templates")
def create_component_template(body: ComponentTemplateCreate):
    con = get_conn()
    try:
        cur = con.execute(
            "INSERT INTO component_template (name, description) VALUES (?,?)",
            (body.name, body.description),
        )
        cid = cur.lastrowid
        for rn in body.roles:
            if rn.strip():
                con.execute("INSERT INTO role_template (component_id, role_name) VALUES (?,?)", (cid, rn.strip()))
        con.commit()
        return {"ok": True, "id": cid}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="组件名称已存在")
    finally:
        con.close()


class ComponentTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    roles: Optional[List[str]] = None


@app.patch("/api/component-templates/{template_id}")
def update_component_template(template_id: int, body: ComponentTemplateUpdate):
    con = get_conn()
    try:
        if body.name is not None or body.description is not None:
            fields = {}
            if body.name is not None:
                fields["name"] = body.name
            if body.description is not None:
                fields["description"] = body.description
            set_clause = ", ".join(f"{k}=?" for k in fields)
            con.execute(f"UPDATE component_template SET {set_clause} WHERE id=?", list(fields.values()) + [template_id])
        if body.roles is not None:
            con.execute("DELETE FROM role_template WHERE component_id=?", (template_id,))
            for rn in body.roles:
                if rn.strip():
                    con.execute("INSERT INTO role_template (component_id, role_name) VALUES (?,?)", (template_id, rn.strip()))
        con.commit()
    finally:
        con.close()
    return {"ok": True}


@app.delete("/api/component-templates/{template_id}")
def delete_component_template(template_id: int):
    con = get_conn()
    try:
        cur = con.execute("DELETE FROM component_template WHERE id=?", (template_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="模板不存在")
        con.commit()
    finally:
        con.close()
    return {"ok": True}


# ════════════════════════════════════════════════════════════
# 租户组件实例 API
# ════════════════════════════════════════════════════════════
@app.get("/api/tenants/{tenant_id}/components")
def list_tenant_components(tenant_id: int):
    con = get_conn()
    try:
        rows = con.execute("""
            SELECT tc.id, tc.tenant_id, tc.component_id, tc.component_name, tc.instance_label, tc.created_at,
                   GROUP_CONCAT(DISTINCT ra.role_name || '#' || ra.role_seq) AS role_summary,
                   COALESCE(SUM(ra.cpu), 0)  AS total_cpu,
                   COALESCE(SUM(ra.memory), 0) AS total_memory
            FROM tenant_component tc
            LEFT JOIN role_allocation ra ON ra.tenant_component_id = tc.id
            WHERE tc.tenant_id = ?
            GROUP BY tc.id
            ORDER BY tc.id
        """, (tenant_id,)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["role_summary"] = d["role_summary"].split(",") if d["role_summary"] else []
            result.append(d)
        return result
    finally:
        con.close()


class TenantComponentCreate(BaseModel):
    component_id: Optional[int] = None
    component_name: str
    instance_label: str = "1"


@app.post("/api/tenants/{tenant_id}/components")
def create_tenant_component(tenant_id: int, body: TenantComponentCreate):
    con = get_conn()
    try:
        t = con.execute("SELECT id FROM tenant WHERE id=?", (tenant_id,)).fetchone()
        if not t:
            raise HTTPException(status_code=404, detail="租户不存在")
        cur = con.execute(
            "INSERT INTO tenant_component (tenant_id, component_id, component_name, instance_label) VALUES (?,?,?,?)",
            (tenant_id, body.component_id, body.component_name, body.instance_label),
        )
        con.commit()
        return {"ok": True, "id": cur.lastrowid}
    finally:
        con.close()


@app.delete("/api/tenant-components/{tc_id}")
def delete_tenant_component(tc_id: int):
    con = get_conn()
    try:
        cur = con.execute("DELETE FROM tenant_component WHERE id=?", (tc_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="组件实例不存在")
        con.commit()
    finally:
        con.close()
    return {"ok": True}


# ════════════════════════════════════════════════════════════
# 角色分配 API
# ════════════════════════════════════════════════════════════
class RoleAllocCreate(BaseModel):
    tenant_component_id: int
    role_name: str
    role_seq: int = 1
    node_id: int
    cpu: int = 0
    memory: int = 0
    status: str = "active"


@app.post("/api/role-allocations")
def create_role_allocation(body: RoleAllocCreate):
    con = get_conn()
    try:
        tc = con.execute("SELECT id, tenant_id FROM tenant_component WHERE id=?", (body.tenant_component_id,)).fetchone()
        if not tc:
            raise HTTPException(status_code=404, detail="组件实例不存在")
        # validate node capacity
        hw = dict(con.execute("""
            SELECT h.cpu_cores, h.memory_gb
            FROM physical_node n JOIN hardware_config h ON h.id = n.hardware_config_id
            WHERE n.id = ?
        """, (body.node_id,)).fetchone())
        used = dict(con.execute("""
            SELECT COALESCE(SUM(cpu),0) AS used_cpu, COALESCE(SUM(memory),0) AS used_mem
            FROM role_allocation
            WHERE node_id = ? AND status = 'active'
        """, (body.node_id,)).fetchone())
        # also count old-style allocations
        used_old = dict(con.execute("""
            SELECT COALESCE(SUM(cpu_allocated),0) AS used_cpu, COALESCE(SUM(memory_allocated),0) AS used_mem
            FROM cpu_memory_allocation
            WHERE node_id = ? AND alloc_status = 'active'
        """, (body.node_id,)).fetchone())
        total_cpu_used = used["used_cpu"] + used_old["used_cpu"]
        total_mem_used = used["used_mem"] + used_old["used_mem"]
        if body.cpu > hw["cpu_cores"] - total_cpu_used:
            raise HTTPException(status_code=400, detail=f"CPU 超配：该节点剩余 {hw['cpu_cores'] - total_cpu_used} 核")
        if body.memory > hw["memory_gb"] - total_mem_used:
            raise HTTPException(status_code=400, detail=f"内存超配：该节点剩余 {hw['memory_gb'] - total_mem_used} GB")
        cur = con.execute(
            "INSERT INTO role_allocation (tenant_component_id, role_name, role_seq, node_id, cpu, memory, status) VALUES (?,?,?,?,?,?,?)",
            (body.tenant_component_id, body.role_name, body.role_seq, body.node_id, body.cpu, body.memory, body.status),
        )
        con.commit()
        return {"ok": True, "id": cur.lastrowid}
    finally:
        con.close()


class RoleAllocUpdate(BaseModel):
    role_name: Optional[str] = None
    role_seq: Optional[int] = None
    node_id: Optional[int] = None
    cpu: Optional[int] = None
    memory: Optional[int] = None
    status: Optional[str] = None


@app.patch("/api/role-allocations/{alloc_id}")
def update_role_allocation(alloc_id: int, body: RoleAllocUpdate):
    con = get_conn()
    try:
        # validate capacity if cpu/memory/node changed
        if body.cpu is not None or body.memory is not None or body.node_id is not None:
            alloc = con.execute("SELECT node_id, cpu, memory FROM role_allocation WHERE id=?", (alloc_id,)).fetchone()
            if not alloc:
                raise HTTPException(status_code=404, detail="分配记录不存在")
            target_node = body.node_id if body.node_id is not None else alloc["node_id"]
            new_cpu = body.cpu if body.cpu is not None else alloc["cpu"]
            new_mem = body.memory if body.memory is not None else alloc["memory"]
            hw = dict(con.execute("""
                SELECT h.cpu_cores, h.memory_gb
                FROM physical_node n JOIN hardware_config h ON h.id = n.hardware_config_id
                WHERE n.id = ?
            """, (target_node,)).fetchone())
            used = dict(con.execute("""
                SELECT COALESCE(SUM(cpu),0) AS used_cpu, COALESCE(SUM(memory),0) AS used_mem
                FROM role_allocation
                WHERE node_id = ? AND status = 'active' AND id != ?
            """, (target_node, alloc_id)).fetchone())
            used_old = dict(con.execute("""
                SELECT COALESCE(SUM(cpu_allocated),0) AS used_cpu, COALESCE(SUM(memory_allocated),0) AS used_mem
                FROM cpu_memory_allocation
                WHERE node_id = ? AND alloc_status = 'active'
            """, (target_node,)).fetchone())
            total_cpu_used = used["used_cpu"] + used_old["used_cpu"]
            total_mem_used = used["used_mem"] + used_old["used_mem"]
            if new_cpu > hw["cpu_cores"] - total_cpu_used:
                raise HTTPException(status_code=400, detail=f"CPU 超配：该节点剩余 {hw['cpu_cores'] - total_cpu_used} 核")
            if new_mem > hw["memory_gb"] - total_mem_used:
                raise HTTPException(status_code=400, detail=f"内存超配：该节点剩余 {hw['memory_gb'] - total_mem_used} GB")

        fields = {k: v for k, v in body.dict().items() if v is not None}
        if not fields:
            raise HTTPException(status_code=400, detail="no fields to update")
        set_clause = ", ".join(f"{k}=?" for k in fields)
        values = list(fields.values()) + [alloc_id]
        cur = con.execute(f"UPDATE role_allocation SET {set_clause} WHERE id=?", values)
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="分配记录不存在")
        con.commit()
    finally:
        con.close()
    return {"ok": True}


@app.delete("/api/role-allocations/{alloc_id}")
def delete_role_allocation(alloc_id: int):
    con = get_conn()
    try:
        cur = con.execute("DELETE FROM role_allocation WHERE id=?", (alloc_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="分配记录不存在")
        con.commit()
    finally:
        con.close()
    return {"ok": True}


# ════════════════════════════════════════════════════════════
# 可视面板 — 组件视角
# ════════════════════════════════════════════════════════════
@app.get("/api/visualization/component-view")
def component_view(tenant_id: Optional[int] = None):
    con = get_conn()
    try:
        where = "WHERE tc.tenant_id = ?" if tenant_id else ""
        params = [tenant_id] if tenant_id else []
        rows = con.execute(f"""
            SELECT ra.id AS alloc_id, ra.role_name, ra.role_seq, ra.node_id, ra.cpu, ra.memory, ra.status,
                   n.node_code, n.machine_name, n.series,
                   h.cpu_cores AS node_cpu, h.memory_gb AS node_mem,
                   tc.id AS tc_id, tc.component_name, tc.instance_label,
                   tc.tenant_id, t.tenant_name
            FROM role_allocation ra
            JOIN tenant_component tc ON tc.id = ra.tenant_component_id
            JOIN tenant t ON t.id = tc.tenant_id
            JOIN physical_node n ON n.id = ra.node_id
            JOIN hardware_config h ON h.id = n.hardware_config_id
            {where}
            ORDER BY t.id, tc.id, ra.role_name, ra.role_seq
        """, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


# ════════════════════════════════════════════════════════════
# 可视面板 — 服务器视角
# ════════════════════════════════════════════════════════════
@app.get("/api/visualization/node-view")
def node_view(node_id: Optional[int] = None):
    con = get_conn()
    try:
        where = "WHERE ra.node_id = ?" if node_id else ""
        params = [node_id] if node_id else []
        rows = con.execute(f"""
            SELECT ra.id AS alloc_id, ra.role_name, ra.role_seq, ra.cpu, ra.memory, ra.status,
                   n.id AS node_id, n.node_code, n.machine_name, n.series,
                   h.cpu_cores AS node_cpu, h.memory_gb AS node_mem,
                   tc.id AS tc_id, tc.component_name, tc.instance_label,
                   tc.tenant_id, t.tenant_name
            FROM role_allocation ra
            JOIN tenant_component tc ON tc.id = ra.tenant_component_id
            JOIN tenant t ON t.id = tc.tenant_id
            JOIN physical_node n ON n.id = ra.node_id
            JOIN hardware_config h ON h.id = n.hardware_config_id
            {where}
            ORDER BY n.id, ra.role_name, ra.role_seq
        """, params).fetchall()
        # also get per-node usage summary
        result = [dict(r) for r in rows]
        return result
    finally:
        con.close()


# ════════════════════════════════════════════════════════════
# 可视面板 — 服务器视角汇总
# ════════════════════════════════════════════════════════════
@app.get("/api/visualization/node-summary")
def node_summary():
    con = get_conn()
    try:
        rows = con.execute("""
            SELECT n.id, n.node_code, n.machine_name, n.series,
                   h.cpu_cores, h.memory_gb,
                   COALESCE(SUM(ra.cpu), 0) AS role_cpu_used,
                   COALESCE(SUM(ra.memory), 0) AS role_mem_used
            FROM physical_node n
            JOIN hardware_config h ON h.id = n.hardware_config_id
            LEFT JOIN role_allocation ra ON ra.node_id = n.id AND ra.status = 'active'
            WHERE n.status = 'active'
            GROUP BY n.id
            ORDER BY n.series, n.node_code
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()
