# 图像后处理 v2：建筑轮廓规整与离线 PNG 测试

本版接续已经恢复并校验的 v1 后端，默认使用不依赖训练色表的 `auto` 模式。适用于背景相对统一、建筑为平涂色块的规划图。此次主验收输入是最新 `v2测试用图(1).zip` 的 4 张原始 PNG，均为 617 × 617，已逐字节核对。

## 直接复制和测试

把压缩包中 `backend` 文件夹内的内容复制到本地项目的 `backend` 目录，覆盖同名文件。例如 `E:\github_workspace\sdxl\backend`。避免套成 `backend\backend`。保留本地环境配置、模型路径及已有数据；前端不需要修改。

在 backend 目录运行：

```powershell
python -m pip install -r requirements-postprocess.txt
python scripts/postprocess_image.py --input test_images_v2 --output outputs\postprocess_v2
```

Python 需为 3.10 或更高。离线命令仅需 NumPy、OpenCV、Pillow，不启动网站、不加载 SDXL、不需要 GPU。已有完整后端环境的用户无需重新安装大型模型依赖。

测试你自己的 PNG：

```powershell
python scripts/postprocess_image.py --input "E:\test_images\plan.png" --output outputs\single_test
python scripts/postprocess_image.py --input "E:\test_images" --output outputs\batch_test --recursive
```

重复处理同一输出目录时添加 `--overwrite`。仅允许覆盖程序自己生成的结果目录；源图片不会改写。目录批处理也支持 JPG 等格式，但评估效果优先使用生成器直接保存的 PNG。

## 先查看本次实际结果

双击 `validation_v2/index.html`，可离线切换 4 张图，比较原图、真实 v1 输出、v2 输出，放大检查，并叠加几何修改或颜色复核标记。无需启动服务器。也可以直接打开每个图片目录中的：

- `comparison_v1_v2.png`：原图 / v1 / v2 全图并排对照。
- `detail_comparison.png`：建筑区域裁剪放大对照，最近邻放大，保留真实像素边界。
- `cleaned.png`：处理后的原分辨率图片。
- `geometry_changes.png`：原图上标记新增和移除的轮廓像素。

文件名例如 `107cd38c10f54562999c46668974c472.png` 的结果目录保留了输入扩展名，用于区分同名 PNG/JPG；它本身是目录。

## v2 改了什么

1. **按轮廓结构提出修复候选。** 分别处理矩形、带转折的直线多边形、任意角度直墙及有连续弯曲证据的轮廓。建筑方向来自自身长边，不统一对齐到画面水平线。
2. **直接在原始轮廓坐标中拟合矩形墙线。** 旋转栅格只提供初始方向，最终使用原图像素中心判定覆盖，减少斜墙因两次栅格旋转产生的偏移。
3. **修补缺口与毛刺。** 以估计墙体宽度决定允许调整的尺度，同时检查总面积改变量、最大支持像素位移、连通性、邻近建筑、庭院和深入口。超出约束的候选会被撤回并记录。
4. **清理孤立碎片。** 结合相对面积、长宽形态和规则度识别残渣；达到最低像素支撑的规则小建筑、细长条带有单独保护。极小的 1–4 像素孤立区域默认视为噪点（高分辨率会按尺度上调）；可通过 `remove_fragments=false` 保留，或提供权威掩膜。已删除碎片不再阻挡邻近墙线补齐。
5. **颜色与几何分开处理。** 自适应发现图中颜色模式，消减低幅度软噪声；对有独立稳定内部支撑的多色分区保留区分。共享的直线分界只拟合一次，统一更新两侧，避免拼缝。
6. **改善补色取样。** 从离原轮廓边缘有足够距离的像素取色，减少浅色抗锯齿边缘污染；符合前景与背景混合模型的边缘颜色可独立清理。
7. **保护截断轮廓。** 接触图片边缘的建筑只做保守局部处理，标记几何复核，不猜测画面外的完整形状。

