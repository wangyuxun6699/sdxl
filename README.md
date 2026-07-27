# SDXL 城市规划生成助手

这是一个 Vue 3 + FastAPI 的本地城市规划生成系统。用户输入自然语言后，后端先通过 DashScope 判断是普通对话还是生成任务；生成任务会调用本地 SDXL 基础模型和分区 LoRA，输出 2D 色块规划图，再生成可交互 3D HTML，并完成轻量日照与通风代理分析。

> 日照/通风结果用于早期方案对比，不是物理级日照仿真或 CFD 结论。

## 功能与调用链

```text
浏览器
  └─ POST /chat
       ├─ DashScope + LangChain：意图识别、整理 SDXL 提示词
       ├─ 普通对话：直接返回中文 reply
       └─ 生成任务
            ├─ 选择分区 LoRA，调用本地 SDXL 生成 PNG
            ├─ OpenCV 提取色块和相对高度
            ├─ Plotly 输出可交互 3D HTML
            ├─ 计算日照/通风代理热力图
            └─ SQLite 保存任务、参数和产物路径
```

分区、LoRA 路由和色块约定如下。深色代表相对高层，浅色代表相对低层；2D→3D 和空间分析都依赖这个约定。

| 分区 | `area_type` / `model_key` | `area_flag` | 建筑色块 |
| --- | --- | ---: | --- |
| 居住区 | `residential` | 1 | 绿色 |
| 工业区 | `industrial` | 2 | 黄色 |
| 商业区 | `commercial` | 3 | 蓝色 |
| 公共区 | `public` | 4 | 红色 |

## 电脑配置要求

当前代码只会选择 NVIDIA CUDA 或 CPU：`torch.cuda.is_available()` 为真时使用 CUDA，否则退回 CPU。AMD/Intel 独显、Apple MPS 目前不会被当作推理设备。

| 场景 | GPU | 内存 | 磁盘 | 说明 |
| --- | --- | --- | --- | --- |
| 接口/前端开发、测试模式 | 不需要 | 8 GB+ | 5 GB+ | 不加载 DashScope 和 SDXL，可验证其余完整链路 |
| 本地推理最低配置 | NVIDIA 8 GB 显存 | 32 GB | 30 GB+ | 开启 CPU offload、attention slicing；显存不足时自动降到最高 768×768、24 步重试 |
| 推荐配置 | NVIDIA 12–16 GB+ 显存 | 32 GB+ | 40–60 GB NVMe | 更适合默认 1024×1024、30 步；16 GB 以上更稳妥 |
| CPU-only | 无 | 32–64 GB | 30 GB+ | 可以运行，但单张 SDXL 可能需要很长时间，不建议服务化 |

部署建议：

- 操作系统：Windows 10/11 x64 或 Linux x86_64；项目当前主要按 Windows + Python 3.12 验证。
- Python：3.10–3.12，推荐 3.12。
- Node.js：Vite 8 要求 Node.js `20.19+` 或 `22.12+`，推荐 Node.js 22 LTS。
- NVIDIA 驱动必须支持所安装的 PyTorch CUDA wheel。通常不需要单独安装完整 CUDA Toolkit，但驱动版本必须匹配。
- 磁盘要同时容纳 Python/CUDA 依赖、SDXL checkpoint、4 个 LoRA、Diffusers 配置缓存和持续增长的生成产物。
- 一块 GPU 建议只启动一个 Uvicorn worker。当前架构每个生成任务都会启动子进程并重新加载 SDXL，多 worker 或并发任务容易耗尽显存/内存。

## 模型文件要求

模型权重不会提交到 Git。正式模式至少需要：

1. 一个 SDXL 兼容的单文件基础模型（`.safetensors`）；
2. 与该基础模型兼容的分区 LoRA；只调用某个分区时，该分区 LoRA 必须存在；
3. `stabilityai/stable-diffusion-xl-base-1.0` 的 Diffusers 配置元数据。

`llmpicture.py` 使用 `local_files_only=True`，推理请求期间不会自动联网下载配置。建议部署前预下载：

```powershell
# 先安装 Python 依赖，然后按模型仓库要求登录并接受许可证
hf auth login

hf download stabilityai/stable-diffusion-xl-base-1.0 `
  --local-dir D:\models\sdxl\diffusers-config `
  --include "model_index.json" "scheduler/*" "tokenizer/*" "tokenizer_2/*" `
            "text_encoder/config.json" "text_encoder_2/config.json" `
            "unet/config.json" "vae/config.json"
```

之后把 `.env` 中的 `SDXL_DIFFUSERS_CONFIG_PATH` 指向该目录。也可以不设置此变量、改用 Hugging Face 缓存，但对应快照必须已经存在于 `HF_HUB_CACHE`。

