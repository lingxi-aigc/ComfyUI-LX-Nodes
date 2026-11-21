# ComfyUI 前端补丁

这里存放少量可删除的 ComfyUI 官方前端热修补丁。

ComfyUI 会自动加载本插件 `WEB_DIRECTORY` 下的所有 `.js` 文件，所以每个补丁都独立放在自己的目录里。想禁用某个补丁时，删除对应目录，或把 `.js` 改成 `.disabled` 一类非 JS 后缀即可。

## 当前补丁

- `group_font_size/fix.js`
  - 修复 `LiteGraph.LGraphGroup` 的 `font_size` 渲染、保存和标题栏高度。
  - 修复组标题双击编辑时输入框字号变小的问题。

- `graphdialog/button_align_fix.js`
  - 修复受影响 ComfyUI 前端版本里的 GraphDialog 按钮高度、居中和文本换行问题。

更完整的维护说明见 [docs/COMFYUI_PATCHES.md](../../docs/COMFYUI_PATCHES.md)。
