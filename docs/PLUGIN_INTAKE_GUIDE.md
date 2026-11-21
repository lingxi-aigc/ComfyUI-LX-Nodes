# 外部节点入库规范

这份文档用于规范“从外部看到好用节点，筛选后清洗并纳入 ComfyUI-LX-Nodes”的流程。目标是让项目长期保持好维护、好扩展、好排错，而不是越加越乱。

## 一句话原则

外部节点不要直接整包塞进来。先判断值不值得收，再确认授权，最后按灵犀节点的结构改名、隔离、精简、测试、记录。

## 1. 候选记录

每个候选插件先记录清楚来源，建议保存在后续的 `docs/ADOPTED_PLUGINS.md` 或单独 issue/笔记里。

```markdown
## 插件名称

- 来源地址：
- 原作者：
- 原仓库版本 / commit：
- 获取日期：
- 授权协议：
- 想保留的节点：
- 不纳入的节点：
- 纳入理由：
- 风险点：
- 我方改动摘要：
```

必须确认的事项：

- 授权是否允许复制、修改、再发布。
- 是否有商业使用限制。
- 是否包含模型、图片、字体、工作流等额外素材的授权问题。
- 是否有隐藏网络请求、上传文件、写系统目录、执行外部命令等行为。
- 是否强依赖特殊环境或大体积第三方库。

如果授权不清楚，先不要入库。

## 2. 筛选标准

优先纳入：

- 高频、稳定、用户确实会反复用的节点。
- 功能边界清楚，能独立维护。
- 代码量可控，不需要整套复杂框架。
- 输入输出符合 ComfyUI 常规类型。
- 能和现有 `LX` 节点形成组合价值。

谨慎纳入：

- 大量 monkey patch ComfyUI 全局行为的插件。
- 启动时自动联网、自动下载、自动修改配置的插件。
- 把很多无关功能混在一起的插件。
- 没有授权说明、来源不明、代码混淆的插件。
- 依赖非常重，且只为了一个小功能。

例外情况：如果是为了修复明确的 ComfyUI 官方前端回归或 LiteGraph 兼容问题，可以作为小型热修补丁放入 `web/comfyui_patches/`，但必须按 `docs/COMFYUI_PATCHES.md` 记录修复范围、启停方式和验证方式。

## 3. 入库目录

每个功能包放一个独立子目录：

```text
_plugins/<plugin_slug>/
├─ __init__.py
├─ nodes.py
└─ 其他内部模块.py
```

如果需要前端扩展：

```text
web/<plugin_slug>/
└─ <plugin_slug>.js
```

如果不是节点功能，而是 ComfyUI 官方前端兼容热修：

```text
web/comfyui_patches/<patch_slug>/
├─ README.md
└─ fix.js
```

命名建议：

- 子插件目录使用小写英文、数字和下划线，例如 `image_tools`。
- Python 文件使用小写英文和下划线。
- 节点 key 使用稳定、可读的功能名，例如 `GlobalInput`、`BroadcastBlock`，不要强制加 `LX` 前缀。
- 显示名优先使用直接可读的中文名，例如 `全局输入`、`屏蔽广播`，不要求带 `LX`。
- 分类统一使用 `🅻🆇 灵犀/<分类>`，例如 `🅻🆇 灵犀/图像处理`。
- 所有节点必须补充 `SEARCH_ALIASES`，至少包含 `lx`、`LX`、`灵犀`，并保留功能别名与旧名称。

## 4. 注册约定

子插件的 `__init__.py` 必须导出：

```python
from .nodes import ExampleNode

NODE_CLASS_MAPPINGS = {
    "ExampleNode": ExampleNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ExampleNode": "示例节点",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
```

注意：

- 节点 key 不能和现有节点重复。
- 不建议使用 `from .xxx import *`，后续更难排查命名污染。
- 子插件导入失败时，顶层加载器会跳过该插件，但用户会在启动日志看到错误。
- 节点类必须添加 `SEARCH_ALIASES`，并把 `lx`、`LX`、`灵犀`、旧名称和功能同义词一起放进去。

## 5. 清洗步骤

### 5.1 改命名

把外部插件的节点 key、显示名、分类改成灵犀项目自己的命名体系。

```python
class ExampleNode:
    CATEGORY = "🅻🆇 灵犀/图像处理"
    SEARCH_ALIASES = ["lx", "LX", "灵犀", "示例节点", "旧节点名", "example node"]

NODE_NAME = "ExampleNode"
```

这样可以避免：

- 和原插件同时安装时冲突。
- 用户搜索时不知道哪些节点属于本项目。
- 后续日志和 bug 反馈难定位。

建议优先规则：

- key 保持稳定，避免频繁改名。
- 显示名可以去掉 `LX`，但旧名称要保留在 `SEARCH_ALIASES`。
- 新增或迁移节点时，统一补 `SEARCH_ALIASES`，让 `lx`、`LX`、`灵犀`、功能名都能搜到。

### 5.2 精简功能

只保留真正要纳入的节点和工具函数。

删除或暂不迁入：

- demo、测试脚本、无关工作流。
- 原插件的发布脚本、CI、截图素材。
- 不再使用的前端文件。
- 和当前功能无关的大段工具代码。

