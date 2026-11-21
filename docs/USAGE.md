# 灵犀节点使用手册

快速安装和功能预览见[项目首页](../README.md)。

## 节点速查

| 功能组 | 节点显示名 | 说明 |
| --- | --- | --- |
| 文件夹批量 | `图像计数（文件夹）` / `加载图像（文件夹）` / `保存图像（文件夹）` | 文件夹图像计数、逐张加载和保存，支持重置计数器。 |
| 文件夹批量 | `加载提示词（TXT系列）` / `保存图像（TXT系列）` | 按 TXT 系列加载提示词并保存对应图片。 |
| 中转站 | `灵犀API配置` / `灵犀生图` / `灵犀局部编辑` | 配置中转 API、生成图片和局部编辑。 |
| 中转站 | `灵犀API池` / `API池合并` / `灵犀批量生图（旧版）` | 多 Key 接口池及并发生图。 |
| 中转站 | `灵犀生图任务` / `灵犀批量执行` / `灵犀结果拆分` | 收集任务、批量执行并拆分结果。 |
| 中转站 | `灵犀单图批量（文件夹）` / `灵犀多图批量（文件夹）` / `灵犀批量执行（文件夹）` | 按文件夹生成任务并执行保存。 |
| 中转站 | `灵犀缓存管理` / `API配置说明` / `AIHUBMIX Seedream 图生图编辑` | 管理本地缓存、查看配置说明和调用 Seedream 编辑。 |
| 全局广播 | `全局输入` | 把一个已连接的值广播到同类型的未连接输入。 |
| 全局广播 | `屏蔽广播` | 占位输出节点，用来阻断某一路全局广播。 |
| 控制组节点 | 组控前端虚拟节点 | 用于控制 group 开启、忽略、禁用状态，支持连线或广播传递组状态。 |
| 图像处理 | `自动抠图` | 使用 BiRefNet、RMBG、InSPyReNet、BEN2 等模型做自动抠图。 |
| 图像处理 | `语义抠图` | 基于 SAM3.1 做文本目标语义分割和抠图。 |
| 图像处理 | `图像缩放（按边）` | 按长边、短边、宽度或高度缩放 IMAGE，并返回实际尺寸。 |
| 图像处理 | `图像批量缩放（按边）` | 按“数量”动态增删 IMAGE 输入/输出端口。 |
| 图像处理 | `图像高质压缩` | 在内存中按 JPEG 质量压缩 IMAGE，适合减小体积后继续接后续节点。 |
| 图像处理 | `保存图像（JPG）` | 将 IMAGE 保存为 JPG，可指定文件名前缀和保存路径。 |
| 图像处理 | `图像对比` | 对比两组 IMAGE，支持滑动分界线、按住切换和多图批次标签。 |
| 图像编辑 | `Qwen Image Edit` | 图像编辑条件节点，支持灵犀/LX 搜索入口。 |
| 图像编辑 | `Qwen 2.1 多图编辑画布` | 最多连接 10 张参考图。出图尺寸可跟随已连接的任意参考图，也可自定义比例或宽高。 |
| 图像编辑 | `Boogu Image Edit` | 图像编辑条件节点，支持灵犀/LX 搜索入口。 |
| 图像编辑 | `Flux2 Kontext Image Edit` | Flux2 Kontext 图像编辑条件节点。 |
| 图像编辑 | `Flux2 Klein Image Edit` | Flux2 Klein 图像编辑条件节点。 |
| 文本工具 | `文本` | 多行文本源，输出 STRING。 |
| 文本工具 | `文本连锁` | 将最多 4 路文本按自定义连接符拼接。 |
| 文本工具 | `文本替换` | 对输入文本执行最多 4 组顺序文本替换。 |
| 文本工具 | `提示词列表` | 将多个提示词文本框收集为 LIST 和字符串列表输出，最多 32 条。 |
| 文本工具 | `提示词分段` | 将多行提示词拆成动态输出端口，可批量添加前缀和后缀。 |
| 文本工具 | `离线翻译` | 本地 CTranslate2 翻译节点，高级依赖放在 `requirements-full.txt`。 |
| 语音工具 | `语音识别输入` | 本地 SenseVoice 语音输入节点，前端录音后由后端识别并回填文本框。 |
| 语音工具 | `语音识别输入Plus` | 基于 FunASR streaming 的 Plus 语音输入节点，高级依赖放在 `requirements-full.txt`。 |
| 实用工具 | `展示任意` | 显示任意输入并原样透传；对 IMAGE/MASK 张量生成预览。 |
| 实用工具 | `展示文本` | 显示文本并原样输出。 |
| 实用工具 | `灵犀环境诊断` | 手动检查当前 Python、依赖和模型文件状态，并输出中文诊断报告。 |
| 实用工具 | `切换任意` | 多路任意类型输入选择开关。 |
| 实用工具 | `切换选择` | 多路固定选项输入选择开关。 |
| 实用工具 | `布尔选择` | 按布尔值选择输入。 |
| 实用工具 | `设置点` / `获取点` | 前端虚拟连线节点，用于隐藏长连线，并可随时还原为真实连线。 |
| 实用工具 | `Qwen3VL 图像反推` | 调用阿里云百炼 Qwen3-VL，对 1 到 4 张图做描述或提示词反推，并带本地缓存。 |
| 实用工具 | `Qwen3 文本生成` | 调用阿里云百炼 Qwen 文本模型，对输入文本做生成、改写、润色、翻译或提示词整理。 |
| 实用工具 | `显存/内存释放` | 按执行次数周期释放显存缓存、系统内存，并可选择卸载已加载模型。 |
| 模型工具 | `LoRA加载器（多重）` | 在同一节点配置多组 LoRA。 |
| 前端工具 | `元节点` / `备注` / `标题` / `智能工作流排版` | 控件同步、画布备注、透明文字和工作流自动排版。 |
| 前端工具 | `工作流管理` | 右键新建文件夹，拖拽或多选移动工作流。 |