默认模式不读取训练图生成脚本，不固定绿色、不固定颜色档数、不把一个连通区域强行涂成单色。`region_ids` 是空间色块编号，既不是建筑实例编号，也不是有序高度档位。

## 每次离线运行的输出

| 文件 | 含义 |
| --- | --- |
| `source.png` 等 | 输入文件的原始字节副本 |
| `original.png` | 解码、方向校正、透明背景合成后的输入 |
| `cleaned.png` | 原分辨率 RGB 结果 |
| `comparison.png` | 原图与结果对照 |
| `foreground_mask.png` | 修复后的前景掩膜 |
| `regions.png` | 分区编号的固定伪彩示意；颜色不代表高度 |
| `geometry_added_mask.png` / `geometry_removed_mask.png` | 几何新增 / 移除像素 |
| `geometry_review_mask.png` | 几何候选未通过保护约束、或轮廓截断的复核区域 |
| `review_mask.png` | 颜色证据不足、仍需复核的像素 |
| `change_mask.png` | 所有 RGB 改动，包含背景归一化 |
| `fields.npz` | 前景、色块编号、颜色复核掩膜、可选高度数组 |
| `report.json` | 参数、校验值、逐轮廓事件、拟合方式、修改比例及复核提示 |

轻微偏白的背景统一后，`change_mask.png` 可能大面积变白。请用两个 `geometry_*_mask.png` 判断建筑边界的改动，不要用全部 RGB 改动数衡量轮廓效果。

`fields.npz` 用 `numpy.load(..., allow_pickle=False)` 读取。背景高度为 0，未配置高度的前景为 NaN。只有用户给出明确的颜色与代表高度配置且匹配通过时才填入高度。默认模式不根据明暗猜测米数。

`report.json` 中的距离均为像素；`max_added_support_distance_px` / `max_removed_support_distance_px` 是新增/移除像素到另一掩膜的最大距离，不是地理坐标距离或完整多边形 Hausdorff 指标。几何复核标记与颜色复核标记互相独立，也不是经过校准的概率。

## 参数与回退方式

配置文件：`postprocess_configs/auto.json`。

| 参数 | 默认 | 作用 |
| --- | --- | --- |
| `mode` | `auto` | 自动适应当前图像配色；`palette` 才使用显式色表 |
| `geometry_mode` | `regularize` | v2 规整；`local` 保留 v1 局部几何算法；`off` 关闭几何处理 |
| `background_rgb` | null | 从边缘估计背景，必要时手动指定 |
| `background_delta` | 10 | 前景与背景的 CIE Lab 色差阈值 |
| `color_delta` | 5 | 相近颜色容差，降低后保留更多颜色差异 |
| `boundary_tolerance_ratio` | 0.24 | 相对估计墙宽的基础位移尺度；矩形候选允许 2 倍，移除毛刺另有 1.6 倍系数，均受面积与拓扑约束 |
| `regularization_max_change_ratio` | 0.20 | 单个轮廓允许修改的支持像素比例上限，超出撤回候选 |
| `remove_fragments` | true | 是否清理孤立碎片 |
| `fragment_area_ratio` | 0.025 | 相对典型前景面积的碎片候选阈值，另结合宽度与规则度保护 |
| `regularize_color_boundaries` | true | 规整有明确证据的共享直线色界 |
| `defect_radius` | 1 | 0 关闭所有几何处理；正值在规整模式中还乘入基础位移尺度 |
| `max_hole_area` | 4 | 局部模式按短边/1024 缩放；规整模式同时参考墙宽，规则小孔有保护；0 禁止填闭合孔 |
| `max_geometry_change_ratio` | 0.025 | 仅用于保守局部算法，不是 v2 规整模式的 20% 上限 |
| `repair_geometry` / `clean_colors` | true | 分别控制几何修复 / 颜色写回 |

上面的像素尺度没有对应米/像素标定。裁剪、重采样或很浅的建筑颜色可能需要调整参数。规整仍过强时，可先降低 `boundary_tolerance_ratio` 与 `regularization_max_change_ratio`，并检查保护标记。