### 5.3 隔离依赖

新增依赖前先判断是否值得。

如果必须新增依赖：

- 写入 `requirements.txt`。
- 在 README 里说明用途。
- 在节点导入失败时给出清晰提示。
- 避免在 ComfyUI 启动时做耗时下载或初始化。

### 5.4 处理配置

配置文件不要混进源码逻辑。

建议：

- 默认配置放 `*.example.json`。
- 用户私有配置放本地文件，并加入 `.gitignore`。
- API Key、token、cookie、绝对路径不要提交。
- 写配置时使用 UTF-8 和 `ensure_ascii=False`。

### 5.5 统一编码

所有 `.py`、`.js`、`.md`、`.json` 都使用 UTF-8。

如果出现中文乱码，优先检查：

- 文件是否用 UTF-8 保存。
- PowerShell 或编辑器是否按 UTF-8 打开。
- 是否从网页复制了不可见字符。

### 5.6 安全处理路径

涉及保存文件、扫描目录、读用户输入路径时，必须处理：

- 首尾引号。
- 环境变量和用户目录。
- 路径规范化。
- 非法字符。
- 防止 `..` 跳出保存根目录。
- 同名覆盖策略是否符合预期。

## 6. 前端扩展约定

前端扩展放在 `web/<plugin_slug>/` 下，并使用 ComfyUI 的扩展注册方式：

```javascript
import { app } from "../../../../scripts/app.js";

app.registerExtension({
    name: "Lingxi.Example",

    async nodeCreated(node) {
        if (node.comfyClass !== "ExampleNode") return;
        // 前端逻辑
    },
});
```

注意：

- `name` 要唯一。
- 只处理自己的 `node.comfyClass`。
- 加 interval、事件监听、DOM 引用时，要在 `node.onRemoved` 中清理。
- 不要假设其他插件一定存在。

### 6.1 ComfyUI 官方前端补丁约定

如果补丁修的是 ComfyUI 官方前端或 LiteGraph 的版本兼容问题，而不是某个灵犀节点功能，应放在 `web/comfyui_patches/<patch_slug>/`。

这类补丁必须满足：

- 不注册节点，不写入工作流，不修改用户配置。
- 只 patch 明确的官方前端对象、事件或 DOM 选择器。
- 使用唯一 `app.registerExtension({ name })`、唯一 style id 或唯一 `Symbol.for(...)` 防重复标记。
- 同目录 README 说明修复对象、删除方式和验证方式。
- 官方修复后可以直接删除目录，或把 `.js` 改成非 `.js` 后缀禁用。

详细规则见 `docs/COMFYUI_PATCHES.md`。

## 7. HTTP 路由约定

如果子插件需要注册 HTTP 路由：

- 路由前缀要有项目或插件命名空间，例如 `/lx_imagebatch/...`、`/relayapi/...`。
- 注册失败不应影响普通节点加载。
- 返回 JSON，错误时带 `status` 或 `success` 字段和可读 message。
- 不要把敏感信息完整返回给前端或日志。

## 8. 测试清单

每次新增或迁移节点后，至少验证：

- ComfyUI 能正常启动。
- 启动日志显示灵犀节点加载数量增加。
- 节点搜索能通过 `lx`、`灵犀`、功能名搜到新节点。
- 节点分类正确。
- 每个 required 输入都有合理默认值。
- 空输入、非法路径、空图片、错误 API Key 等异常路径不会直接崩 ComfyUI。
- 中文路径、空格路径、带引号路径能正常处理。
- 如果有前端 JS，刷新页面后不会重复注册按钮或定时器。
- 如果有保存文件，确认覆盖/追加策略正确。
- 如果有网络请求，确认超时和错误提示可读。

可用的基础检查：

```powershell
python -m compileall .
```

如当前机器没有完整 ComfyUI Python 环境，至少保证语法检查通过；运行检查需要在实际 ComfyUI 环境里完成。

## 9. 入库完成标准

一个外部节点算真正入库完成，需要满足：

- 代码在 `_plugins/<plugin_slug>/` 下独立成包。
- 节点 key、显示名、分类和搜索别名已按灵犀项目规范整理。
- 不需要的原插件文件已移除。
- 来源、授权、改动记录已写清。
- README 或对应文档已补充用法。
- 基础功能在 ComfyUI 中跑通过。
- 没有把用户 API Key、个人路径、临时文件提交进项目。

## 10. 建议的入库流程

1. 建一个临时目录或临时分支研究原插件。
2. 只挑选要保留的节点和必要工具函数。
3. 新建 `_plugins/<plugin_slug>/`。
4. 改节点 key、显示名、分类、搜索别名。
5. 迁移必要前端到 `web/<plugin_slug>/`。
6. 抽掉无关依赖和副作用。
7. 添加或更新文档。
8. 重启 ComfyUI 验证。
9. 记录来源、授权、改动摘要。

## 11. 未来可以自动化的部分

后续可以写一个小脚手架命令，用来生成：

```text
_plugins/<plugin_slug>/__init__.py
_plugins/<plugin_slug>/nodes.py
web/<plugin_slug>/
docs/intake/<plugin_slug>.md
```

这样每次新增节点都从同一个结构开始，维护成本会低很多。