搜索「标题」可添加透明文字，用于工作流标题、分区名或短提示。双击打开编辑面板，也能在右键菜单快速切换颜色和字号。对齐适用于多行文字和拉宽后的标题框，箭头和三角都可以调整为上、下、左、右。文字、样式与位置都随工作流保存。

### 智能工作流排版

在画布空白处右键打开「智能工作流排版」，或从 ComfyUI 主菜单的扩展与「灵犀工具」进入。

- **一键整理工作流** 选中节点时只整理选中节点，单独选中一个分组时整理该组。没有选区时沿连线整理当前画布，手工分组整体移动，固定的节点和分组留在原位。进入子图时只整理当前一层。
- **整理并添加说明** 同时在模型、素材、提示词、采样和输出等关键节点附近添加可编辑备注。备注会随工作流保存，重复整理同一节点时复用已有说明。
- **整理并生成分组** 根据连线把独立流程分开，识别共用准备和各条分支，再按节点用途为较长流程分段命名。只为当前范围中未分组、未固定的相连节点创建组框。需要备注时选 **整理并生成分组及说明**。
- **清除自动分组** 移除可移动的自动组框，保留节点、连线和手工分组。
- **整理当前分组** 可单独排布分组内节点。整理作为一次画布修改，可以撤销。

### 工作流管理

在左侧点提示为「灵犀工作流管理」的工作流图标，或在主菜单的「扩展 → 灵犀工具」打开工作流管理。打开后可以直接输入搜索。单击文件夹展开或收起，单击文件打开工作流。文件夹名称旁的数字包括所有子目录中的工作流。

- 右键文件夹可新建子文件夹，右键列表空白处或面板标题可在根目录新建文件夹。
- 右键文件或文件夹可选择「移动到」。按 Ctrl 或 Shift 多选时，右键菜单会标出移动数量。移动后可以在短暂提示里点击「撤销」。
- 已保存的工作流即使有未保存修改也能移动。拖动会将磁盘上已保存的版本移到目标目录，打开的标签和草稿会跟随新路径。按 Ctrl+S 将改动保存到新位置，关闭时选择不保存则保留移动前已保存的内容。
- 在同一文件夹内，拖到另一项的上沿或下沿可以排序。右键可恢复默认排序。
- 右键工作流可选择「置顶」或「取消置顶」。置顶的工作流在所在文件夹最前面，置顶和手动排序都保存在当前浏览器。
- 右键点中的文件或文件夹可以重命名或删除。删除弹窗会显示路径，默认选中「取消」。
- 跨目录移动时，可以拖到目标文件夹这一行的中间，或拖到目标文件夹里的任一工作流。拖动子目录或子文件时，列表顶部会显示「移到根目录」。
- 在资源管理器里改动文件后，可以点「重新扫描工作流文件」同步列表。面板内的文件操作会自动更新列表。

