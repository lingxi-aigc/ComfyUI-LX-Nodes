# 发布操作说明

## 当前交付

`0.1.0-rc.4` 为公开首发候选版。项目代码采用 GPL-3.0-only，Apache 和 MIT 部分的原文与声明随包保留。 [首发范围](OPEN_SOURCE_REVIEW.md) · [验收记录](RELEASE_VALIDATION.md)

## 本地检查

在项目根目录、当前 ComfyUI 使用的 Python 环境中运行：

```bash
python tools/check_project.py
python -m unittest discover -s tests -p "test_release*.py" -v
python -m unittest discover -s tests -p "test_imagebatch_routes.py" -v
```

发布工具测试只需 Python 标准库；接口测试需要基础依赖 `aiohttp`。JS 语法检查需要 Node.js；缺少 Node.js 时基础脚本会提示跳过，因此须另行补验前端。这些检查不调用付费 API，也不下载模型。

## 生成审查 ZIP

```bash
python tools/build_release.py
```

输出到 `dist/`：

- `ComfyUI-LX-Nodes-v0.1.0-rc.4-review.zip`
- 同名 `.zip.sha256` 文件

ZIP 内只有一个顶层 `ComfyUI-LX-Nodes/`，可解压安装到 `custom_nodes/`。工具读取已列入白名单的当前磁盘源文件，包含尚未加入 Git 的新功能；它不依赖 `git archive`，也不修改 Git 索引。

包内包含根 `LICENSE`、`NOTICE`、`third_party.json` 和 `licenses/`。打包检查第三方许可文本的 LF 规范化哈希及对应源码声明，防止它们在整理时被误删；外部模型和依赖许可说明见 `docs/EXTERNAL_RESOURCES.md`。

打包时执行基础检查，扫描所选文件与本地 Git 引用可达历史中的常见凭据形态，排除私有配置、缓存、模型、运行程序、Git 数据和本地备份。ZIP 内的 `RELEASE_MANIFEST.json` 列出实际文件、大小、SHA256、扫描范围和公开发布待办。写入后重新读取 ZIP，核对文件清单、CRC 和每个文件的哈希。

历史扫描不包含其他远程仓库、不可达对象或托管平台缓存。匹配日志只显示文件位置和类型，不显示密钥内容。审查包中的历史扫描结果通过不能代替对自定义 Key、工作流和已有泄露的人工检查。

新增源资源类型应先在 `tools/build_release.py` 中审核并更新白名单。运行文件夹中的未审核文件类型会阻止打包，避免静默漏掉必要资源。重新构建会替换同版本 ZIP。

## 实际 ComfyUI 验收

在独立 ComfyUI 实例中安装发布源码和基础依赖，检查以下项目。

- 仅安装合并包即可加载节点，旧两个分包不重复注册。
- 拖入 `examples/text_basic.json` 后，文本能够进入“展示文本”节点。
- 前端资源可以加载，工作流管理能读取测试用户的工作流。
- 缺少可选依赖和模型时，基础工作流仍能运行。

改动涉及批量、图像对比、组控、广播、设置点和获取点时，复验对应的执行与保存流程。模型推理、API、语音、抠图用自有测试凭据与素材验收，记录系统、Python、ComfyUI 和前端版本。公开示例只使用演示数据。

## 转为公开版

完成拟发布范围的源码与安装验收后，更新 `release.json`，并将全部发布文件加入 Git、提交后，再执行：

```bash
python tools/build_release.py --public
```

公开模式要求授权和运行验收状态完成、声明了许可证且存在非空 `LICENSE`、本地历史扫描通过、所有打包源文件已被 Git 跟踪且已提交。状态字段由维护者依据真实审查结果填写；工具不会判断授权文件的法律效力，也不会自动授予第三方代码任何权限。

公开前复核提交内容和拟推送历史。完成提交后可打标签，并把构建好的 ZIP 及校验文件附加到 GitHub Release。
