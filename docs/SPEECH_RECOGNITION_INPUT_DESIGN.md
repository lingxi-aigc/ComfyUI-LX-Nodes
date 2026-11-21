# 语音识别输入节点开发文档

## 目标

实现一个类似微信语音输入体验的 ComfyUI 文本输入节点：

- 节点显示名为 `语音识别输入`，去掉 `LX_` 前缀。
- 点击 `START` 后开始录音，按钮变为绿色录音态并显示麦克风动效。
- 说话内容实时预览在原本的多行文本框内。
- 停顿后自动确认当前片段，并输出带标点文本。
- 点击 `STOP` 后处理最后一段音频，最终文本留在文本框并作为节点输出。
- 不使用浏览器 `SpeechRecognition` / `webkitSpeechRecognition`。
- 不依赖云 API。
- 固定使用 SenseVoice ONNX INT8 本地模型。
- 首次使用时自动下载模型，后续离线可用。

## 节点定义

显示名称：

```text
语音识别输入
```

内部 key 建议：

```text
SpeechRecognitionInput
```

分类：

```text
灵犀节点/语音工具
```

输出：

```text
STRING 文本
```

控件：

- 多行文本框：承载实时预览和最终文本。
- `START` / `STOP` 按钮：英文文字，左侧带麦克风图标。
- 不设置单独 `CLEAR` 按钮，用户可直接在文本框内编辑或删除文本。
- 音量动效：录音时在主按钮右侧显示 10 根内嵌迷你声波条，随麦克风输入跳动。

## 交互体验

1. 用户点击 `START`。
2. 前端请求麦克风权限。
3. 后端检查模型是否存在。
4. 模型不存在时自动下载，按钮显示 `DOWNLOADING`，状态区展示进度。
5. 模型下载完成后自动加载。
6. 加载完成后进入录音态，按钮变为绿色，文字变为 `STOP`。
7. 录音时麦克风图标发光，音量柱随输入跳动。
8. 用户说话时，文本框中实时显示临时识别状态。
9. 检测到停顿后切分音频片段，上传后端识别。
10. 后端返回带标点文本，前端追加到文本框。
11. 用户点击 `STOP` 后，前端上传最后一段残余音频。
12. 最终文本保留在文本框，节点输出该文本。

## 预览位置

预览直接做到原本的多行文本框，不做单独窗口。

内部维护两层状态：

```text
committedText: 已确认文本，作为最终输出的一部分
interimText: 当前临时文本，用于录音中的视觉预览
```

文本框显示：

```text
committedText + interimText
```

片段确认后：

```text
committedText += finalSegment
interimText = ""
```

这样用户看到的是实时输入效果，停止后文本框中自然就是最终结果。

## 流式策略

SenseVoice ONNX 不做真正逐 token streaming。节点采用更稳定的准流式方案：

```text
持续录音 -> 实时音量检测 -> 静音/最长时长切段 -> 后端识别片段 -> 文本框追加结果
```

推荐参数：

```text
采样率: 16000 Hz
声道: 单声道
格式: Float32 PCM 或 Int16 PCM
最短识别片段: 1.2 秒
最长识别片段: 5.0 秒
静音断句阈值: 850ms
音量刷新: 60fps 或约 100ms
文本刷新: 准确率优先，后端返回完整片段后直接追加
```

当前默认以准确率优先：识别按较完整片段执行，前端在后端返回片段后直接追加。视觉流式和更短切段可作为后续单独模式，不作为默认行为。

## 智能标点

智能标点分两层。

第一层：模型输出。

SenseVoice 识别时启用：

```text
use_itn=True
```

模型负责输出带标点、数字规整后的文本。

第二层：本地轻量后处理。

后端对每个最终片段执行：

- 合并重复标点。
- 去掉开头无意义标点。
- 不主动补句号。
- 大部分句号转换为逗号。
- 问句语气词结尾时补问号。
- 明显问号、感叹号保留，但不频繁生成。
- 去口头禅。
- 修正常见专业词。

默认专业词修正：

```text
空飞 UI / 康菲 UI -> ComfyUI
comfy ui -> ComfyUI
劳拉 -> LoRA
control net / 康特耐特 / 康特 net -> ControlNet
vae -> VAE
checkpoint -> checkpoint
工作流 -> 工作流
提示词 -> 提示词
节点 -> 节点
```

已确认文本不频繁回改，避免文本跳动。临时文本可变化，最终片段返回后再稳定落入文本框。

## 视觉设计

按钮状态：

- 未开始：深灰按钮，白色麦克风图标，文字 `START`。
- 正在录音：绿色按钮，浅绿色麦克风图标，文字 `STOP`。
- 下载模型：按钮禁用，文字 `DOWNLOADING`。
- 加载模型：按钮禁用，文字 `LOADING`。
- 识别中：保持绿色录音态，状态显示 `RECOGNIZING`。

动效：

- 标题始终保持 `语音识别输入`，不把状态拼进标题。
- 底部使用极简控制条：居中的 `START/STOP` 胶囊按钮，声波条内嵌在按钮右侧。
- 录音时按钮边框做轻微绿色呼吸光。
- 麦克风图标采用线性描边风格，录音时轻微发光。
- 按钮内部右侧显示 10 根迷你声波条，未录音时灰色静止，录音/识别时绿色跳动。
- 不绘制状态胶囊和底部说明文字，避免视觉拥挤。