可以直接删除已打开的工作流。确认后，ComfyUI 会永久删除该文件并关闭对应标签，未保存的修改会丢失。删除文件夹会把整个目录移入当前用户目录下的 `.lx-workflow-library-trash`，其中的 `manifest.json` 记录原位置，便于手动恢复。

移动、重命名或删除文件夹前，请先保存并关闭其中已打开的工作流。含收藏项的文件夹可以单独操作其中的工作流。

面板右上角「⋯」里可以关闭或恢复「显示原生工作流入口」。隐藏后，灵犀图标会补到原生入口的位置。设置按 ComfyUI 用户保存，两个入口共用用户的工作流文件。

## 安装

### 从三个独立插件升级

关闭 ComfyUI 后，安装完整的 `ComfyUI-LX-Nodes`。旧 `ComfyUI-LX-ImageBatch` 和 `ComfyUI-LX-Relay` 应移出 `custom_nodes`，避免重复注册节点、前端扩展和 HTTP 路由。已有工作流使用的节点 key 不变。

如旧 Relay 中存在 `_plugins/lingxi_bridge/relay_config.local.json` 或旧版 `relay_config.json`，将它们复制到本项目同名相对路径；不要覆盖已有私有配置。原 LX-Nodes 的 `_plugins/_shared` 配置保留原位置。中转缓存默认位于 ComfyUI 用户目录，合并不改变缓存位置；`LX_RELAY_CACHE_DIR` 设置仍有效。

### 新安装

1. 将本项目放到 ComfyUI 的 `custom_nodes` 目录：

   ```text
   ComfyUI/custom_nodes/ComfyUI-LX-Nodes
   ```

2. 安装基础依赖：

   ```bash
   python -m pip install -r requirements.txt
   ```

   如果要使用离线翻译、自动抠图、语音识别、语音识别 Plus 等高级功能，再安装全量依赖：

   ```bash
   python -m pip install -r requirements-full.txt
   ```

   秋叶启动器或便携版用户请使用当前 ComfyUI 自带的 Python 环境执行安装，例如：

   ```bash
   path/to/ComfyUI-python/python.exe -m pip install -r requirements-full.txt
   ```

3. 重启 ComfyUI。
4. 在节点搜索里输入 `灵犀`、`LX`、`图像`、`提示词`、`离线翻译`、`语音识别`、`展示任意`、`环境诊断`、`设置点`、`获取点`、`Qwen3VL`、`Qwen3 文本生成`、`抠图`、`图像编辑` 等关键词。

### 第一次验证

拖入 [基础文本示例](../examples/text_basic.json)，运行后“展示文本”节点应显示文本节点的内容。该示例无需模型或 API Key；示例说明见 [examples/README.md](../examples/README.md)。

中转生图、Seedream 和 Qwen API 功能会将所选文本/图片发送到配置的服务地址，可能产生服务费用。API Key 留在自己的运行环境中，分享工作流前清空真实凭据。

### Qwen 2.1 画布兼容

新建多图编辑或姿势迁移流程可使用「Qwen 2.1 多图编辑画布」，将正面条件、负面条件和 Latent 接到采样器。旧工作流的「Qwen 2.1 高分辨率编辑画布」继续提供独立宽高、对齐参考图和 Latent，因而能读取原接线。浏览器里还显示旧的「Qwen 2.1 姿势迁移」原型时，重启 ComfyUI 后刷新页面即可更新可用节点。

## 目录结构

