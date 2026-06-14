# Bridge Skill v0.3 — UAV Survey → Constructable Bridge Engineering Drawings

自动化管道：从无人机勘测点云到可建造的桥梁施工图。

## 概述

```
无人机影像
    │
    ▼ [ODM / 合成数据]
LAS 点云
    │
    ▼ bridge_pipeline.py  ← 增强: 地形剖面, 植被过滤, 拱桥检测, 多跨支持
bridge_params.json
    │
    ▼ bridge_designer.py  ← **新**: 工程结构设计 (AASHTO / JTG)
detailed_design.json     ← 配筋设计, 材料清单, 荷载分析
    │
    ├──► freecad_bridge.py  ← 增强: I型梁, 拱桥, 盖梁, 支座, 栏杆
    │    bridge.FCStd + .step + .stl
    │
    └──► bridge_drawing.py  ← **新**: 专业施工图
         drawings/
         ├── GA_drawing.svg              总体布置图
         ├── Superstructure_drawing.svg  主梁+桥面板构造图
         ├── Substructure_drawing.svg    桥墩+桥台构造图
         └── BOM_table.svg              材料清单+规格表
```

## 快速开始

```bash
# 1. 一键生成演示（合成数据 → 结构设计 → 3D模型 → 施工图）
./run_bridge_skill.sh --generate-synthetic

# 2. 真实感UAV仿真数据
./run_bridge_skill.sh --generate-synthetic --realistic

# 3. 拱桥
./run_bridge_skill.sh --generate-synthetic --bridge-type arch --span 40 --width 10

# 4. 查看输出
ls bridge_output/
ls bridge_output/drawings/
```

## 处理真实无人机数据

```bash
# 完整管道
./run_bridge_skill.sh /path/to/uav_survey.las ./my_bridge_output

# 指定设计规范
./run_bridge_skill.sh survey.las ./output --design-code CHN --live-load CL1

# 含结构分析
./run_bridge_skill.sh survey.las ./output --analyze
```

## 管道步骤详解

### 第1步：点云生成
- `generate_synthetic_data.py` — 简单合成点云 (简支梁桥)
- `generate_realistic_data.py` — 真实感仿真 (UAV飞行线, 植被, 水体, 遮挡)

### 第2步：结构提取 (增强)
`bridge_pipeline.py` — 从点云提取桥梁结构参数
- 体素降采样 + 植被分类过滤
- 多平面RANSAC (地面/桥面/其他)
- 桥面密度滤波 (DBSCAN去伪影)
- DBSCAN聚类 → 桥墩/桥台识别
- PCA主轴线 + 拱桥曲率检测
- **NEW**: 地形剖面提取 (沿桥轴40点采样)
- **NEW**: LAS分类标签植被预过滤
- **NEW**: 抛物线拱桥形状检测
- **NEW**: 多跨连续梁跨段计算

### 第3步：工程结构设计 (NEW)
`bridge_designer.py` — AASHTO LRFD / JTG D60 结构设计引擎
- 梁截面选型 (T型梁/I型梁/箱梁) → 按跨径自动选择
- 荷载计算 (恒载+铺装+栏杆+活载 HL-93/CL-1)
- 结构分析 (弯矩/剪力/挠度)
- 配筋设计 (受弯主筋+受剪箍筋)
- 桥墩设计 (柱+盖梁+支座选型+基础)
- 材料清单 (混凝土方量+钢筋重量+模板面积+支座数量)

### 第4步：参数化3D建模 (增强)
`freecad_bridge.py` — FreeCAD 精细参数化建模
- **I型梁**: 工字截面拉伸 (上翼缘+腹板+下翼缘)
- **桥面板**: 独立桥面板 + 路缘石
- **桥墩**: 矩形柱 + T型盖梁 + 支座垫石
- **栏杆**: 立柱 + 顶部扶手
- **拱桥**: 抛物线拱肋 + 立柱(拱上建筑)
- **桥台**: 台身 + 背墙 + 支座平台
- 多格式导出: FCStd + STEP + STL

### 第5步：专业施工图 (NEW)
`bridge_drawing.py` — 工程级SVG图纸生成 (独立模块, 不需要FreeCAD)
- 图框+标题栏 (项目名, 图号, 比例, 日期, 版次)
- 尺寸标注 (箭头+文字)
- 材料填充图案 (混凝土点, 钢筋斜线, 沥青黑色)
- 4张图纸:
  1. **总体布置图**: 平面+立面+横断面, 三视图完整标注
  2. **主梁构造图**: 工字钢截面, 配筋图, 钢筋表
  3. **下部结构图**: 桥墩立面+断面, 桥台详图
  4. **材料清单**: 混凝土表+钢筋表+其他材料+规格说明

