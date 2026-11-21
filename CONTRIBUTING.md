# 参与开发

项目采用 `_plugins/<模块>/` 与 `web/<模块>/` 的结构，根入口统一加载。提交前先阅读 [节点入库规范](docs/PLUGIN_INTAKE_GUIDE.md)。

## 来源与授权

项目源码许可为 GPL-3.0-only，现有 Apache/MIT 部分仍保留原条款；当前候选的剩余事项见 [审查状态](docs/OPEN_SOURCE_REVIEW.md)。引入外部代码时，记录原仓库、作者、commit、许可证、声明和修改范围，并更新 NOTICE、许可文件与 third_party.json。

## 修改要求

- 保持已有节点 key、输入输出契约和工作流兼容。
- 新节点补齐 `lx`、`LX`、`灵犀` 搜索别名，分类使用 `_plugins/categories.py`。
- 共用代码放在明确的共享模块；前端文件通过统一 `web/` 入口加载。
- 使用可选依赖时提供清楚的缺失提示；避免在插件启动时安装依赖或调用远程生图服务。
- 功能变更同步更新 README、CHANGELOG 和必要测试。

## 提交与反馈

运行 `python tools/check_project.py` 和与改动有关的测试，命令见 [发布说明](docs/RELEASING.md)。提交时说明改动目的、复现步骤、验证环境与结果。

报告问题请提供 ComfyUI/Python/操作系统版本、完整错误日志和清除凭据后的最小工作流。请移除 API Key、令牌、个人图片和本地私有路径。