```text
ComfyUI-LX-Nodes/
├─ __init__.py                         # 顶层入口：扫描并聚合 _plugins/*
├─ requirements.txt                    # 轻量基础依赖
├─ requirements-full.txt               # 高级功能全量依赖
├─ release.json                        # 候选版本及审查状态
├─ LICENSE / NOTICE                    # 项目许可与第三方声明
├─ licenses/                           # 纳入源码的原许可文本
├─ third_party.json                    # 来源范围、许可哈希和模型对照证据
├─ CONTRIBUTING.md                     # 贡献说明
├─ examples/                           # 无密钥示例工作流
├─ tests/                              # 节点与发布工具测试
├─ tools/
│  ├─ check_project.py                 # 基础项目检查脚本
│  └─ build_release.py                 # 审查/公开版打包与校验
├─ _plugins/
│  ├─ _shared/                         # 共享配置和密钥引用工具
│  ├─ aihubmix_seedream/                # Seedream 图生图编辑
│  ├─ auto_cutout/                     # 自动抠图和语义抠图
│  ├─ categories.py                    # 统一节点分类名称
│  ├─ global_input/                    # 全局输入与屏蔽广播
│  ├─ group_control/                   # 控制组前端虚拟节点说明
│  ├─ image_compare/                   # 图像对比节点
│  ├─ image_compression/               # 图片压缩、缩放和 JPG 保存
│  ├─ image_edit/                      # 图像编辑条件节点
│  ├─ imagebatch/                      # 文件夹图像计数、加载与保存
│  ├─ lingxi_bridge/                   # 中转配置、生图、局部编辑与缓存管理
│  ├─ lingxi_concurrent_bridge/        # API 池和旧版并发生图
│  ├─ lingxi_folder_batch/             # 文件夹批量生图
│  ├─ lingxi_task_queue/               # 任务队列与结果拆分
│  ├─ lora_tools/                      # 多重 LoRA 加载器
│  ├─ prompt_batch/                    # TXT 系列加载和图像保存
│  ├─ prompt_tools/                    # 提示词分段
│  ├─ set_get/                         # 设置点/获取点虚拟连线节点
│  ├─ speech_tools/                    # 本地语音识别输入
│  ├─ text_tools/                      # 文本、拼接、替换、提示词列表
│  ├─ translation_tools/               # 离线翻译
│  └─ utility/                         # 展示、反推、内存释放、开关等实用节点
├─ web/
│  ├─ comfyui_patches/                 # ComfyUI 官方前端兼容热修补丁
│  ├─ auto_cutout.js                   # 抠图节点前端扩展
│  ├─ global_input/                    # 全局输入前端扩展
│  ├─ group_control/                   # 控制组前端虚拟节点
│  ├─ image_compression/               # 批量缩放前端扩展
│  ├─ image_edit/                      # 图像编辑节点前端扩展
│  ├─ meta_node/                       # 元节点前端虚拟节点
│  ├─ set_get/                         # 设置点/获取点前端扩展
│  ├─ speech_tools/                    # 语音输入前端扩展
│  ├─ text_tools/                      # 文本工具前端扩展
│  ├─ translation_tools/               # 离线翻译前端扩展
│  ├─ utility/                         # 实用工具前端扩展
│  └─ image_compare.js                 # 图像对比前端扩展
└─ docs/
   ├─ PLUGIN_INTAKE_GUIDE.md
   ├─ ADOPTED_PLUGINS.md
   ├─ AUTO_CUTOUT_NODE_DESIGN.md
   ├─ COMFYUI_PATCHES.md
   └─ SPEECH_RECOGNITION_INPUT_DESIGN.md
```

## 加载机制

合并的文件夹图片模块位于 `_plugins/imagebatch/`，TXT 系列模块位于 `_plugins/prompt_batch/`，中转 API 模块位于 `_plugins/lingxi_bridge/`。其余中转功能位于 `lingxi_concurrent_bridge`、`lingxi_task_queue`、`lingxi_folder_batch` 和 `aihubmix_seedream` 子目录，前端资源与模块同名。

顶层 `__init__.py` 会自动扫描 `_plugins/` 下所有非下划线开头的子目录，并以私有运行时包名 `_lx_nodes_plugins.<plugin_name>` 导入。磁盘目录仍保持 `_plugins/`，运行时包名加前缀是为了避免和其他 ComfyUI 插件的内部包冲突。

每个子插件只要在自己的 `__init__.py` 里导出下面两个变量，就会自动注册到 ComfyUI：

```python
NODE_CLASS_MAPPINGS = {
    "ExampleNode": ExampleNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ExampleNode": "示例节点",
}
```

节点类必须提供统一搜索别名，至少包含 `lx`、`LX`、`灵犀`，并继续保留功能名、旧名称或英文同义词：

```python
class ExampleNode:
    CATEGORY = "🅻🆇 灵犀/示例分类"
    SEARCH_ALIASES = ["lx", "LX", "灵犀", "示例节点", "example node"]
```

