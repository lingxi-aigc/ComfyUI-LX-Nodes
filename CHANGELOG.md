# 更新日志

本文件记录 ComfyUI-LX-Nodes 的重要变更。格式参考 Keep a Changelog，但按本项目实际维护节奏简化。

## 未发布

## 0.1.0-rc.4 · GitHub 首发

- 合并发布工作流管理、批量图像与提示词、中转站、资源清理、设置点和获取点、广播及多图编辑。新增安装说明和无模型示例。
- 在独立 ComfyUI 实例验证插件启动、文本工作流，以及按原名和子目录保存图像。
- Qwen Image 2.1 本地 PE 模块的发布等待再分发许可确认。

### 第三方许可整理：0.1.0-rc.2


- 按维护者选择，以 GPL-3.0-only 整理项目源码许可；补齐 Use Everywhere、KJNodes/SetGet 和 rgthree 绘图片段来源。
- 保存 GPL、Apache-2.0、MIT 原文，新增 NOTICE、机器可读范围和许可哈希，补回源码和镜像中的必要声明与修改说明。
- 核对 BEN2、BiRefNet、RMBG、SAM3.1 镜像权重公开哈希，分别记录外部模型、程序、依赖的许可及具体缺项。
- 整理首发范围、外部模型及依赖条款和运行验收记录。
- 发布工具检查第三方许可原文与源码声明，防止整理或打包时误删。

### 发布整理：0.1.0-rc.1

- 经维护者确认，删除三个文件夹图像节点中其有权修改的旧署名、联系方式及限制声明，同步更新授权记录。

- 统一三个原分包的发布目录，新增 `release.json` 标记授权与运行验收待完成状态。
- 新增按文件白名单打包、凭据模式扫描、本地 Git 历史扫描、ZIP 清单与哈希校验；提供私有审查包和公开版检查模式。
- 补充逐文件/模块授权缺项清单、发布说明、贡献说明、问题模板和 GitHub 自动检查配置。
- 新增无模型、无 API Key 的基础文本工作流，以及打包排除、公开版条件、归档完整性与示例执行测试。
- 第三方代码按相应许可证核对保留声明；未添加覆盖全部代码的开源许可证。

### Added

- 新增 `Qwen 2.1 多图编辑画布`，合并多参考图处理、提示词编码和原生采样画布，支持跟随参考图比例或自定义宽高。

- 新增 `Qwen 2.1 高分辨率编辑画布`，可按姿势参考图的比例生成目标 latent，并独立控制人物参考尺寸。

- 新增 `Qwen 文本生成` 节点，调用阿里云百炼 Qwen 文本模型，支持 `qwen3.7-plus`、`qwen3.6-flash`、`qwen3.7-max`，提供 `user_prompt`、`system_prompt`、`creativity`、`seed` 和 API Key 遮罩输入，并内置本地缓存。
- 新增 `docs/AUTO_CUTOUT_NODE_DESIGN.md`，记录自动抠图节点的模型顺序、面板参数、模型路径和实现边界。
- 新增 `docs/SPEECH_RECOGNITION_INPUT_DESIGN.md`，记录语音识别输入节点的交互、模型下载、前后端职责和验收标准。
- 新增 `docs/ADOPTED_PLUGINS.md`，用于记录外部节点、历史代码和本项目整理代码的来源与授权状态。
- 新增 `docs/COMFYUI_PATCHES.md`，用于说明 ComfyUI 官方前端热修补丁的目录、启停方式和维护规则。
- 新增组标题字号前端补丁，修复 group `font_size` 渲染、保存、标题栏高度以及双击编辑标题时输入框变小的问题。
- 增强 `tools/check_project.py`：
  - 检查运行时私有配置和缓存目录是否被 Git 跟踪。
  - 扫描常见密钥形态，降低误提交 API Key 的风险。
  - 增加 `global_input` 和 `group_control` 双份前端资源漂移提示。
  - 检查节点 `SEARCH_ALIASES` 是否包含 `lx`、`LX`、`灵犀`。

### Changed

- Qwen 2.1 多图编辑画布作为新建工作流的入口，独立画布标记为旧工作流兼容节点。
- 工作流管理允许确认删除已打开的工作流，支持同目录拖拽排序、工作流置顶与取消置顶。
- Qwen 2.1 多图编辑画布根据已连接的参考图显示画幅选项，「自定义比例」可点选常用宽高比。采样尺寸与参考图尺寸分开展示，正向、负向提示词紧邻显示。
- 将 `ComfyUI-LX-ImageBatch`、`ComfyUI-LX-Relay` 合入一个安装目录，保留 20 个迁入节点的 key、配套前端扩展和中转缓存路径。
- 文件夹图像计数器重置接口由 `imagebatch` 模块注册，统一更新安装迁移说明、私有配置说明和来源授权记录。
- 项目检查脚本改为检查合并后的模块文档，并覆盖新增模块的未跟踪文件提示。

- 将 ComfyUI 前端兼容热修集中到 `web/comfyui_patches/`，旧的独立 `ComfyUI-GroupFontSize-Fix` 补丁已收敛为项目内置补丁。
- 更新 README 的文档目录与开发文档入口，只保留当前仍有维护价值的文档链接。
- `Qwen 文本生成` 节点面板调整为通用文本生成结构：`model`、`user_prompt`、`system_prompt`、`creativity`、`seed`、`api_key`，输出保持单一 `text`。

### Removed

- 删除过期的远程生图/API 池/并发生图/任务队列设计草案：
  - `docs/LINGXI_API_POOL_NODE_DESIGN.md`
  - `docs/LINGXI_CONCURRENT_IMAGE_NODE_DESIGN.md`
  - `docs/LINGXI_TASK_QUEUE_NODE_DESIGN.md`
- 删除早期旧模块审计清单 `docs/PROJECT_OPTIMIZATION_NOTES.md`，避免与当前 README 和实际加载目录产生冲突。
