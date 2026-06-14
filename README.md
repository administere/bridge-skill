# Bridge Skill — UAV Survey → Bridge Construction Drawing

自动化管道：从无人机勘测点云到桥梁施工图。

## 概述

```
无人机影像 → 点云(.las) → 结构提取 → bridge_params.json → FreeCAD参数化建模 → 施工图(.svg/.step/.stl)
```

## 快速开始

```bash
# 1. 激活环境
conda activate bridge_skill

# 2. 一键生成演示（合成数据 → 参数提取 → 3D模型 → 图纸）
./run_bridge_skill.sh --generate-synthetic

# 3. 查看输出
ls bridge_output/
# bridge.las           点云（合成）
# bridge_params.json   提取的结构参数
# bridge.FCStd         FreeCAD 3D模型
# bridge.step          STEP交换格式
# bridge.stl           3D网格
# bridge_drawing.svg   三视图图纸
```

## 处理真实无人机数据

```bash
# 如果有无人机影像，先用 ODM 生成点云：
# docker run -v /data:/datasets opendronemap/odm --project-path /datasets project

# 然后运行管道：
./run_bridge_skill.sh /path/to/uav_survey.las ./my_bridge_output

# 指定桥型
./run_bridge_skill.sh survey.las ./output --bridge-type arch
```

## 管道步骤详解

### 第1步：点云生成（可选）
`generate_synthetic_data.py` — 生成合成桥梁点云
- 简支梁桥：跨度30m、宽8m、墩高5m
- 含桥面、桥墩、桥台、地面
- 输出 LAS 1.2 格式

### 第2步：结构提取
`bridge_pipeline.py` — 从点云提取桥梁结构参数
1. 点云降采样（体素网格 0.1m）
2. 多平面RANSAC分割（地面、桥面、其他）
3. DBSCAN聚类 → 桥墩/桥台识别
4. PCA主轴线提取（桥面中线）
5. 关键尺寸计算（跨径、宽度、净空、墩间距）
6. 输出 `bridge_params.json`

### 第3步：参数化建模
`freecad_bridge.py` — FreeCAD 参数化3D建模
- 读取 `bridge_params.json`
- 创建：桥面板、桥墩、桥台、路面层
- 输出：FCStd、STEP、STL、三视图SVG

### 第4步：结构分析（可选）
`--analyze` 开关：简支梁弯矩估算

## bridge_params.json 格式

```json
{
  "bridge_type": "beam",
  "dimensions": {
    "span_length": 30.7,
    "deck_width": 8.08,
    "deck_elevation": 5.25,
    "ground_elevation": -0.84,
    "clearance_under_bridge": 6.09,
    "num_piers": 2,
    "pier_spacings": [12.01]
  },
  "centerline": {
    "start": [x, y, z],
    "end": [x, y, z],
    "axis_direction": [dx, dy]
  },
  "pier_positions": [
    {"x": -6.0, "y": 0.0, "height": 5.03}
  ],
  "abutment_positions": [
    {"x": -15.0, "y": 0.0, "height": 5.10}
  ]
}
```

## 环境依赖

```bash
# 创建环境
conda create -n bridge_skill python=3.10 -y
conda install -n bridge_skill -c conda-forge \
    open3d opencv shapely laspy rasterio \
    numpy scipy matplotlib freecad=0.21.2 -y

# 可选：ODM（处理无人机影像生成点云）
# docker pull opendronemap/odm
```

## 系统架构

```
~/bridge_skill/
├── run_bridge_skill.sh          # 主入口脚本
├── generate_synthetic_data.py   # 合成点云生成
├── bridge_pipeline.py           # 点云处理 & 结构提取
├── freecad_bridge.py            # FreeCAD 参数化建模
├── bridge_params.json           # 示例输出
├── bridge.las                   # 示例点云
└── README.md                    # 本文档
```

## 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--span` | 30 | 桥跨(m) |
| `--width` | 8 | 桥面宽度(m) |
| `--pier-height` | 5 | 桥墩高度(m) |
| `--bridge-type` | auto | beam/arch/auto |
| `--voxel-size` | 0.1 | 降采样分辨率(m) |
| `--ransac-threshold` | 0.15 | RANSAC距离阈值(m) |
| `--dbscan-eps` | 0.5 | 聚类半径(m) |
| `--analyze` | false | 启用结构分析 |

## License

MIT
