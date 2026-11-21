# 外部模型、运行程序和依赖

核查日期：2026-10-18。节点代码 GPL-3.0-only 不改变外部资源许可。源代码 ZIP 不包含权重、运行程序或第三方 Python 包；使用者按具体条款获取和使用资源。另行整合分发时，应保留对应许可与声明。

## 模型与程序

自动抠图的 BEN2、BiRefNet 和 RMBG 可按需下载并加载模型仓库提供的 Python 文件。使用这些后端前可在下表查看模型来源和镜像差异。

| 功能 | 原始来源与核查结果 | 使用与分发说明 |
| --- | --- | --- |
| BEN2 | [PramaLLC/BEN2](https://huggingface.co/PramaLLC/BEN2) 模型卡和[代码许可](https://github.com/PramaLLC/BEN2/blob/main/LICENSE) 为 MIT。镜像 `BEN2.py` blob 和 `BEN2_Base.pth` SHA256 与原仓库一致。 | 已定位原出处；另行分发时保留 Prama LLC 的 MIT 声明。 |
| BiRefNet Matting / Dynamic | 原 [Matting](https://huggingface.co/ZhengPeng7/BiRefNet-matting)、[Dynamic](https://huggingface.co/ZhengPeng7/BiRefNet_dynamic) 模型卡及[代码许可](https://github.com/ZhengPeng7/BiRefNet/blob/main/LICENSE) 为 MIT。镜像对应权重 SHA256 一致。 | 镜像 `birefnet.py` 与对照原仓库 blob 不同；不将权重核对结果扩展成所有镜像代码均已审查。 |
| RMBG-2.0 | [BRIA 官方说明](https://huggingface.co/briaai/RMBG-2.0) 有非商业条件，商业使用需另行协议。镜像与官方 `model.safetensors` SHA256 相同。 | 镜像不消除原模型使用条件；其 Python 实现有差异。代码 GPL 不授予模型商用权。 |
| InSPyReNet | [transparent-background](https://github.com/plemeri/transparent-background) 库及本地 1.3.4 元数据标 MIT；节点另指向 release `1.2.12` 的 `ckpt_base.pth`。 | 未下载历史权重做内容审查；库许可不能单独证明每个附件的条款。源包不含权重。 |
| SAM3.1 | [官方模型](https://huggingface.co/facebook/sam3.1) 使用 SAM License。两个配置镜像的 `sam3.1_multiplex.pt` 与官方 LFS SHA256 相同，均带 SAM 许可文件。 | 自定义 SAM License，不能标成 MIT/Apache；遵守官方获取和使用条件。没有下载受限权重或把权重打进源包。 |
| SenseVoice ONNX | [转换模型卡](https://huggingface.co/lovemefan/SenseVoice-onnx) 标 MIT，[原代码](https://github.com/FunAudioLLM/SenseVoice/blob/main/LICENSE) 有 MIT 文本。 | VAD、词表等配套文件仍按实际文件核对声明，不将一条模型卡许可当作全部附件已审查。 |
| FunASR streaming | [模型卡](https://huggingface.co/funasr/paraformer-zh-streaming) 明确 `apache-2.0-20260804` 标签覆盖权重和所列配套文件；已取得该标签 Apache-2.0 原文。 | 可按固定 revision 复核部署；本项目当前模型下载尚未锁 revision。Python 库本身的 MIT 与模型许可分别处理。 |
| NLLB-200-600M | [官方模型卡](https://huggingface.co/facebook/nllb-200-distilled-600M) 标 CC-BY-NC-4.0。 | 有非商业条件；转换到 CTranslate2/INT8 不自动改变原许可。 |

### Qwen 2.1 编辑模型

「Qwen 2.1 多图编辑画布」使用用户自行安装的 Qwen 图像编辑模型、图文编码器和 VAE。量化模型和 LoRA 也按各自来源与许可获取；官方模型条款见 [Qwen Image 2.1 许可](https://github.com/QwenLM/Qwen-Image-2.1/blob/main/LICENSE)。

### 权重内容身份

以下为公开 LFS 元数据对照，没有下载数 GB 权重。它们是内容身份线索，不代替许可，也不证明任意既有本地缓存属于相同版本。

| 镜像资源 | 对照原仓库 revision | 一致 SHA256 |
| --- | --- | --- |
| BEN2 `BEN2_Base.pth` | `PramaLLC/BEN2@e48a20765fb421d19dcdb0bf3cc61e802ca5ec8f` | `926144a876bda06f125555b4f5a239ece89dc6eb838a863700ca9bf192161a1c` |
| BiRefNet Matting | `ZhengPeng7/BiRefNet-matting@eccde0a8cbdce7ac5fecfeb06340fe7b949e85d9` | `a9875de5b1e6c8eb5fdaa8c727a82927ce442cdc87ba3abee6a77e6fa46c25bb` |
| BiRefNet Dynamic | `ZhengPeng7/BiRefNet_dynamic@280306042f57b7a33854319da62fd86aaa89ec4c` | `e3d2e4884e51ff30f0cd630edc6b1e41b06b7f23a0a2a5169f7b7cb33a711c2d` |
| RMBG-2.0 | `briaai/RMBG-2.0@5df4c9c76d8170882c34f6986e848ee07fd0ba43` | `566ed80c3d95f87ada6864d4cbe2290a1c5eb1c7bb0b123e984f60f76b02c3a7` |
| SAM3.1 两个镜像 | `facebook/sam3.1@daa63191845a41281374e725f4c9e51c7a824460` | `0567debeec80ba4ac6369540c6c248025283cb3ff2b92827509e57e2b3541cb6` |

## Python 依赖元数据

读取当前 ComfyUI Python 发行包 METADATA；不是锁定文件，也不表示新安装会得到相同版本。各包可能还含配套第三方组件，应保留原发行包声明。未为核查安装或更新依赖。

| 依赖 | 本地版本 | 声明 |
| --- | --- | --- |
| Pillow | 12.2.0 | MIT-CMU |
| numpy | 1.26.4 | BSD 系列及包内配套声明 |
| requests | 2.34.2 | Apache-2.0 |
| aiohttp | 3.14.1 | Apache-2.0 AND MIT |
| huggingface_hub | 1.13.0 | Apache-2.0 |
| onnxruntime | 1.26.0 | MIT |
| transformers | 5.9.0 | Apache-2.0 |
| ctranslate2 | 4.8.0 | MIT |
| sentencepiece | 0.2.1 | 已核对 [v0.2.1 原许可](https://github.com/google/sentencepiece/blob/v0.2.1/LICENSE)，Apache-2.0；本地 METADATA 未填写该字段。 |
| accelerate | 1.13.0 | Apache-2.0 |
| transparent-background | 1.3.4 | MIT 分类声明 |
| safetensors | 0.8.0 | Apache 许可分类声明 |
| einops | 0.8.2 | MIT |
| timm | 1.0.27 | Apache-2.0 |
| opencv-python | 4.13.0.92 | Apache-2.0；另查所用 wheel 的配套声明 |
| funasr | 1.3.14 | MIT |
| SenseVoice-python / sensevoice-onnx | 本地未找到发行元数据 | 当前 Git fork 的 `setup.py` 和 PyPI 1.1.0 声明 MIT；fork 和父仓库均未找到根 LICENSE。不补造作者原文。 |

## 分发边界

本 ZIP 只为实际纳入的第三方源码保存 GPL、Apache、MIT 文本；外部资源不能因本项目公开而被宣称为全部可无条件商用。API 功能向用户配置的服务上传文本/图片，按相应条款及费用使用；源包不含 Key。

外部资源的上述具体缺项继续记录在此，不再将每个本地工具模块一律标为“来源不明”。