## Windows 部署

### 1. 创建 Python 环境

```powershell
cd D:\path\to\sdxl
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
```

先根据 [PyTorch 官方安装选择器](https://pytorch.org/get-started/locally/) 安装匹配显卡驱动的版本。以下只是在 CUDA 12.8 环境下的示例；机器不匹配时不要照抄版本通道。

```powershell
# NVIDIA CUDA 12.8 示例
.\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cu128

# CPU-only 示例
# .\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu

.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

验证 PyTorch 是否识别显卡：

```powershell
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
```

### 2. 配置后端

```powershell
Copy-Item .env.example .env
notepad .env
```

关键变量：

| 变量 | 是否必需 | 用途 |
| --- | --- | --- |
| `DASHSCOPE_API_KEY` | 正式模式必需 | 意图识别和提示词整理 |
| `DASHSCOPE_MODEL` / `DASHSCOPE_BASE_URL` | 有默认值 | DashScope OpenAI 兼容接口 |
| `SDXL_BASE_MODEL_PATH` | 必需 | SDXL 单文件基础模型 |
| `SDXL_*_LORA_MODEL` | 对应分区必需 | 4 类分区 LoRA 路径 |
| `SDXL_*_LORA_STRENGTH` | 可选 | LoRA 融合强度，默认 `0.9` |
| `SDXL_DIFFUSERS_CONFIG_PATH` | 推荐 | 已下载的 SDXL Diffusers 配置目录 |
| `HF_HUB_CACHE` | 可选 | Hugging Face 本地缓存目录 |
| `CITY_PLANNER_TEST_MODE` | 可选 | `1` 时跳过 DashScope 和 SDXL |

路径可放在任意磁盘，不要依赖源码里的历史默认盘符。`.env` 已被 `.gitignore` 排除。

### 3. 启动后端

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app `
  --host 0.0.0.0 --port 8000 --workers 1
```

检查服务：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

返回 `status = ok` 即表示 API、SQLite 和运行目录初始化成功。Swagger 文档位于 `http://127.0.0.1:8000/docs`。

### 4. 启动前端

```powershell
cd frontend
Copy-Item .env.example .env
notepad .env
npm ci
npm run dev
```

访问 `http://127.0.0.1:5173`。开发服务器会把 `/api/*` 代理到 `http://127.0.0.1:8000/*`。

`VITE_CESIUM_ION_TOKEN` 只用于浏览器地图圈选。它会进入构建后的 JavaScript，不是服务端秘密；请在 Cesium 控制台创建受域名限制、最小权限的公开 Token。未配置时 SDXL 主链路仍可使用，但 Cesium 底图可能不可用或显示授权警告。

## 测试模式

测试模式不调用 DashScope，也不加载 SDXL。它会用规则识别意图、生成 mock 色块图，然后继续执行真实的 2D→3D、SQLite 和日照/通风分析，适合低配置电脑做部署验收。

终端一：

```powershell
$env:CITY_PLANNER_TEST_MODE="1"
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1
```

终端二：

```powershell
$env:API_BASE_URL="http://127.0.0.1:8000"
.\.venv\Scripts\python.exe test_backend.py
```

测试结束后关闭终端，或清除临时变量：

```powershell
Remove-Item Env:CITY_PLANNER_TEST_MODE -ErrorAction SilentlyContinue
```

## 生产部署（Nginx + Uvicorn 示例）

前端默认使用同域 `/api`，适合由 Nginx 同时提供静态文件和反向代理。构建变量只在 `npm run build` 时读取：

```bash
cd frontend
npm ci
VITE_API_BASE_URL=/api VITE_CESIUM_ION_TOKEN=your_public_token npm run build
```

后端建议交给 systemd、Supervisor 或 Windows 服务管理器常驻。Linux systemd 示例：

```ini
[Unit]
Description=SDXL City Planner API
After=network.target

[Service]
Type=simple
User=sdxl
WorkingDirectory=/opt/sdxl-city-planner
EnvironmentFile=/opt/sdxl-city-planner/.env
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/sdxl-city-planner/.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=on-failure
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
```

Nginx 示例（把 `root` 改为实际的 `frontend/dist` 目录）：

```nginx
server {
    listen 80;
    server_name planner.example.com;
    root /opt/sdxl-city-planner/frontend/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_http_version 1.1;
        proxy_read_timeout 900s;
        proxy_send_timeout 900s;
    }
}
```

SDXL 首次加载和 CPU offload 可能较慢，所以代理超时要明显高于普通 Web API。公网部署前还应增加 HTTPS、身份认证、限流/任务队列，并把后端 CORS 从当前开发用的全开放策略收紧。

## 调用接口

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

生成商业区规划图：

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"生成一个商业区总平面规划图，蓝色建筑块，白色背景","selection_range":null}'
```

PowerShell 调用：

```powershell
$body = @{
  message = "生成一个商业区总平面规划图，蓝色建筑块，白色背景"
  selection_range = $null
} | ConvertTo-Json -Depth 8

Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/chat `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

生成响应包含 `request_id`、`result`、`image_url`、`html_url` 和 `analysis`。常用接口：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查 |
| `POST` | `/chat` | 对话或触发完整生成链路 |
| `GET` | `/results` | 结果列表 |
| `GET` | `/results/{id}` | 单条结果 |
| `GET` | `/results/{id}/analysis` | 读取已有分析；没有时自动计算 |
| `POST` | `/results/{id}/analysis` | 按新日照/风向参数强制重算 |
| `PATCH` | `/results/{id}` | 更新标题和备注 |
| `DELETE` | `/results/{id}` | 删除记录和对应磁盘产物 |

强制重算分析的请求体示例：

```json
{
  "season_profile": "spring",
  "sun_altitude_deg": 44,
  "primary_wind_direction": "west",
  "wind_directions": ["north", "east", "south", "west"]
}
```

## 目录结构与运行产物

```text
backend/
  main.py                    # FastAPI 应用装配、静态目录挂载
  app/
    routes.py                # chat/results/analysis API
    llm_router.py            # DashScope 意图路由和 fallback
    generation_service.py    # SDXL 与 2D→3D 子进程编排
    analysis_service.py      # 分析缓存、参数规范化
    repository.py            # SQLite 读写
  scripts/
    llmpicture.py            # 本地 SDXL + LoRA 推理
    2D23D.py                 # 规划色块转 Plotly 3D HTML
    spatial_analysis.py      # 日照/通风代理分析
