# 自动抠图 节点开发文档

## 定位

`自动抠图` 是一个独立新增的 LX 图像节点，用来把输入图像快速转换成：

1. `图像`
2. `遮罩`

它的目标不是复用原作者插件的实现细节，而是基于原有模型与安装习惯，重新做一个更干净、更稳定的 LX 节点。

## 节点命名

- 显示名：`自动抠图`
- 内部类名：`AutoCutout`
- 节点 key：`AutoCutout`
- 分类：`🅻🆇 灵犀/图像处理`

## 模型顺序

模型下拉框顺序固定为：

1. `BEN2`
2. `RMBG-2.0`
3. `InSPyReNet`
4. `BiRefNet-Matting`
5. `BiRefNet-Dynamic`

这个顺序不是“性能排序”，而是用户要求的固定展示顺序。

默认选中 `InSPyReNet`。

## 面板参数

面板保持精简，只保留 8 个字段：

1. `图像`
2. `模型`
3. `处理分辨率`
4. `灵敏度`
5. `遮罩模糊`
6. `遮罩偏移`
7. `输出背景`
8. `背景颜色`

### 图像

类型：`IMAGE`

支持批量输入，输出也保持 batch 对齐。

### 模型

类型：枚举

取值：

- `BEN2`
- `RMBG-2.0`
- `InSPyReNet`
- `BiRefNet-Matting`
- `BiRefNet-Dynamic`

### 处理分辨率

类型：`INT`

默认 `1024`，建议范围 `256-2048`。

实现上会按模型做统一缩放策略：

- `RMBG-2.0` / `BiRefNet-Matting`：方形输入
- `BEN2` / `InSPyReNet` / `BiRefNet-Dynamic`：按长边缩放后再推理

### 灵敏度

类型：`FLOAT`

默认 `1.00`。

这个参数保留，但只做轻量后处理，不再引入额外复杂逻辑。它的意义是统一补偿不同模型的 mask 边界差异，方便用户微调。

### 遮罩模糊

类型：`INT`

默认 `0`。

用于平滑边缘。

### 遮罩偏移

类型：`INT`

默认 `0`。

用于扩大或收缩前景边界。

### 输出背景

类型：枚举

建议采用下面这组选项：

- `Alpha`
- `黑色`
- `白色`
- `自定义颜色`

优化思路：

- `Alpha` 是最常用结果，直接输出透明背景
- `黑色` / `白色` 适合快速预览
- `自定义颜色` 给需要特殊背景的用户留一个入口

### 背景颜色

类型：`COLOR`

默认 `#222222`

仅在 `输出背景 = 自定义颜色` 时生效。

## 出参

只保留两个输出：

1. `图像`
2. `遮罩`

不再输出额外的 `MASK_IMAGE`、状态文本、预览图之类的内容。

## 模型与下载路径

新节点默认使用 LX 自己的模型目录：

```text
ComfyUI/models/LX/auto_cutout/
```

建议的子目录结构：

```text
ComfyUI/models/LX/auto_cutout/
  BEN2/
  RMBG-2.0/
  InSPyReNet/
  BiRefNet-Matting/
  BiRefNet-Dynamic/
```

### 首次自动下载

- `BEN2`：下载到 `ComfyUI/models/LX/auto_cutout/BEN2/`
- `RMBG-2.0`：下载到 `ComfyUI/models/LX/auto_cutout/RMBG-2.0/`
- `InSPyReNet`：下载 `ckpt_base.pth` 到 `ComfyUI/models/LX/auto_cutout/InSPyReNet/`
- `BiRefNet-Matting`：下载到 `ComfyUI/models/LX/auto_cutout/BiRefNet-Matting/`
- `BiRefNet-Dynamic`：下载到 `ComfyUI/models/LX/auto_cutout/BiRefNet-Dynamic/`

### 兼容旧路径

如果原作者插件已经下载过模型，会优先复用旧路径，不重复下载：

```text
ComfyUI/models/RMBG/BiRefNet/
ComfyUI/models/RMBG/inspyrenet/
ComfyUI/models/RMBG/RMBG-2.0/
ComfyUI/models/RMBG/BEN2/
```

这意味着新节点可以直接接管本机已有模型，不要求用户重新下大文件。

## 依赖

节点实现会依赖这些库：

- `huggingface_hub`
- `transformers`
- `transparent-background`
- `safetensors`
- `einops`
- `timm`
- `opencv-python`

其中：

- `RMBG-2.0` / `BiRefNet-Matting` / `BiRefNet-Dynamic` 走 `transformers` 远程代码加载
- `InSPyReNet` 走 `transparent-background`
- `BEN2` 依赖 `timm`、`einops`、`opencv-python`

ComfyUI 本体已经提供 `torch` / `torchvision` 的情况下，这个节点就可以直接运行。

## 实现边界

第一版只做：

- 批量抠图
- 模型切换
- 统一输出图像和遮罩
- 后处理参数
- 自动下载和旧路径兼容

第一版不做：

- 前端动态隐藏颜色选择
- 多模型并发
- 额外输出端口
- 预览状态面板

## 推荐实现顺序

1. 新建 `_plugins/auto_cutout/`
2. 写统一模型加载器
3. 写统一 mask 后处理
4. 接入 4 个模型
5. 补依赖声明
6. 跑语法与项目自检
