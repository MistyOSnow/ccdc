#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate init.sql from cpu使用.csv and xlsx_data.json
"""

import csv
import json
import re
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "cpu使用.csv")
JSON_PATH = os.path.join(BASE_DIR, "xlsx_data.json")
SQL_PATH = os.path.join(BASE_DIR, "init.sql")

# ============================================================
# 1. Read and parse CSV
# ============================================================
def read_csv():
    nodes = []
    with open(CSV_PATH, encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)  # skip header
        for row in reader:
            # skip empty rows
            if not row or not row[0].strip():
                continue
            hw_type = row[0].strip()
            node_code = row[1].strip()
            machine_name = row[2].strip()
            total_cpu_str = row[3].strip()
            total_mem_str = row[4].strip()

            # Parse CPU allocations (cols 5-10: 3 pairs of name,cpu)
            cpu_slots = []
            for i in range(5, 11, 2):
                name = row[i].strip() if i < len(row) else ''
                cpu_val = row[i+1].strip() if i+1 < len(row) else ''
                cpu_slots.append((name, cpu_val))

            # Parse Memory allocations (cols 11-16: 3 pairs of name,mem)
            mem_slots = []
            for i in range(11, 17, 2):
                name = row[i].strip() if i < len(row) else ''
                mem_val = row[i+1].strip() if i+1 < len(row) else ''
                mem_slots.append((name, mem_val))

            nodes.append({
                'hw_type': hw_type,
                'node_code': node_code,
                'machine_name': machine_name,
                'total_cpu': total_cpu_str,
                'total_mem': total_mem_str,
                'cpu_slots': cpu_slots,
                'mem_slots': mem_slots,
            })
    return nodes


# ============================================================
# 2. Read and parse xlsx_data.json (disk allocation)
# ============================================================
def read_disk_json():
    with open(JSON_PATH, encoding='utf-8') as f:
        data = json.load(f)
    return data['存储分配']


def parse_disk_data(rows):
    """
    Parse the 2D array from xlsx_data.json into a mapping:
    machine_name -> list of (disk_name_raw, region_label)

    The structure has groups separated by null rows. Each group starts with
    a header row containing machine names, followed by disk rows.
    """
    machine_disks = {}  # machine_name -> [(disk_name_raw, region_label)]

    i = 0
    current_region = None
    current_machines = []

    while i < len(rows):
        row = rows[i]

        # Check if this is a separator row (all nulls or all empty)
        is_separator = all(v is None or (isinstance(v, str) and v.strip() == '') for v in row)

        if is_separator:
            i += 1
            continue

        # Check if this is a header row (first column is null, rest are machine names)
        first_col = row[0]
        if first_col is None or (isinstance(first_col, str) and first_col.strip() == ''):
            # Check if remaining cols look like machine names (testNNN)
            non_null_cols = [v for v in row[1:] if v is not None and isinstance(v, str) and v.strip()]
            machine_like = [v for v in non_null_cols if re.match(r'test\d+', v.strip())]

            if machine_like:
                # This is a header row with machine names
                current_machines = []
                for v in row[1:]:
                    if v is not None and isinstance(v, str) and v.strip():
                        name = v.strip()
                        if re.match(r'test\d+', name):
                            current_machines.append(name)
                            if name not in machine_disks:
                                machine_disks[name] = []
                current_region = None
                i += 1
                continue

        # This is a data row with (region, disk1, disk2, disk3, disk4, ...)
        if current_machines:
            # First column might be a region label
            # If first column is null/empty, this disk row is UNASSIGNED (no tenant)
            region_label = None
            if first_col is not None and isinstance(first_col, str) and first_col.strip():
                region_label = first_col.strip()
                current_region = region_label
            else:
                # Null first column means unassigned - do NOT inherit previous region
                current_region = None

            # Cols 1-4 correspond to current_machines[0..3]
            for j, mach in enumerate(current_machines):
                col_idx = j + 1
                if col_idx < len(row):
                    disk_val = row[col_idx]
                    if disk_val is not None and isinstance(disk_val, str) and disk_val.strip():
                        machine_disks[mach].append((disk_val.strip(), current_region))

        i += 1

    return machine_disks


# ============================================================
# 3. Tenant definitions
# ============================================================
# Define tenant list manually based on CSV analysis
TENANTS = [
    # id, tenant_code, tenant_name, region, tier, status
    (1,  't01', '北京局', '北京', 1, 'active'),
    (2,  't02', '上海局', '上海', 1, 'active'),
    (3,  't03', '浙江局', '浙江', 1, 'active'),
    (4,  't04', '江苏局', '江苏', 1, 'active'),
    (5,  't05', '广东局', '广东', 1, 'active'),
    (6,  't06', '深圳局', '深圳', 1, 'active'),
    (7,  't07', '云南局', '云南', 2, 'active'),
    (8,  't08', '安徽局', '安徽', 2, 'active'),
    (9,  't09', '贵州局', '贵州', 2, 'active'),
    (10, 't10', '山西局', '山西', 2, 'active'),
    (11, 't11', '厦门局', '厦门', 2, 'active'),
    (12, 't12', '山东局', '山东', 2, 'active'),
    (13, 't13', '海南局', '海南', 2, 'active'),
    (14, 't14', '辽宁局', '辽宁', 2, 'active'),
    (15, 't15', '河北局', '河北', 2, 'active'),
    (16, 't16', '吉林局', '吉林', 2, 'active'),
    (17, 't17', '内蒙局', '内蒙古', 2, 'active'),
    (18, 't18', '重庆局', '重庆', 2, 'active'),
    (19, 't19', '陕西局', '陕西', 2, 'active'),
    (20, 't20', '四川局', '四川', 2, 'returned'),
    (21, 't21', '青岛局', '青岛', 2, 'reserved'),
    (22, 't22', '广西局', '广西', 2, 'reserved'),
    (23, 't23', '黑龙江局', '黑龙江', 2, 'active'),
    (24, 't24', '待分配24', None, 2, 'pending'),
    (25, 't25', '待分配25', None, 2, 'pending'),
    (26, 't26', '待分配26', None, 2, 'pending'),
    (27, 't27', '宁波局', '宁波', 2, 'active'),
    (28, 't28', '待分配28', None, 2, 'pending'),
    # 一表通 tenants (tier=0, independent)
    (29, 'ybt01', '北京-一表通', '北京', 0, 'active'),
    (30, 'ybt02', '上海-一表通', '上海', 0, 'active'),
    (31, 'ybt03', '江苏-一表通', '江苏', 0, 'active'),
    (32, 'ybt04', '深圳-一表通', '深圳', 0, 'active'),
    (33, 'ybt05', '重庆一表通', '重庆', 0, 'active'),
    (34, 'ybt06', '吉林一表通', '吉林', 0, 'active'),
]

# Build name-to-id mapping
TENANT_NAME_MAP = {}
for t in TENANTS:
    TENANT_NAME_MAP[t[2]] = t[0]

# Mapping from CSV tenant names to our clean names
# The CSV uses formats like:
#   "第一档-北京局", "第一档-租户1-北京局", "第二档-租户7-云南局"
#   "北京-一表通", "上海-一表通", "江苏-一表通-quark1", "江苏-一表通-quark2"
#   "深圳-一表通", "重庆一表通", "吉林一表通"
#   "第二档-租户20-四川局（申请退回）", "第二档-租户21-青岛预留", etc.
#   "第二档-租户28-租户待分配", "第二档-租户24-租户待分配"
#   "第二档-租户21（青岛-预分配，测试是已修改ip，所以保留青岛）"
#   "第二档-租户22（广西-预分配，测试是已修改ip，所以保留青岛）"
#   "资源满", "租户待分配", "待分配", "第一档-租户待分配"

def csv_tenant_name_to_id(raw_name, cpu_val_str=''):
    """Map a CSV tenant name to our tenant ID. Returns None for placeholders."""
    if not raw_name:
        return None

    name = raw_name.strip()

    # Skip placeholders
    if name in ('资源满', '租户待分配', '待分配', '第一档-租户待分配'):
        return None

    # 一表通 quark variants -> map to the base 一表通 tenant
    if '江苏-一表通-quark' in name:
        return TENANT_NAME_MAP.get('江苏-一表通')

    # 一表通 direct matches
    ybt_map = {
        '北京-一表通': '北京-一表通',
        '上海-一表通': '上海-一表通',
        '江苏-一表通': '江苏-一表通',
        '深圳-一表通': '深圳-一表通',
        '重庆一表通': '重庆一表通',
        '吉林一表通': '吉林一表通',
    }
    if name in ybt_map:
        return TENANT_NAME_MAP.get(ybt_map[name])

    # Regional bureau mapping from CSV naming patterns
    # Handle patterns like "第二档-租户9-贵州局", "第一档-北京局", "第一档-租户1-北京局"
    region_map = {
        '北京局': '北京局',
        '上海局': '上海局',
        '浙江局': '浙江局',
        '江苏局': '江苏局',
        '广东局': '广东局',
        '深圳局': '深圳局',
        '云南局': '云南局',
        '安徽局': '安徽局',
        '贵州局': '贵州局',
        '山西局': '山西局',
        '厦门局': '厦门局',
        '山东局': '山东局',
        '海南局': '海南局',
        '辽宁局': '辽宁局',
        '河北局': '河北局',
        '吉林局': '吉林局',
        '内蒙局': '内蒙局',
        '重庆局': '重庆局',
        '陕西局': '陕西局',
        '宁波局': '宁波局',
        '黑龙江': '黑龙江局',  # CSV sometimes uses "黑龙江" without "局"
    }

    # Special cases for Sichuan/Qingdao/Guangxi with annotations
    special_map = {
        '四川局（申请退回）': '四川局',
        '青岛预留': '青岛局',
        '青岛（预留）': '青岛局',
        '广西局（预留）': '广西局',
        '广西预留': '广西局',
    }

    # Check for "第二档-租户21（青岛-预分配" pattern
    if '租户21' in name and ('青岛' in name or '预分配' in name):
        return TENANT_NAME_MAP.get('青岛局')
    if '租户22' in name and ('广西' in name or '预分配' in name):
        return TENANT_NAME_MAP.get('广西局')

    # Check for "第二档-租户20-四川局（申请退回）"
    if '四川' in name:
        return TENANT_NAME_MAP.get('四川局')

    # Check for pending tenant slots (t24-t28)
    if '租户24' in name or '租户待分配24' in name:
        return TENANT_NAME_MAP.get('待分配24')
    if '租户25' in name:
        return TENANT_NAME_MAP.get('待分配25')
    if '租户26' in name:
        return TENANT_NAME_MAP.get('待分配26')
    if '租户28' in name:
        return TENANT_NAME_MAP.get('待分配28')

    # "第二档-租户23-黑龙江" or "第二档-租户23"
    if '租户23' in name:
        return TENANT_NAME_MAP.get('黑龙江局')

    # "第二档-租户21-青岛预留"
    if '租户21' in name and '青岛' in name:
        return TENANT_NAME_MAP.get('青岛局')

    # "第二档-租户22-广西预留"
    if '租户22' in name and '广西' in name:
        return TENANT_NAME_MAP.get('广西局')

    # Check special map
    for key, val in special_map.items():
        if key in name:
            return TENANT_NAME_MAP.get(val)

    # Check region_map - try to find a region name in the CSV name
    for region_key, clean_name in region_map.items():
        if region_key in name:
            tid = TENANT_NAME_MAP.get(clean_name)
            if tid:
                return tid

    # "第一档-租户6深圳局" (no dash between 6 and 深圳)
    if '深圳局' in name:
        return TENANT_NAME_MAP.get('深圳局')

    # "第二档-租户27-宁波局" or "第二档-宁波局"
    if '宁波局' in name:
        return TENANT_NAME_MAP.get('宁波局')

    # Handle "第二档-租户25" (no region name, just number)
    if '租户25' in name:
        return TENANT_NAME_MAP.get('待分配25')
    if '租户26' in name:
        return TENANT_NAME_MAP.get('待分配26')

    # "第二档-内蒙局"
    if '内蒙局' in name:
        return TENANT_NAME_MAP.get('内蒙局')

    # Handle partial matches for some edge cases
    if '河北局' in name:
        return TENANT_NAME_MAP.get('河北局')
    if '海南局' in name:
        return TENANT_NAME_MAP.get('海南局')

    # "第一档-深圳局" in B series
    if '深圳局' in name:
        return TENANT_NAME_MAP.get('深圳局')

    # Fallback for numbered tenant refs like "第二档-租户26"
    if re.search(r'租户26', name):
        return TENANT_NAME_MAP.get('待分配26')
    if re.search(r'租户25', name):
        return TENANT_NAME_MAP.get('待分配25')
    if re.search(r'租户28', name):
        return TENANT_NAME_MAP.get('待分配28')
    if re.search(r'租户24', name):
        return TENANT_NAME_MAP.get('待分配24')

    print(f"WARNING: Could not map tenant name: '{name}'")
    return None


# ============================================================
# 4. Disk tenant name mapping (from xlsx region labels to tenant IDs)
# ============================================================
def disk_region_to_tenant_id(region_label):
    """Map a disk region label from xlsx_data.json to our tenant ID."""
    if not region_label:
        return None

    label = region_label.strip()

    region_map = {
        '山西': '山西局',
        '贵州': '贵州局',
        '安徽': '安徽局',
        '云南': '云南局',
        '山东': '山东局',
        '厦门': '厦门局',
        '辽宁': '辽宁局',
        '海南局': '海南局',
        '吉林局': '吉林局',
        '河北局': '河北局',
        '内蒙': '内蒙局',
        '重庆': '重庆局',
        '陕西': '陕西局',
        '黑龙江': '黑龙江局',
        '宁波局': '宁波局',
    }

    clean_name = region_map.get(label)
    if clean_name:
        return TENANT_NAME_MAP.get(clean_name)

    return None


# ============================================================
# 5. Parse CPU value (handles "租户待分配:20", "未申请:32", plain numbers, etc.)
# ============================================================
def parse_cpu_value(val_str):
    """
    Returns (cpu_number, status)
    - "24" -> (24, 'active')
    - "租户待分配:20" -> (0, 'pending')
    - "未申请:32" -> (0, 'pending')
    - "租户待分配" -> (0, 'pending')
    - "" -> (0, 'pending')
    """
    if not val_str:
        return (0, 'pending')

    val = val_str.strip()

    if not val:
        return (0, 'pending')

    # Pure number
    try:
        return (int(val), 'active')
    except ValueError:
        pass

    # "租户待分配:20" or "未申请:32"
    m = re.match(r'^(租户待分配|未申请)[:：](\d+)$', val)
    if m:
        return (0, 'pending')

    # "租户待分配" alone
    if val in ('租户待分配', '未申请'):
        return (0, 'pending')

    # Fallback
    print(f"WARNING: Could not parse CPU value: '{val}'")
    return (0, 'pending')


def parse_mem_value(val_str):
    """Parse memory value - same logic as CPU but simpler (usually just numbers)."""
    if not val_str:
        return (0, 'pending')

    val = val_str.strip()

    if not val:
        return (0, 'pending')

    try:
        return (int(val), 'active')
    except ValueError:
        pass

    if val in ('租户待分配', '未申请', '待分配'):
        return (0, 'pending')

    # "租户待分配:N" pattern
    m = re.match(r'^(租户待分配|未申请)[:：](\d+)$', val)
    if m:
        return (0, 'pending')

    print(f"WARNING: Could not parse memory value: '{val}'")
    return (0, 'pending')


# ============================================================
# 6. Parse disk name and status from xlsx raw value
# ============================================================
def parse_disk_entry(disk_raw, region_label):
    """
    Parse a disk entry like "disk7（待退役）", "disk9（待扩容）", "disk8(北京局扩容）"
    Returns (disk_name_clean, disk_status, tenant_id_override)
    """
    if not disk_raw:
        return None

    val = disk_raw.strip()
    if not val:
        return None

    disk_name = val
    disk_status = 'normal'
    tenant_id_override = None

    # Check for status annotations
    if '（待退役）' in val or '(待退役）' in val or '（待退役)' in val:
        disk_name = re.sub(r'[（(]待退役[）)]', '', val)
        disk_status = 'decommissioning'
    elif '（待扩容）' in val or '(待扩容）' in val or '（待扩容)' in val:
        disk_name = re.sub(r'[（(]待扩容[）)]', '', val)
        disk_status = 'expanding'
    elif '北京局扩容' in val:
        disk_name = re.sub(r'[（(]北京局扩容[）)]', '', val)
        disk_status = 'expanding'
        tenant_id_override = TENANT_NAME_MAP.get('北京局')

    # Derive tenant_id from region label
    tid = disk_region_to_tenant_id(region_label)
    if tenant_id_override is not None:
        tid = tenant_id_override

    return (disk_name, disk_status, tid)


# ============================================================
# 7. Main generation logic
# ============================================================
def generate_sql():
    nodes = read_csv()
    disk_rows = read_disk_json()
    machine_disks = parse_disk_data(disk_rows)

    lines = []
    def w(s=''):
        lines.append(s)

    # Header
    w("-- ============================================================")
    w("--  资源分配看板 — SQLite 建表语句 + 完整数据")
    w("--  自动生成 by generate_sql.py")
    w("--  适用：DBeaver 连接 SQLite 文件后，全选执行")
    w("-- ============================================================")
    w()
    w("PRAGMA foreign_keys = ON;")
    w()

    # Drop tables
    w("-- 建表（先删旧表，方便重复执行）")
    for tbl in ['role_allocation', 'tenant_component', 'role_template',
                'component_template', 'disk', 'cpu_memory_allocation',
                'physical_node', 'tenant', 'hardware_config']:
        w(f"DROP TABLE IF EXISTS {tbl};")
    w()

    # Create tables
    w("CREATE TABLE hardware_config (")
    w("    id          INTEGER PRIMARY KEY,")
    w("    config_name TEXT    NOT NULL,")
    w("    cpu_cores   INTEGER NOT NULL,")
    w("    memory_gb   INTEGER NOT NULL,")
    w("    description TEXT")
    w(");")
    w()

    w("CREATE TABLE physical_node (")
    w("    id                 INTEGER PRIMARY KEY,")
    w("    node_code          TEXT    NOT NULL UNIQUE,")
    w("    machine_name       TEXT    NOT NULL,")
    w("    hardware_config_id INTEGER NOT NULL REFERENCES hardware_config(id),")
    w("    series             TEXT    NOT NULL,")
    w("    status             TEXT    NOT NULL DEFAULT 'active',")
    w("    created_at         TEXT    NOT NULL DEFAULT (datetime('now','localtime'))")
    w(");")
    w()

    w("CREATE TABLE tenant (")
    w("    id          INTEGER PRIMARY KEY,")
    w("    tenant_code TEXT    NOT NULL UNIQUE,")
    w("    tenant_name TEXT    NOT NULL,")
    w("    region      TEXT,")
    w("    tier        INTEGER,")  # changed from NOT NULL DEFAULT 2 to allow NULL for 一表通
    w("    status      TEXT    NOT NULL DEFAULT 'active'")
    w(");")
    w()

    w("CREATE TABLE cpu_memory_allocation (")
    w("    id               INTEGER PRIMARY KEY,")
    w("    node_id          INTEGER NOT NULL REFERENCES physical_node(id),")
    w("    tenant_id        INTEGER NOT NULL REFERENCES tenant(id),")
    w("    cpu_allocated    INTEGER NOT NULL DEFAULT 0,")
    w("    memory_allocated INTEGER NOT NULL DEFAULT 0,")
    w("    alloc_status     TEXT    NOT NULL DEFAULT 'active',")
    w("    created_at       TEXT    NOT NULL DEFAULT (datetime('now','localtime')),")
    w("    updated_at       TEXT    NOT NULL DEFAULT (datetime('now','localtime'))")
    w(");")
    w()

    w("CREATE TABLE disk (")
    w("    id           INTEGER PRIMARY KEY,")
    w("    node_id      INTEGER NOT NULL REFERENCES physical_node(id),")
    w("    disk_name    TEXT    NOT NULL,")
    w("    disk_size_tb INTEGER NOT NULL,")
    w("    disk_status  TEXT    NOT NULL DEFAULT 'normal',")
    w("    tenant_id    INTEGER REFERENCES tenant(id),")
    w("    allocated_at TEXT")
    w(");")
    w()

    w("-- component_template（组件模板）")
    w("CREATE TABLE component_template (")
    w("    id          INTEGER PRIMARY KEY,")
    w("    name        TEXT    NOT NULL UNIQUE,")
    w("    description TEXT")
    w(");")
    w()

    w("-- role_template（角色模板）")
    w("CREATE TABLE role_template (")
    w("    id            INTEGER PRIMARY KEY,")
    w("    component_id  INTEGER NOT NULL REFERENCES component_template(id) ON DELETE CASCADE,")
    w("    role_name     TEXT    NOT NULL")
    w(");")
    w()

    w("-- tenant_component（租户组件实例）")
    w("CREATE TABLE tenant_component (")
    w("    id              INTEGER PRIMARY KEY,")
    w("    tenant_id       INTEGER NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,")
    w("    component_id    INTEGER REFERENCES component_template(id) ON DELETE SET NULL,")
    w("    component_name  TEXT    NOT NULL,")
    w("    instance_label  TEXT    NOT NULL DEFAULT '1',")
    w("    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))")
    w(");")
    w()

    w("-- role_allocation（角色分配明细）")
    w("CREATE TABLE role_allocation (")
    w("    id                    INTEGER PRIMARY KEY,")
    w("    tenant_component_id   INTEGER NOT NULL REFERENCES tenant_component(id) ON DELETE CASCADE,")
    w("    role_name             TEXT    NOT NULL,")
    w("    role_seq              INTEGER NOT NULL DEFAULT 1,")
    w("    node_id               INTEGER NOT NULL REFERENCES physical_node(id),")
    w("    cpu                   INTEGER NOT NULL DEFAULT 0,")
    w("    memory                INTEGER NOT NULL DEFAULT 0,")
    w("    status                TEXT    NOT NULL DEFAULT 'active',")
    w("    created_at            TEXT    NOT NULL DEFAULT (datetime('now','localtime'))")
    w(");")
    w()

    # ---- hardware_config ----
    w("-- hardware_config")
    hw_inserts = [
        (1, '配置二', 96, 512, '双路96核/512GB'),
        (2, '配置三', 96, 768, '双路96核/768GB'),
        (3, '配置五', 32, 256, '单路32核/256GB'),
        (4, '配置七', 32, 256, '单路32核/256GB 高密度'),
    ]
    w("INSERT INTO hardware_config (id,config_name,cpu_cores,memory_gb,description) VALUES")
    hw_vals = [f"  ({r[0]},'{r[1]}',{r[2]},{r[3]},'{r[4]}')" for r in hw_inserts]
    w(',\n'.join(hw_vals) + ';')
    w()

    # ---- tenant ----
    w("-- tenant")
    w("INSERT INTO tenant (id,tenant_code,tenant_name,region,tier,status) VALUES")
    t_vals = []
    for t in TENANTS:
        tier_val = str(t[4]) if t[4] is not None else 'NULL'
        region_val = f"'{t[3]}'" if t[3] else 'NULL'
        t_vals.append(f"  ({t[0]},'{t[1]}','{t[2]}',{region_val},{tier_val},'{t[5]}')")
    w(',\n'.join(t_vals) + ';')
    w()

    # ---- physical_node ----
    # Build node data from CSV
    # Hardware config mapping
    hw_config_map = {
        '配置二': 1,
        '配置三': 2,
        '配置五': 3,
        '配置七': 4,
    }

    # Series from node_code prefix
    def get_series(node_code):
        prefix = node_code[0]
        if prefix in ('A', 'B', 'C', 'D'):
            return prefix
        return 'X'

    node_id_counter = 1
    node_records = []  # (id, node_code, machine_name, hw_config_id, series, status)

    for n in nodes:
        nc = n['node_code']
        mn = n['machine_name']
        hw = n['hw_type']

        # Determine hardware_config_id
        # Special case: D052 is listed as 配置二 but has 32 CPU / 256 GB = 配置七
        if nc == 'D052':
            hw_config_id = 4  # 配置七
        else:
            hw_config_id = hw_config_map.get(hw, 4)

        series = get_series(nc)

        # Determine status
        if mn == 'TBD' or mn == '备用' or mn == '':
            status = 'standby'
        elif nc in ('D001', 'D002', 'D003', 'D004'):
            status = 'standby'
        elif nc in ('D059', 'D060'):
            status = 'standby'
        else:
            status = 'active'

        node_records.append((node_id_counter, nc, mn, hw_config_id, series, status))
        node_id_counter += 1

    w("-- physical_node")
    w("INSERT INTO physical_node (id,node_code,machine_name,hardware_config_id,series,status) VALUES")
    pn_vals = [f"  ({r[0]},'{r[1]}','{r[2]}',{r[3]},'{r[4]}','{r[5]}')" for r in node_records]
    w(',\n'.join(pn_vals) + ';')
    w()

    # Build node_code -> node_id map
    node_code_to_id = {r[1]: r[0] for r in node_records}
    # Build machine_name -> node_id map
    machine_to_node_id = {r[2]: r[0] for r in node_records if r[2]}

    # ---- cpu_memory_allocation ----
    w("-- cpu_memory_allocation")

    alloc_records = []  # (node_id, tenant_id, cpu_allocated, memory_allocated, alloc_status)

    for n in nodes:
        node_id = node_code_to_id.get(n['node_code'])
        if node_id is None:
            continue

        # Skip nodes with no allocations (standby/empty)
        if n['node_code'] in ('D059', 'D060') or n['machine_name'] == 'TBD':
            continue

        # Combine CPU and memory slots
        # CPU slots: [(name1, cpu1), (name2, cpu2), (name3, cpu3)]
        # Memory slots: [(name1, mem1), (name2, mem2), (name3, mem3)]
        # Positionally, slot i CPU name and slot i memory name refer to the same slot
        # They may differ (e.g., CPU has a real tenant, memory has "租户待分配" placeholder)
        # We use the CPU name as primary, and fall back to memory name if CPU name is placeholder

        # Build tenant -> (cpu, memory) mapping for this node
        tenant_allocs = {}  # tenant_id -> (cpu, memory, cpu_status, mem_status)

        for i in range(3):
            cpu_name = n['cpu_slots'][i][0] if i < len(n['cpu_slots']) else ''
            cpu_val_str = n['cpu_slots'][i][1] if i < len(n['cpu_slots']) else ''
            mem_name = n['mem_slots'][i][0] if i < len(n['mem_slots']) else ''
            mem_val_str = n['mem_slots'][i][1] if i < len(n['mem_slots']) else ''

            # Determine tenant ID
            # Use CPU name as primary, but if CPU name is "资源满", check memory name
            if cpu_name == '资源满':
                # The CPU slot is full, but memory might have a different tenant
                if mem_name and mem_name not in ('租户待分配', '待分配', '资源满', ''):
                    tid = csv_tenant_name_to_id(mem_name)
                    if tid is not None:
                        mem_num, mem_status = parse_mem_value(mem_val_str)
                        if tid in tenant_allocs:
                            existing = tenant_allocs[tid]
                            tenant_allocs[tid] = (
                                existing[0],
                                existing[1] + mem_num,
                                existing[2],
                                mem_status if mem_status != 'active' else existing[3],
                            )
                        else:
                            tenant_allocs[tid] = (0, mem_num, 'pending', mem_status)
                continue

            tid = csv_tenant_name_to_id(cpu_name, cpu_val_str)

            # If CPU name is a placeholder but memory name has a tenant
            if tid is None and mem_name:
                tid = csv_tenant_name_to_id(mem_name)

            if tid is None:
                continue

            cpu_num, cpu_status = parse_cpu_value(cpu_val_str)
            mem_num, mem_status = parse_mem_value(mem_val_str)

            # Merge with existing entry for same tenant on same node
            # This handles cases like 江苏-一表通-quark1 and 江苏-一表通-quark2
            # which map to the same tenant_id (31)
            if tid in tenant_allocs:
                existing = tenant_allocs[tid]
                tenant_allocs[tid] = (
                    existing[0] + cpu_num,
                    existing[1] + mem_num,
                    cpu_status if cpu_status != 'active' else existing[2],
                    mem_status if mem_status != 'active' else existing[3],
                )
            else:
                tenant_allocs[tid] = (cpu_num, mem_num, cpu_status, mem_status)

        for tid, (cpu_num, mem_num, cpu_st, mem_st) in tenant_allocs.items():
            # Determine overall status
            if cpu_num > 0 or mem_num > 0:
                alloc_status = 'active'
            else:
                alloc_status = 'pending'

            alloc_records.append((node_id, tid, cpu_num, mem_num, alloc_status))

    # For standby D001-D004 nodes, add allocation for pending tenant if specified
    for n in nodes:
        if n['node_code'] in ('D001', 'D002', 'D003', 'D004'):
            node_id = node_code_to_id.get(n['node_code'])
            if node_id is None:
                continue
            # These have "第一档-租户待分配" as tenant - which is a placeholder
            # We don't create allocation for "租户待分配" placeholder
            pass

    w("INSERT INTO cpu_memory_allocation (node_id,tenant_id,cpu_allocated,memory_allocated,alloc_status) VALUES")
    alloc_vals = [f"  ({r[0]},{r[1]},{r[2]},{r[3]},'{r[4]}')" for r in alloc_records]
    w(',\n'.join(alloc_vals) + ';')
    w()

    # ---- disk ----
    w("-- disk")

    disk_records = []  # (node_id, disk_name, disk_size_tb, disk_status, tenant_id, allocated_at)

    for nr in node_records:
        node_id = nr[0]
        machine_name = nr[2]
        series = nr[4]

        if series == 'D' and machine_name and machine_name in machine_disks:
            # Use actual disk data from xlsx
            disk_entries = machine_disks[machine_name]

            # Track which disk numbers we've seen
            seen_disk_nums = set()

            for disk_raw, region_label in disk_entries:
                parsed = parse_disk_entry(disk_raw, region_label)
                if parsed:
                    disk_name, disk_status, tid = parsed

                    # Extract disk number for ordering
                    m = re.match(r'disk(\d+)', disk_name)
                    if m:
                        seen_disk_nums.add(int(m.group(1)))

                    allocated_at = f"datetime('now','localtime')" if tid is not None else 'NULL'
                    disk_records.append((node_id, disk_name, 10, disk_status, tid, allocated_at))

            # Add any missing disks (1-12) as unassigned normal disks
            for dn in range(1, 13):
                if dn not in seen_disk_nums:
                    disk_records.append((node_id, f'disk{dn}', 10, 'normal', None, 'NULL'))

        elif series in ('A', 'B', 'C') or (series == 'D' and (not machine_name or machine_name not in machine_disks)):
            # For A/B/C series or D series without xlsx data: 12 disks, all unassigned
            # Also for D standby nodes without machine names
            for dn in range(1, 13):
                disk_records.append((node_id, f'disk{dn}', 10, 'normal', None, 'NULL'))

    # Sort disk records by (node_id, disk_name) for consistent ordering
    def disk_sort_key(r):
        m = re.match(r'disk(\d+)', r[1])
        num = int(m.group(1)) if m else 0
        return (r[0], num)

    disk_records.sort(key=disk_sort_key)

    # Group insert by node for readability
    w("INSERT INTO disk (node_id,disk_name,disk_size_tb,disk_status,tenant_id,allocated_at) VALUES")
    d_vals = []
    for r in disk_records:
        tid_str = str(r[4]) if r[4] is not None else 'NULL'
        d_vals.append(f"  ({r[0]},'{r[1]}',{r[2]},'{r[3]}',{tid_str},{r[5]})")
    w(',\n'.join(d_vals) + ';')
    w()

    # ---- component_template, role_template ----
    w("-- 示例模板数据")
    w("INSERT INTO component_template (id, name, description) VALUES")
    w("  (1, 'HDFS',  'Hadoop 分布式文件系统'),")
    w("  (2, 'YARN',  '资源管理框架'),")
    w("  (3, 'HBase', '分布式列式数据库'),")
    w("  (4, 'Kafka', '分布式消息队列'),")
    w("  (5, 'Spark', '分布式计算引擎'),")
    w("  (6, 'Flink', '流式计算引擎'),")
    w("  (7, 'ZooKeeper', '分布式协调服务');")
    w()

    w("INSERT INTO role_template (component_id, role_name) VALUES")
    w("  (1, 'NameNode'), (1, 'SNN'), (1, 'DataNode'), (1, 'JournalNode'),")
    w("  (2, 'ResourceManager'), (2, 'NodeManager'),")
    w("  (3, 'HMaster'), (3, 'RegionServer'),")
    w("  (4, 'Broker'), (4, 'Controller'),")
    w("  (5, 'Master'), (5, 'Worker'),")
    w("  (6, 'JobManager'), (6, 'TaskManager'),")
    w("  (7, 'QuorumPeer');")
    w()

    # Write to file
    with open(SQL_PATH, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f"Generated {SQL_PATH}")
    print(f"  Nodes: {len(node_records)}")
    print(f"  CPU/Memory allocations: {len(alloc_records)}")
    print(f"  Disk records: {len(disk_records)}")


if __name__ == '__main__':
    generate_sql()