## 输出详细说明

### detailed_design.json 格式

```json
{
  "bridge_type": "beam",
  "design_code": "AASHTO LRFD HL-93",
  "superstructure": {
    "girder_type": "I-beam",
    "num_girders": 3,
    "girder_depth": 1.67,
    "girder_spacing": 2.69,
    "deck_thickness": 0.225,
    "wearing_surface": 0.075
  },
  "reinforcement": {
    "girder": {"main_bars": "10-Φ36", "stirrups": "Φ16@100"},
    "deck": {"top_transverse": "Φ16@150", "bottom_transverse": "Φ16@150"}
  },
  "quantities": {
    "concrete_m3": {"deck_slab": 54.6, "girders": 48.5, "piers": 47.4},
    "rebar_kg": {"Φ36": 7737, "Φ16": 25274, "Φ12": 7368},
    "total_concrete_m3": 225.9,
    "total_rebar_kg": 42202
  },
  "analysis": {
    "Mu_per_girder_kNm": 23084,
    "max_deflection_mm": 8.3,
    "deflection_ok": true
  }
}
```

## 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--generate-synthetic` | — | 生成合成点云 |
| `--realistic` | — | 真实感UAV仿真 |
| `--span N` | 30 | 桥跨(m) |
| `--width N` | 8 | 桥面宽度(m) |
| `--pier-height N` | 5 | 桥墩高度(m) |
| `--bridge-type TYPE` | auto | beam / arch / auto |
| `--design-code CODE` | AASHTO | AASHTO / CHN |
| `--live-load MODEL` | HL93 | HL93 / CL1 |
| `--voxel-size N` | 0.1 | 降采样分辨率(m) |
| `--ransac-threshold N` | 0.15 | RANSAC距离阈值(m) |
| `--dbscan-eps N` | 0.5 | 聚类半径(m) |
| `--no-class-filter` | — | 禁用植被分类过滤 |
| `--analyze` | false | 启用结构分析 |

## 环境依赖

```bash
conda create -n bridge_skill python=3.10 -y
conda install -n bridge_skill -c conda-forge \
    open3d opencv shapely laspy rasterio \
    numpy scipy matplotlib freecad=0.21.2 -y
```

## 系统架构

```
~/bridge_skill/
├── run_bridge_skill.sh              # 主入口脚本 (v0.3)
├── generate_synthetic_data.py       # 简单合成点云
├── generate_realistic_data.py       # 真实感仿真点云
├── bridge_pipeline.py               # 点云处理 & 结构提取 (增强)
├── bridge_designer.py               # 工程结构设计引擎 (NEW)
├── freecad_bridge.py                # FreeCAD 精细建模 (增强)
├── bridge_drawing.py                # 专业施工图生成 (NEW)
└── README.md                        # 本文档
```

## v0.3 更新日志

### 新增模块
- **bridge_designer.py**: AASHTO LRFD/JTG D60结构设计引擎
  - 梁截面选型 (T-beam/I-beam/Box Girder)
  - 完整荷载计算 (恒载+活载+冲击系数)
  - 配筋设计 (受弯+受剪+分布筋)
  - 材料清单 (混凝土+钢筋+模板+支座)
  - 拱桥设计 (抛物线拱肋+立柱)
- **bridge_drawing.py**: 专业施工图生成器
  - 4张工程图纸 (GA/主梁/下部/BOM)
  - 标准图框+标题栏
  - 尺寸标注+材料填充+钢筋表

### 增强模块
- **bridge_pipeline.py**:
  - 地形剖面提取 (40点沿桥轴)
  - LAS分类标签植被预过滤
  - 抛物线拱桥形状检测
  - 多跨连续梁跨段计算
- **freecad_bridge.py**:
  - I型梁工字截面 (翼缘+腹板)
  - 桥墩盖梁+支座垫石
  - 桥梁栏杆 (立柱+扶手)
  - 拱桥抛物线拱肋+拱上立柱
  - 详细设计JSON格式支持
  - 材料颜色 (混凝土灰/钢筋红/沥青黑)

## License

MIT