只整理颜色：

```powershell
python scripts/postprocess_image.py --input test_images_v2 --output outputs\color_only --geometry-mode off
```

使用原来的局部几何处理作消融对照：

```powershell
python scripts/postprocess_image.py --input test_images_v2 --output outputs\local_geometry --geometry-mode local
```

该命令仍使用 v2 颜色逻辑，不等同于完整 v1。包中三列对照的 v1 列是恢复 v1 代码后实际重跑的结果。

手动指定背景或权威前景掩膜：

```powershell
python scripts/postprocess_image.py --input "E:\test_images\plan.png" --output outputs\white_bg --background "#FFFFFF"
python scripts/postprocess_image.py --input "E:\test_images\plan.png" --output outputs\masked --mask "E:\test_images\mask.png"
```

权威掩膜必须与方向校正后的输入尺寸相同；灰度大于 127 为前景。提供掩膜后不修改其几何，只整理内部颜色。

## 后端接入与高度

沿用 v1 已有接入：生图 → `app/postprocess_service.py` → 保存原图与诊断包 → 发布 cleaned PNG → 三维预览与代理分析。此次 v2 修改集中在独立后处理模块、离线工具与测试，原有 API 和数据库结构沿用。

- 原图位于 `images/<id>_postprocess/source.png`；`images/<id>.png` 为发布结果。
- 响应保留 `original_image_url`、`postprocess_report_url`、`postprocess_comparison_url`。
- 三维与分析共用 `postprocessing/scene.py` 的掩膜和高度策略；旧 sidecar 与图片不一致时拒绝静默混用。
- 未配置高度时使用统一的 12 个示意单位供预览与代理分析，并附说明。不是测量高度。三维预览仍采用降采样网格；精确轮廓应查看原分辨率 PNG/NPZ。
- `CITY_POSTPROCESS_CONFIG` 可指定网站生成时的后处理配置，相对路径以 backend 为基准。修改配置影响后续生成；不自动改写历史图片。
- 将 `repair_geometry`、`clean_colors` 同时设为 false 可停止几何与颜色清理，保留诊断输出。

可选色表与代表高度的格式见 `postprocess_configs/palette.example.json`。住宅参考色表仍可选用，但与默认 auto 流程无关；未来商业区模型无需沿用住宅色档。

## 适用边界与复现

单张 RGB 图片无法证明一个清晰色界是否对应真实高度，也不能证明一段平滑弯墙一定是设计意图。连续曲线、有结构支撑的色界和深入口倾向保留；颜色/几何证据不足的区域输出复核标记。规则也无法可靠判断照片、文字、道路、绿地等是否属于建筑，这类输入需要额外语义掩膜。

最新复杂多色 PNG 的部分颜色与内孔边缘仍需复核，旧汇报截图还存在压缩杂色。本版没有把这些情况宣称为完全修复。四张用户图参与了开发与验收，没有人工真值，不能作为泛化准确率测试集。

详细结果和研究依据分别见 `VALIDATION_POSTPROCESS.md`、`RESEARCH_NOTES_V2.md`。

重新生成最新四张图的完整对比与 15 组合成几何指标：

```powershell
python scripts/validate_postprocess_v2.py --input test_images_v2 --output outputs\validation_rerun --baseline validation_v2\baseline_v1
```

`baseline_v1` 仅作为经过哈希验证的 v1 参考输出，不会被修改。脚本输出完整比较图和 JSON/CSV 指标；随包的 HTML 查看页展示本次交付时的固定结果。

运行全部自动测试：

```powershell
python -m unittest discover -s tests -v
```

离线测试只需三项 CV 依赖。集成测试另需 Plotly、FastAPI、httpx，缺失时相应测试会跳过。此处交付记录的 35 项测试均实际运行，无跳过；网站联动使用模拟生图，未加载真实 SDXL，也未在你的 Windows 电脑上执行。
