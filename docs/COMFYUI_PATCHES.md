# ComfyUI 前端补丁说明

本项目允许在 `web/comfyui_patches/` 下维护少量、可删除的 ComfyUI 官方前端兼容补丁。

这些补丁只用于处理明确的 ComfyUI 前端回归或版本兼容问题，不注册节点，不修改 ComfyUI 官方打包文件，也不应该承载灵犀节点自身的业务逻辑。

## 目录约定

```text
web/comfyui_patches/
├─ README.md
├─ group_font_size/
│  ├─ README.md
│  └─ fix.js
└─ graphdialog/
   ├─ README.md
   └─ button_align_fix.js
```

ComfyUI 会自动加载 `WEB_DIRECTORY` 下所有 `.js` 文件，因此补丁文件只要保留 `.js` 后缀就会随本插件加载。

## 当前补丁

### `group_font_size/fix.js`

修复受影响 ComfyUI 前端版本中的组标题字号问题：

- 让 `LiteGraph.LGraphGroup` 正确读取并渲染自身 `font_size`。
- 保存工作流时保留非默认 `font_size`。
- 按字号缩放组标题栏高度和点击命中区域。
- 修复双击组标题编辑时输入框字号变小的问题。
- 修复右键 `Edit Group > Title` 时标题输入框字号不一致的问题。

该补丁原本来自本地独立热修插件 `ComfyUI-GroupFontSize-Fix`，现在已收敛进本项目，旧独立插件目录可以删除。

### `graphdialog/button_align_fix.js`

修复受影响 ComfyUI 前端版本中 LiteGraph `graphdialog` 按钮高度、居中和文本换行问题。

## 启用与禁用

启用方式：

- 保持补丁文件以 `.js` 结尾。
- 重启或刷新 ComfyUI 前端页面。

禁用方式：

- 删除对应补丁目录。
- 或把补丁文件改名为非 `.js` 后缀，例如 `fix.disabled`。
- 页面已经加载过旧文件时，需要硬刷新浏览器。

## 新增补丁规则

新增 ComfyUI 前端补丁前，需要满足：

- 问题来自官方前端或 LiteGraph 行为，不属于灵犀节点自身逻辑。
- 补丁作用范围尽量小，有明确选择器、事件或类名边界。
- 必须使用唯一 `app.registerExtension({ name })` 或唯一 DOM/style id。
- monkey patch 必须带 `Symbol.for(...)` 或等价防重复标记。
- 文件头部或同目录 README 说明修复对象、删除方式和验证方式。
- 不要依赖其他第三方插件一定存在。
- 不要写入用户配置、工作流、磁盘缓存或网络请求。

验证方式至少包括：

```bash
node --check web/comfyui_patches/<patch>/fix.js
python tools/check_project.py
```

如果 ComfyUI 正在运行，还应确认 `/extensions` 能列出新补丁文件。
