# Bridge Skill — UAV Survey → Constructable Engineering Drawings

从无人机勘探到可建造桥梁施工图的全流程管道。每个步骤独立可调用。

## 触发条件

当用户提到：
- 桥梁/桥/UAV/无人机 勘测/点云/施工图/图纸/3D模型
- "处理这个点云" / "生成桥梁图纸" / "设计一座桥"
- bridge survey / point cloud / bridge drawing / bridge model

## 管道总览

```
  无人机影像 (.jpg/.tif)
      │
      ▼ [ODM — 可选]
  LAS/LAZ 点云
      │
      ├── Step 1: 点云处理 → bridge_params.json
      │       bridge_pipeline.py
      │       ↓
      ├── Step 2: 工程设计 → detailed_design.json
      │       bridge_designer.py
      │       ↓
      ├── Step 3: 3D建模 → bridge.FCStd + .step + .stl
      │       freecad_bridge.py (freecadcmd)
      │       ↓
      └── Step 4: 施工图 → 4张专业SVG图纸
              bridge_drawing.py
```

## 各步骤详解

### Step 0: 点云获取（生成合成数据 或 真实UAV数据）

**合成数据（测试用）：**
```bash
# 简单合成 (134K点，高斯噪声)
conda run -n bridge_skill python ~/bridge_skill/generate_synthetic_data.py \
    --span 30 --width 8 --pier-height 5 --output bridge.las

# 真实感仿真 (254K点，UAV飞行线+植被+水+遮挡)
conda run -n bridge_skill python ~/bridge_skill/generate_realistic_data.py \
    --span 30 --width 8 --pier-height 5 --density medium --output bridge_realistic.las
```

**真实UAV数据（需要ODM）：**
```bash
docker pull opendronemap/odm
docker run -v /data:/datasets opendronemap/odm --project-path /datasets project
```

**从USGS 3DEP下载公共LiDAR数据（需要注册OpenTopography）：**
- 访问 https://opentopography.org → Data → Find Data Map
- 选择区域 → 下载LAS格式

---

### Step 1: 点云处理 → 结构参数提取

**命令：**
```bash
conda run -n bridge_skill python ~/bridge_skill/bridge_pipeline.py \
    <input.las> -o bridge_params.json --bridge-type auto
```

**输入：** `.las` / `.laz` 点云文件
**输出：** `bridge_params.json`

**关键参数：**
| 参数 | 默认 | 说明 |
|------|------|------|
| `--voxel-size` | 0.1 | 降采样分辨率 (m) |
| `--ransac-threshold` | 0.15 | RANSAC平面距离阈值 (m) |
| `--dbscan-eps` | 0.5 | DBSCAN聚类半径 (m) |
| `--dbscan-min-points` | 30 | DBSCAN最小点数（噪声大时提高） |
| `--bridge-type` | auto | beam / arch / auto |
| `--no-class-filter` | — | 禁用植被分类过滤 |

**输出JSON关键字段：**
```json
{
  "bridge_type": "beam",
  "dimensions": {"span_length": 30.06, "deck_width": 8.07, "clearance_under_bridge": 6.1, "num_piers": 2},
  "centerline": {"start": [...], "end": [...], "axis_direction": [...]},
  "pier_positions": [{"x": 6.0, "height": 5.0}, ...],
  "terrain_profile": [{"x": ..., "z": ...}, ...],
  "span_segments": [9.05, 12.0, 9.02]
}
```

---

### Step 2: 工程结构设计

**命令：**
```bash
conda run -n bridge_skill python ~/bridge_skill/bridge_designer.py \
    bridge_params.json -o detailed_design.json --design-code AASHTO
```

**输入：** `bridge_params.json`（Step 1 输出）
**输出：** `detailed_design.json`

**根据跨径自动选型：**
| 跨度 | 自动方案 |
|------|---------|
| ≤15m | T型梁 (RC) |
| 15-35m | I型梁 (RC) |
| 35-42m | 预应力I型梁 (AASHTO标准截面) |
| 42-50m | 预应力(超限) — 建议连续梁或钢梁 |
| >50m | 尝试预应力+警告 — 建议钢梁或节段施工 |