如果子插件需要前端扩展，把 JavaScript 放到 `web/<plugin_name>/` 下即可。顶层入口已经设置：

```python
WEB_DIRECTORY = os.path.join(_package_dir, "web")
```

`web/comfyui_patches/` 是专门给 ComfyUI 官方前端兼容热修使用的区域。这里的补丁不注册节点，也不承载灵犀节点业务逻辑；如果官方后续修复了对应问题，可以删除补丁目录，或把补丁 `.js` 改成非 `.js` 后缀来禁用。详细规则见 [ComfyUI 前端补丁说明](COMFYUI_PATCHES.md)。

## 本地私有配置

中转 API 目录和模型选项配置位于 `_plugins/lingxi_bridge/relay_config.local.json`，默认模板为同目录下的 `relay_config.example.json`。

共享默认配置文件位于：

```text
_plugins/_shared/relay_config.example.json
```

实际运行时的私有配置会写入：

```text
_plugins/_shared/relay_config.local.json
```

请注意：

- 不要把真实 API Key 提交到公开仓库。
- `relay_config.example.json` 只保存默认结构；本地私有配置使用 `relay_config.local.json`。
- 共享密钥工具支持密钥引用；中转 API 配置/API 池的 Key 输入仍可能随工作流保存，分享工作流前需清空真实 Key。
- 如果手动压缩发布插件，请排除 `relay_config.local.json`、`qwen3vl_cache/`、`qwen_text_cache/`、`__pycache__/` 等运行时文件。

## 语义抠图和 SAM3

`语义抠图` 使用 SAM3.1，除了 `requirements-full.txt` 里的通用高级依赖，还需要额外准备官方 `sam3` Python 包和 SAM3.1 资源。

请把官方 `sam3` 包安装到当前 ComfyUI 使用的同一个 Python 环境中。节点不会复用其他 `custom_nodes` 插件内置的 `sam3`，这样可以避免不同插件之间的包版本互相污染。

模型和词表可放在下面位置：

```text
ComfyUI/models/LX/semantic_cutout/sam3.1_multiplex.pt
ComfyUI/models/LX/semantic_cutout/assets/bpe_simple_vocab_16e6.txt.gz
```

也兼容这些位置：

```text
ComfyUI/models/SAM3/sam3.1_multiplex.pt
ComfyUI/models/SAM3/assets/bpe_simple_vocab_16e6.txt.gz
ComfyUI/models/sam3/sam3.1_multiplex.pt
ComfyUI/models/sam3/assets/bpe_simple_vocab_16e6.txt.gz
```

如果 HuggingFace 镜像可访问，节点会尝试下载 `sam3.1_multiplex.pt`；BPE 词表仍建议提前放好，或安装包含该词表的 `clip/open_clip` 包。

## 语音识别模型

`语音识别输入` 不使用浏览器 `SpeechRecognition`，也不依赖云 API。首次点击 `START` 时会检查并下载 SenseVoice ONNX INT8 必需文件：

```text
ComfyUI/models/speech/sensevoice_onnx_int8
```

`语音识别输入Plus` 使用 FunASR streaming 模型：

```text
ComfyUI/models/speech/paraformer_zh_streaming
```

下载源默认走 HuggingFace。如果网络环境需要镜像，可在启动 ComfyUI 前设置：

```bash
set HF_ENDPOINT=https://hf-mirror.com
```

## 依赖

轻量基础依赖写在 `requirements.txt`，用于保证基础节点和接口功能正常加载：

- `Pillow`
- `numpy`
- `requests`
- `aiohttp`
- `huggingface_hub`

高级功能依赖写在 `requirements-full.txt`，用于离线翻译、自动抠图、语音识别和语音识别 Plus：

- `onnxruntime`
- `transformers`
- `ctranslate2`
- `sentencepiece`
- `accelerate`
- `transparent-background`
- `safetensors`
- `einops`
- `timm`
- `opencv-python`
- `SenseVoice-python`
- `funasr`

`torch`、`folder_paths`、`server`、`comfy.utils`、`comfy.model_management` 等通常由 ComfyUI 环境提供，不建议在插件里强制安装。

节点运行时不会自动执行 `pip install`。如果缺少 Python 包，节点会提示安装 `requirements-full.txt` 或对应特殊依赖；模型权重文件可以在节点运行时按需下载。