图标实现：

- 优先用 Canvas 直接绘制麦克风图标，避免增加图标依赖。

## 快捷键

空格键作为语音输入开关：

```text
Space -> START / STOP
```

触发规则：

- 节点被选中、被点击，或文本框/按钮最近被点击过时，该节点成为 active speech node。
- 当前焦点在普通输入框、文本框或可编辑元素内时，空格保留原本输入行为，不触发录音。
- 下载、加载、停止收尾等忙碌状态下，空格不会重复触发。
- 忽略长按重复事件，避免一次按键触发多次切换。

## 模型下载

模型目录：

```text
ComfyUI/models/speech/sensevoice_onnx_int8

Plus 流式节点模型目录：
```text
ComfyUI/models/speech/paraformer_zh_streaming
```
```

首次点击 `START` 时检查模型文件。不存在则自动下载 INT8 必需文件，不下载完整仓库。

必需文件：

```text
am.mvn
embedding.npy
chn_jpn_yue_eng_ko_spectok.bpe.model
sense-voice-encoder-int8.onnx
fsmn-am.mvn
fsmn-config.yaml
fsmnvad-offline.onnx
```

预估体积：

```text
核心 ONNX INT8: 约 241MB
辅助文件: 约 10-30MB
总下载量: 约 250-280MB
建议预留磁盘: 400MB
```

下载源：

- 默认 HuggingFace。
- 可通过 `HF_ENDPOINT=https://hf-mirror.com` 使用镜像。

下载失败时显示明确错误，不静默失败。

## 后端接口

新增接口：

```text
GET  /lx/speech/status
POST /lx/speech/download
POST /lx/speech/transcribe
```

`GET /lx/speech/status` 返回：

```json
{
  "model_exists": true,
  "model_loaded": false,
  "downloading": false,
  "progress": 0,
  "message": "READY"
}
```

`POST /lx/speech/download` 返回：

```json
{
  "status": "downloading",
  "progress": 42,
  "message": "DOWNLOADING"
}
```

`POST /lx/speech/transcribe` 输入一段 PCM 音频，返回：

```json
{
  "status": "success",
  "text": "帮我生成一个女孩，穿红色衣服。",
  "raw": "...",
  "duration": 3.4
}
```

## 文件结构

建议结构：

```text
_plugins/speech_tools/
  __init__.py
  speech_recognition_input.py
  speech_routes.py
  sensevoice_engine.py
  audio_utils.py
  text_postprocess.py

web/speech_tools/
  speech_recognition_input.js
```

旧的 `lx_speech_input.py` 和 `lx_speech_input.js` 可以替换或删除，不再沿用浏览器识别逻辑。

## 前端职责

`speech_recognition_input.js` 负责：

- 绘制 `START` / `STOP` 按钮。
- 绘制麦克风图标。
- 绘制绿色录音态和音量柱动效。
- 请求麦克风权限。
- 使用 Web Audio 采集音频。
- 下采样到 16k 单声道。
- 计算实时音量。
- 根据静音和最长时长切分音频片段。
- 调用后端接口识别。
- 将识别结果写入原文本框。
- 显示下载、加载、录音、识别、错误状态。

禁止使用：

```text
SpeechRecognition
webkitSpeechRecognition
```

## 后端职责

`speech_recognition_input.py`：

- 定义 ComfyUI 节点。
- 输出文本框中的字符串。

`speech_routes.py`：

- 注册 HTTP 接口。
- 处理模型状态、下载、识别请求。

`sensevoice_engine.py`：

- 检查模型文件。
- 下载 INT8 必需文件。
- 加载 ONNX 模型。
- 调用 SenseVoice 推理。
- 返回原始识别结果。

`audio_utils.py`：

- 解析前端上传的 PCM。
- 校验采样率、声道、时长。
- 转为模型需要的 numpy waveform。

`text_postprocess.py`：

- 清理标点。
- 去口头禅。
- 修正专业词。
- 补齐句末标点。

## 依赖

新增依赖建议：

```text
onnxruntime
huggingface_hub
git+https://github.com/shadowcz007/SenseVoice-python.git
```

Plus 节点单独依赖放在 `requirements-plus.txt`，不要放进默认 `requirements.txt`：

```text
funasr
```

尽量避免基础节点新增：

```text
torchaudio
ffmpeg
大 PyTorch ASR 模型
```

前端直接上传 PCM，后端不依赖音频解码器。

## 验收标准

1. 节点显示名是 `语音识别输入`。
2. 节点没有 `LX_` 前缀。
3. 第一次点击 `START` 自动下载模型。
4. 下载完成后自动开始录音。
5. 录音时按钮变绿色，麦克风图标和音量柱有动效。
6. 说话时文本框内有实时输入体验。
7. 停顿后自动确认片段，并生成智能标点。
8. 点击 `STOP` 后最终文本保留在原文本框。
9. 节点输出文本框内容。
10. 不使用浏览器语音识别 API。
11. 不需要云 API。
12. 模型下载量控制在约 300MB 内。
