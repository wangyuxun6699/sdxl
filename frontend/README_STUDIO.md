# Urban Diffusion · 全栈工作台更新

本次以前端 `frontend_city_spatial_v11.zip` 和后端 `backend_cv_postprocess_v2.zip` 为基础。前端升级为 v12 工作台，后端服务升级为 v3；后处理算法仍为已经验证的 **2.0.0**，没有重写颜色与轮廓修复规则。

## 复制到你的项目

1. 停止正在运行的 Vite / 后端进程。
2. 将前端 ZIP 中的 `frontend` 内容复制到 `E:\github_workspace\sdxl\frontend`，覆盖同名代码文件。
3. 将后端 ZIP 中的 `backend` 内容复制到 `E:\github_workspace\sdxl\backend`，覆盖同名代码文件。
4. 保留本地 `.env`、模型、`database.db`、`images`、`outputs` 和 `analysis` 数据。ZIP 不携带这些运行数据，也不需要删除它们。
5. 不要再套一层 `frontend\frontend` 或 `backend\backend`。

这次没有增加前端第三方依赖。原有依赖可继续使用；新电脑或依赖不完整时在 `frontend` 运行 `npm ci`。前端运行环境请使用满足 Vite 8 要求的 Node.js（20.19+ 或 22.12+；本次验证用 Node 24）。

## 最快启动：不需要接入 SDXL

在项目根目录（同时能看到 `frontend` 和 `backend` 的地方）打开第一个 PowerShell，使用你的 Python 环境：

```powershell
python -m pip install -r backend/requirements-web.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Python 需为 3.10+。已有完整后端环境时，只补缺失依赖即可；`requirements-web.txt` 不安装 Torch、Diffusers 或模型权重。

第二个 PowerShell：

```powershell
cd frontend
npm run dev
```

打开 Vite 输出的地址，进入工作台后点击左侧“修复”，选择 PNG 即可测试。

- 上传只接受 **静态 PNG**，最大 **12 MB / 4,194,304 像素**，短边至少 16 像素。
- 默认“标准修复”使用既有 v2 自动模式，不要求住宅区色板。
- 默认勾选“三维示意”。没有真实高度映射时采用统一示意高度，颜色区域不等于建筑实例或真实楼高。
- 完成后会自动归档到“方案库”，可查看原图/结果、拖动对比、复核掩膜、分色区域、报告及下载。
- 上传前图像由浏览器本地预览，点击“开始后处理”才发送后端。

如果想测试“规划助手→生成→后处理”完整流程，但还没配置模型，可在**启动后端的那个 PowerShell**临时设置：

```powershell
$env:CITY_PLANNER_TEST_MODE="1"
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

界面会明确标为“演示模式”。这里只把生图替换为规则示意块体，后处理、三维导出和代理分析仍真实执行。测试结束后在该终端运行 `Remove-Item Env:CITY_PLANNER_TEST_MODE` 并重启后端，恢复正常模式。

**当前没有部署或连接云端 SDXL。** 本地模型路径未配置时，“生成”按钮会停用；图片后处理仍可独立使用。保留原有本地 SDXL 路由和配置，日后可继续接入云端推理服务。

## 新的工作流

- **规划**：研究范围、规划目标、真实服务状态、二维/三维方案、形态代理分析。建议提示词可填入输入框，不会自动发送。
- **修复**：PNG 上传、标准/保守/仅颜色三种策略、任务阶段、原图保留、处理前后对比与修复检查。
- **方案**：按名称或备注搜索、按来源筛选、时间/名称排序、编辑资料、下载及确认删除。
- 草稿、当前分区和任务编号保存在此浏览器中。刷新可继续查询任务；这不是多用户账户系统。新建草稿会提示清空尚未提交的范围和目标。
- 方案持久化在后端 SQLite；刷新或切换分区不会丢失保存的方案。

## 地图与坐标

已修正 Cesium 静态资源目录映射，保留按需加载。默认使用 OpenStreetMap，无需 Cesium ion token。可在 `frontend/.env.local` 设置 `VITE_MAP_TILE_URL`（XYZ 模板）及 `VITE_MAP_ATTRIBUTION` 使用自己的底图，修改后重启 Vite。

当底图服务不可达或图形环境不可用，会显示原因与重试入口。此时仍可在“研究范围”输入西/东经度、南/北纬度，应用矩形范围。

坐标为 WGS 84。当前边界仅随生成任务保存，**还没有用作 ControlNet 条件，也不约束模型生成的建筑位置**。输入坐标范围不支持跨日期变更线，地图矩形纬度限制为 ±85°。

## 后端接口与任务

新增接口：

| 接口 | 功能 |
| --- | --- |
| `GET /health` | 服务、模型配置、上传限制与分析能力 |
| `POST /jobs/postprocess` | multipart 上传：file、title、preset、make_3d；立即返回 202 和任务编号 |
| `POST /jobs/generate` | 规划任务：message、可选 selection_range；返回 202 和任务编号 |
| `GET /jobs/{id}` | queued / running / succeeded / failed 及阶段、错误、结果 |
| `GET /results/{id}/quality` | 真实后处理质量报告 |
| `GET /results/{id}/download/{kind}` | cleaned / original / report / model 文件下载 |

原有 `/chat`、`/results`、分析及编辑/删除接口保留。耗时同步路由改由框架线程池执行，避免直接阻塞事件循环。

轻量任务队列为**单服务进程、单执行线程，最多四个待完成任务**。请用默认单 worker 启动。队列满时返回 429。状态存在 SQLite，服务重启会把未完成任务标记为中断，供用户重新提交，不会伪装成已完成或自动重复生成。多 GPU / 多进程部署前应换成共享任务队列。

可用环境变量 `CITY_PLANNER_DATA_DIR` 设置数据目录；不设置时继续沿用原 `backend` 内的数据路径。项目根 `.env` 继续有效；提供的是 `.env.example`，不会覆盖你的真实配置。

生成子进程设 30 分钟超时。图像后处理本身在 CPU 队列中执行。三维转换失败会保留成功的二维结果，并返回明确提示。

## 构建与验证

```powershell
# 项目根目录
# 需要 httpx 才能执行 API 集成测试
python -m pip install httpx
python -m unittest discover -s backend/tests -v

cd frontend
npm run test:intro
npm run build
```

详细实测结果见 `VALIDATION_STUDIO.md`。已有 CLI 用法与后处理规则仍见后端 `README_POSTPROCESS.md`。

## 生产部署说明

前端构建产物为 `frontend/dist`。生产服务器需要把 `/api/` 代理到后端并去掉 `/api` 前缀，同时允许上传大小至少 12 MB（代理层可设 16 MB）。不要把 `vite preview` 当作生产 API 代理。示例见 `frontend/deploy/nginx.conf.example`。

本次交付不包含公网部署、账号认证或云模型配置；无需为本地上传测试先部署云端。