## 开发与入库规范

### 公开发布前

来源与授权见 [来源记录](ADOPTED_PLUGINS.md) 和 [第三方源码核查](THIRD_PARTY_SOURCES.md)。维护者确认有权修改的旧声明已清理；GPL、Apache、MIT 原文、必要来源和修改说明已保留。外部模型、Python 包及运行程序不被项目 GPL 重新授权，具体条件见 [外部资源](EXTERNAL_RESOURCES.md)。

逐项待确认材料见 [开源授权审查清单](OPEN_SOURCE_REVIEW.md)。当前可运行 `python tools/build_release.py` 生成私有审查 ZIP；公开版条件及命令见 [发布说明](RELEASING.md)。

发布前运行 `python tools/check_project.py`，确认私有配置、缓存未被 Git 跟踪，并检查所有功能代码已加入版本管理。手动打包时也须排除 `.codex_tmp/`、`.vs/`、私有配置、缓存与密钥。

如果要把外部优秀节点整理进本项目，请先阅读：

- [外部节点入库规范](PLUGIN_INTAKE_GUIDE.md)
- [外部插件来源与授权记录](ADOPTED_PLUGINS.md)
- [开源授权审查清单](OPEN_SOURCE_REVIEW.md)
- [发布说明](RELEASING.md)
- [发布验证记录](RELEASE_VALIDATION.md)
- [第三方源码来源与许可](THIRD_PARTY_SOURCES.md)
- [外部资源条款](EXTERNAL_RESOURCES.md)
- [贡献说明](../CONTRIBUTING.md)
- [自动抠图节点开发文档](AUTO_CUTOUT_NODE_DESIGN.md)
- [ComfyUI 前端补丁说明](COMFYUI_PATCHES.md)
- [语音识别输入节点开发文档](SPEECH_RECOGNITION_INPUT_DESIGN.md)
- [更新日志](../CHANGELOG.md)

核心原则：

- 先确认来源和授权，再搬代码。
- 每个外部功能保持独立子插件目录。
- 节点 key 使用稳定、可读的功能名；所有节点必须用 `SEARCH_ALIASES` 补齐 `lx`、`LX`、`灵犀` 搜索入口。
- 子插件之间不要随意互相依赖，共用逻辑应沉淀到清晰的 shared 工具层。
- 新增节点必须能在 ComfyUI 启动日志、节点搜索、基本运行流程中验证。

## 基础检查

修改或新增节点后，可以运行：

```bash
python tools/check_project.py
```

它会检查 Python 语法、JSON 格式、节点 key 冲突、搜索别名、私有文件、文档漂移和前端 JS 语法。

## 常见问题

### 节点搜不到

先看 ComfyUI 启动日志中是否出现类似：

```text
[灵犀节点] 已加载 N 个节点（含 M 个插件）
```

如果某个子插件加载失败，顶层入口会打印失败插件名和错误原因。也可以尝试搜索显示名里的关键词，例如 `lx`、`LX`、`灵犀`、`图像`、`提示词`、`语音`、`Qwen3VL`、`Qwen3 文本生成`、`抠图`、`图像编辑`。

### 离线翻译第一次运行很久

离线翻译首次使用时可能需要下载并转换模型。这个过程取决于网络和磁盘速度，完成后会复用本地模型。请确认 `requirements-full.txt` 已安装到当前 ComfyUI Python 环境。

### 不确定依赖或模型是否装好

添加并运行 `灵犀环境诊断` 节点。它只检查当前 Python、依赖和模型文件状态，不会下载、转换模型，也不会修改环境。

### 自动抠图或语义抠图失败

优先检查：

- `requirements-full.txt` 是否安装到当前 ComfyUI Python 环境。
- 对应模型目录是否完整下载。
- HuggingFace 访问失败时是否需要配置 `HF_ENDPOINT` 镜像。
- `语义抠图` 是否已额外安装官方 `sam3` 包，并放好 SAM3.1 权重和 BPE 词表。

### 语音输入无法开始

优先检查：

- 浏览器是否允许麦克风权限。
- `requirements-full.txt` 是否安装到当前 ComfyUI Python 环境。
- 模型目录是否完整下载。
- HuggingFace 访问失败时是否需要配置 `HF_ENDPOINT` 镜像。
