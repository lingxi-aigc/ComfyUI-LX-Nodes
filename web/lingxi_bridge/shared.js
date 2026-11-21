/**
 * LingxiBridge 前端公共模块
 *
 * 提供各节点 JS 扩展共用的工具函数和常量。
 * 由 lingxi_bridge 目录下的各 .js 在注册 extension 时按需导入。
 */

import { app } from "../../../../scripts/app.js";

// ─── 平台与比例常量（与 lb_image.py 保持一致）───────────────────────────────
export const IMAGE_RATIOS_BASE = ["auto", "1:1", "2:3", "3:2", "4:3", "3:4", "9:16", "16:9", "9:21", "21:9"];
export const IMAGE_RATIOS_EXTREME = ["1:4", "4:1", "1:8", "8:1"];
export const GPT_IMAGE2_EXTRA_RATIOS = ["1:3", "3:1", "5:4", "4:5", "1:2", "2:1"];

export const IMAGE_RATIOS_BY_PLATFORM = {
    "banana-pro": IMAGE_RATIOS_BASE,
    "banana-2": IMAGE_RATIOS_BASE.concat(IMAGE_RATIOS_EXTREME),
    "gpt-image2": IMAGE_RATIOS_BASE.concat(GPT_IMAGE2_EXTRA_RATIOS),
    "gpt-image2.5": IMAGE_RATIOS_BASE.concat(GPT_IMAGE2_EXTRA_RATIOS),
};

export const GPT_IMAGE2_SIZES = ["1K", "2K", "4K"];

// ─── 模型 → 平台映射 ────────────────────────────────────────────────────────
export const MODEL_PLATFORM = {
    "nano-banana-pro":                   "banana-pro",
    "nano-banana-pro-cl":                "banana-pro",
    "nano-banana-pro-vt":                "banana-pro",
    "gemini-3-pro-image-preview":        "banana-pro",
    "rhart-image-n-pro":                "banana-pro",
    "rhart-image-n-pro-official":       "banana-pro",
    "nano-banana-2":                    "banana-2",
    "nano-banana-2-cl":                 "banana-2",
    "gemini-3.1-flash-image-preview":  "banana-2",
    "rhart-image-n-g31-flash":          "banana-2",
    "rhart-image-n-g31-flash-official": "banana-2",
    "gpt-image-2-vip":                  "gpt-image2",
    "gpt-image-2":                      "gpt-image2",
    "gpt-image-2.5-flare-firefly": "gpt-image2.5",
    "gpt-image-2.5-sunburst-firefly": "gpt-image2.5",
    "rhart-image-g-2":                  "gpt-image2",
    "rhart-image-g-2-official":         "gpt-image2",
};

export function modelMatchesPlatform(model, platform) {
    return MODEL_PLATFORM[model] === platform;
}

// ─── 节点尺寸常量 ────────────────────────────────────────────────────────────
export const MIN_WIDTH = 380;

// ─── 防抖工具 ────────────────────────────────────────────────────────────────
let _debounceTimers = {};

export function debounce(name, fn, ms = 300) {
    clearTimeout(_debounceTimers[name]);
    _debounceTimers[name] = setTimeout(() => {
        delete _debounceTimers[name];
        fn();
    }, ms);
}

// ─── 节点尺寸工具 ────────────────────────────────────────────────────────────

/**
 * 锁定节点宽度：在 widget 显示/隐藏操作前后调用，
 * 防止 LiteGraph 的 computeSize() 把节点缩窄。
 */
export function getLinkedOriginNode(node, input) {
    const graph = node?.graph;
    const id = input?.link;
    if (!graph || id == null) return null;
    const link = typeof graph.getLink === "function" ? graph.getLink(id)
        : graph.links?.get?.(id) ?? graph.links?.[id];
    return link ? graph.getNodeById(link.origin_id) : null;
}

export function captureWidth(node) {
    return Array.isArray(node.size) && node.size.length >= 2 ? node.size[0] : MIN_WIDTH;
}

export function restoreWidth(node, savedWidth) {
    if (!node || !Array.isArray(node.size)) return;
    const targetW = Math.max(savedWidth || 0, MIN_WIDTH);
    if (node.size[0] !== targetW) {
        node.setSize([targetW, node.size[1]]);
    }
}

export function ensureMinSize(node, minW = MIN_WIDTH, minH = 0) {
    if (!node || !Array.isArray(node.size) || node.size.length < 2) return;
    let w = node.size[0];
    let h = node.size[1];
    let changed = false;
    if (w < minW) { w = minW; changed = true; }
    if (minH > 0 && h < minH) { h = minH; changed = true; }
    if (changed) {
        node.setSize([w, h]);
    }
}

// ─── widget 显隐工具 ────────────────────────────────────────────────────────
export function isWidgetHidden(w) {
    return w?.hidden || w?.type === "hidden";
}

function clearWidgetLayoutCache(w) {
    if (!w) return;
    delete w.width;
    delete w.last_y;
}

export function hideWidget(w) {
    if (!w) return;
    if (isWidgetHidden(w)) {
        clearWidgetLayoutCache(w);
        return;
    }
    w._origType = w.type;
    w._origComputeSize = w.computeSize;
    clearWidgetLayoutCache(w);
    w.hidden = true;
    w.type = "hidden";
    w.computeSize = () => [0, 0];
    if (w.inputEl) {
        w.inputEl.style.display = "none";
        w.inputEl.style.visibility = "hidden";
        w.inputEl.style.pointerEvents = "none";
        w.inputEl.tabIndex = -1;
    }
}

export function showWidget(w) {
    if (!w) return;
    if (!isWidgetHidden(w)) {
        clearWidgetLayoutCache(w);
        return;
    }
    w.hidden = false;
    w.type = w._origType || "combo";
    if (w._origComputeSize) {
        w.computeSize = w._origComputeSize;
    } else {
        delete w.computeSize;
    }
    clearWidgetLayoutCache(w);
    if (w.inputEl) {
        w.inputEl.style.display = "";
        w.inputEl.style.visibility = "";
        w.inputEl.style.pointerEvents = "";
        w.inputEl.tabIndex = 0;
    }
}
