# 组标题字号补丁

这是一个纯前端热修补丁，用于修复部分 ComfyUI 前端版本中组标题 `font_size` 没有被一致应用的问题。

补丁会作用于官方 `LiteGraph.LGraphGroup`：

- 每个 group 按自身 `font_size` 渲染标题。
- 工作流保存/加载时保留 `font_size`。
- 按字号缩放标题栏高度和点击命中区域。
- 双击编辑组标题时，输入框字号保持和可见标题一致。
- 右键 `Edit Group > Title` 编辑标题时，输入框字号保持和可见标题一致。

禁用方式：删除本目录，或把 `fix.js` 改名为 `fix.disabled`，然后硬刷新浏览器。