**参数：**
| 参数 | 默认 | 说明 |
|------|------|------|
| `--design-code` | AASHTO | AASHTO / CHN |
| `--live-load` | HL93 | HL93 / CL1 |

**输出包含：** 梁截面选型、配筋设计、预应力束设计、荷载计算、应力验算、材料清单(BOM)

---

### Step 3: FreeCAD 3D建模

**必须通过 freecadcmd 运行（不是标准Python）：**
```bash
cd <output_dir>
cp ~/bridge_skill/freecad_bridge.py .

# 创建运行配置
cat > freecad_config.json <<'EOF'
{
  "params": "detailed_design.json",
  "output": "bridge.FCStd",
  "drawing": "bridge_drawing.svg",
  "analyze": false
}
EOF

# 运行建模
~/miniconda3/envs/bridge_skill/bin/freecadcmd -c <<'FREECADEOF'
import sys, json
sys.path.insert(0, ".")
with open("freecad_config.json") as f: config = json.load(f)
exec(open("freecad_bridge.py").read())
FREECADEOF
```

**输入：** `detailed_design.json` 或 `bridge_params.json`
**输出：** `bridge.FCStd` + `bridge.step` + `bridge.stl`

**支持的桥型：** 简支梁（I型梁+盖梁+支座+栏杆）、拱桥（抛物线拱肋+立柱）

---

### Step 4: 施工图纸生成

**命令：**
```bash
conda run -n bridge_skill python ~/bridge_skill/bridge_drawing.py \
    detailed_design.json -o ./drawings --all
```

**输入：** `detailed_design.json`（Step 2 输出）
**输出：** `drawings/` 目录下4张SVG图纸

| 图纸 | 文件 | 内容 |
|------|------|------|
| GA-01 | `GA_drawing.svg` | 总体布置：平面+立面+横断面 |
| SS-01 | `Superstructure_drawing.svg` | 主梁截面+配筋图+钢筋表 |
| SS-02 | `Substructure_drawing.svg` | 桥墩立面+断面+桥台详图 |
| BOM-01 | `BOM_table.svg` | 材料清单+规格说明 |

**所有图纸均包含：** 图框、标题栏（图号、版次、比例、日期）、尺寸标注、材料填充

---

### 一键运行（全管道）

```bash
# 演示：合成数据全流程
~/bridge_skill/run_bridge_skill.sh --generate-synthetic

# 真实感仿真
~/bridge_skill/run_bridge_skill.sh --generate-synthetic --realistic

# 拱桥
~/bridge_skill/run_bridge_skill.sh --generate-synthetic --bridge-type arch --span 40

# 真实点云
~/bridge_skill/run_bridge_skill.sh <input.las> <output_dir>

# 中国规范
~/bridge_skill/run_bridge_skill.sh <input.las> <output_dir> --design-code CHN
```

## 环境

- **Conda env:** `bridge_skill` (Python 3.10, open3d, laspy, numpy, scipy, freecad=0.21.2)
- **FreeCAD:** `/home/wayne/miniconda3/envs/bridge_skill/bin/freecadcmd`
- **管道脚本:** `~/bridge_skill/`

## 关键文件

| 文件 | 功能 | 独立运行 |
|------|------|---------|
| `generate_synthetic_data.py` | 简单合成点云 | ✅ |
| `generate_realistic_data.py` | 真实感UAV仿真点云 | ✅ |
| `bridge_pipeline.py` | 点云→参数 (RANSAC+DBSCAN+PCA) | ✅ |
| `bridge_designer.py` | 参数→工程设计 (配筋+预应力+BOM) | ✅ |
| `freecad_bridge.py` | 设计→3D模型 (必须freecadcmd) | ✅ |
| `bridge_drawing.py` | 设计→施工图 (4张SVG) | ✅ |
| `run_bridge_skill.sh` | 一键管道入口 | ✅ |
