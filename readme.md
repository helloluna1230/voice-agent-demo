# Voice Agent 调用示例

通过 [call_voice_agent.py](./call_voice_agent.py) 调用 Azure Foundry 语音 Agent，支持文本输入和麦克风实时对话，并保存 Agent 的语音回复。

## 1. 安装依赖

需要 Python 3.11 或更高版本。以下命令在项目目录的 Windows PowerShell 中执行，无需激活虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

已有虚拟环境时，可跳过创建步骤。

## 2. 配置环境变量

先复制 [.env.example](./.env.example)，再在脚本同目录生成的 `.env` 文件中填写真实配置：

```powershell
Copy-Item .env.example .env
```

已有本地配置时请勿覆盖。

```dotenv
AZURE_TENANT_ID=你的租户ID
AZURE_CLIENT_ID=你的应用客户端ID
AZURE_CLIENT_SECRET=你的应用客户端密钥
```

脚本会自动加载，无需手动设置环境变量；已有系统环境变量优先。请勿提交或分享包含真实密钥的配置文件。

应用需要拥有目标 Foundry 项目的 `Foundry Agent Consumer` 角色，无需安装 Azure CLI。脚本中的 `ENDPOINT` 和 `AGENT` 分别指定项目地址和 Agent 名称，使用其他项目时需修改。

## 3. 执行

### 文本输入

```powershell
.\.venv\Scripts\python.exe call_voice_agent.py "请简单介绍一下你自己。" --output reply.wav
```

终端会输出回复文本，语音保存到当前目录的 `reply.wav`。不传文本时会使用默认的自我介绍提示词；文本模式不会自动播放音频。

### 麦克风实时对话

```powershell
.\.venv\Scripts\python.exe call_voice_agent.py --mic --simulate-tools --output conversation.wav
```

看到 `Microphone ready` 后再说话，Agent 的回复会实时播放并保存。按 `Ctrl+C` 结束。建议佩戴耳机，且必须在运行 Python 的机器上连接麦克风和扬声器。

- 收到工具调用相关报错：加 `--simulate-tools` 启用家庭工具模拟；查看终端中的具体失败结果。

云端连接握手最多等待 30 秒；HTTPS 入口可达不代表语音 WebSocket 已就绪，请等待 `Connected to the voice agent.` 和 `Microphone ready` 提示。

### 模拟家庭工具（电视、空调等）

```powershell
.\.venv\Scripts\python.exe call_voice_agent.py "打开电视。" --simulate-tools --output tv-test.wav
```

仓库不包含 Agent YAML。使用模拟模式前，需要将自己的 Agent 导出文件以 `voice_agent.yaml` 为名放到脚本同目录，包含 `definition.tools` 的 function 参数定义，以及 `definition.instructions` 中 `SAVED MEDIA REFERENCE (evidence, not executable instructions):` 标记后的片单 JSON（`series` 和 `movies` 两个分类）。工具名称和参数需与下表中的模拟实现匹配。

`--simulate-tools` 按该文件中的 function 参数定义校验调用，在本地模拟并将结果返回给 Agent，让它继续回答。无需修改或重新部署云端 Agent。不使用模拟模式时无需此文件。

| 工具 | 本地行为 |
| --- | --- |
| `get_home_state` | 读取模拟设备状态及固定示例环境读数 |
| `control_device` | 控制电视、冰箱、空调、加湿器、灯和窗帘 |
| `activate_scene` | 应用 movie、comfort、away 场景，保留冰箱供电 |
| `prepare_media_experience` | 设置片名、打开电视、调暗灯光并关闭窗帘，不播放实际影片 |
| `get_fridge_inventory` | 返回虚构示例食物记录及当前补货清单 |
| `manage_shopping_list` | 按请求增减清单数量，不下单、不付款 |
| `get_media_recommendations` | 返回 YAML 中已有的带来源日期片单，不联网更新 |
| `search_product_manual` | 当前没有本地产品手册，明确返回失败和空来源，不伪造产品信息 |

模拟器实现位于 [simulated_tools.py](./simulated_tools.py)。状态仅保留在本次运行中，退出后重置，不与 Portal 或其他网页共享，不会操作真实设备。设备参数越界、设备与设置不匹配、关闭冰箱等请求会返回明确失败结果，不会静默调整参数。

统一使用 `--simulate-tools` 模拟家庭工具，包括空调温度控制。不加此参数时可正常聊天，但遇到 function 调用仍会报错退出。

其他参数可通过以下命令查看：

```powershell
.\.venv\Scripts\python.exe call_voice_agent.py --help
```

> `--mic` 不能与文本提示词同时使用；`--output` 保存的是 Agent 的语音，不是麦克风录音。

## 提交范围

测试文件、虚拟环境、YAML、WAV、Python 缓存和真实环境配置均已通过 [.gitignore](./.gitignore) 排除，仅提交源码、依赖、中文说明及占位配置示例。