frontend/                    # Vue 3 + Cesium 前端
test_backend.py              # 后端端到端测试
```

运行后会生成：

- `backend/images/{request_id}.png`
- `backend/outputs/{request_id}.html`
- `backend/analysis/{request_id}/analysis.json`
- `backend/analysis/{request_id}/sunlight_heatmap.png`
- `backend/analysis/{request_id}/ventilation_heatmap.png`
- `backend/database.db`

这些文件、模型权重、日志、虚拟环境和真实 `.env` 都已排除在 Git 之外。

## 常见问题

### `torch.cuda.is_available()` 为 `False`

确认是 NVIDIA 显卡，运行 `nvidia-smi` 检查驱动，再检查 PyTorch wheel 的 CUDA 通道是否与驱动兼容。安装到错误虚拟环境也会造成这种现象。

### 提示找不到 SDXL 配置

`from_single_file` 除 checkpoint 外仍需要 tokenizer、scheduler、UNet/VAE 等配置 JSON。按“模型文件要求”预下载，并设置 `SDXL_DIFFUSERS_CONFIG_PATH`。程序不会在生成请求里在线补下载。

### CUDA OOM 或生成很慢

- 保持 `--workers 1`，不要并发跑多个 SDXL 子进程；
- 关闭占用显存的其他程序；
- 把请求尺寸调到 768×768 或 512×512、降低推理步数；
- 8 GB 显存会频繁依赖 CPU offload，系统内存和磁盘速度也会影响耗时。

### 2D→3D 没有识别到建筑

转换脚本只提取当前分区的红/黄/绿/蓝色块，并过滤边框、细线和小噪点。确保提示词保持纯白背景、实心色块，避免道路、文字、阴影、渐变和非目标颜色。

### 分析指标看起来不真实

当前实现根据色块亮度推断相对高度，用简化投影估算阴影，用二维传播和尾流衰减估算通风。指标是 0–1 归一化代理量，不是小时日照值或 m/s 风速。

### 前端能打开但请求失败

开发模式确认 Vite 的 `/api` 代理目标是 `127.0.0.1:8000`；生产模式确认 Nginx 的 `/api/` 尾斜杠和 `proxy_pass` 配置正确。前后端分离时，在构建前把 `VITE_API_BASE_URL` 设为后端完整地址。

## 安全说明

- 不要提交 `.env`、模型权重、数据库和日志；
- DashScope Key 只放后端 `.env`，不要使用 `VITE_` 前缀；
- Cesium Token 会公开到浏览器端，必须限制允许域名和权限；
- 如果任何 Token 曾硬编码或推送到公开仓库，应立即在对应控制台轮换；
- 请遵守 SDXL 基础模型和各 LoRA 的许可证及内容使用要求。
