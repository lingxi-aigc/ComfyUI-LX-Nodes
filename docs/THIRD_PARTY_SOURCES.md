# 第三方源码来源与许可

核查日期：2026-10-18。维护者选择保留设置点/获取点，并按 GPL-3.0 整理兼容的发布许可。当前项目代码许可为 **GPL-3.0-only**；上游 Apache-2.0、MIT 许可及声明同时保留。

## 已定位并处理的源码

| 本地范围 | 原项目与对照版本 | 证据与许可 | 已保留内容 |
| --- | --- | --- | --- |
| `web/global_input/`、`_plugins/global_input/js/` | [cg-use-everywhere](https://github.com/chrisgoringe/cg-use-everywhere/tree/50ae9f8c5d8b9538589663c90a15d4067a02969c)，提交 `50ae9f8c5d8b9538589663c90a15d4067a02969c` | 18 个前端文件对应上游；classes 文件 111 条长行中 104 条相同，UI 文件 142 条中 123 条相同。Apache-2.0。 | `licenses/Apache-2.0.txt`、根 `NOTICE`、配套 JS/CSS 来源和修改说明。上游树没有单独 NOTICE。 |
| `web/set_get/lx_set_get.js` | [ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes/blob/d3cfe21625e5170126ce06fbfcfe1d88108688c3/web/js/setgetnodes.js)，提交 `d3cfe21625e5170126ce06fbfcfe1d88108688c3` | 45 条较长语句完全匹配，涉及跨图转换、连接还原、菜单及绘制。上游 GPL v3。 | 根 `LICENSE`、`NOTICE`、文件头；保留 KJNodes 原注释中的 [diffus3 SetGet 来源](https://github.com/diffus3/ComfyUI-extensions)，该原项目也提供 GPL v3。 |
| `web/group_control/group_control.js`、内部镜像 | [rgthree-comfy](https://github.com/rgthree/rgthree-comfy/blob/2c5342a8cb0eaecaabf61435a5f37dd594c510ba/web/comfyui/fast_groups_muter.js)，提交 `2c5342a8cb0eaecaabf61435a5f37dd594c510ba` | 控件箭头、分隔线绘图片段对应 Fast Groups Muter。保守保留该部分 MIT，不将整个组控实现归为上游。 | `licenses/rgthree-MIT.txt` 原版权及完整许可、根 `NOTICE`、两个文件的修改说明。 |

对照提交是本次实际检查版本，不代表已恢复最初引入日期。源行统计去掉空白并使用 40/45 字符长度阈值，仅辅助定位，不能替代许可判断。加入声明后行号有所变化。

许可原文直接从对照源码保存，范围和原文哈希记录在根 `third_party.json`。项目检查和打包工具会验证它们仍存在。GPL 与 Apache-2.0 组合的兼容性说明见 [GNU 许可列表](https://www.gnu.org/licenses/license-list.html#apache2)。

## 首发范围

Qwen Image 2.1 PE 提示词增强及其专用画布在开发时参考了 [T8mars 的 ComfyUI Qwen Image Prompt Rewrite T8](https://github.com/T8mars/Comfyui-Qwen-Image-Prompt-Rewrite-T8)。这两项的源码、前端和测试未随首发分发，再分发许可仍待确认。

## 其余本地模块

本次对照了本机 KJNodes、Easy-Use、rgthree、RMBG、Custom-Scripts、Comfyroll 和 Essentials。部分文件仅共享少量 ComfyUI 注册扩展、回调、控件访问语句，不据此把整个模块认定为搬入代码。

多重 LoRA、元节点、备注、排版、图像处理及其余模块，按维护者“大部分自行实现”的说明记录，本次未定位到可明确归因的非通用复制片段。这不是穷尽网络检索的原创保证。

已删除维护者确认有权修改的旧署名、联系方式和禁止使用文字；已核清组件的版权、许可及技术参考链接按相应条款保留。

外部模型、Python 包和运行程序不随 ZIP 分发，条款另见 [EXTERNAL_RESOURCES.md](EXTERNAL_RESOURCES.md)。
