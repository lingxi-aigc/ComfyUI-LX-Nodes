/**
 * LingxiBridgeImage 前端扩展
 *
 * 职责：
 *  - 监听 settings 节点 platform 下拉值变化
 *  - gpt-image2：quality + moderation 显示；AI派协议由 size 直接表示 1K/2K/4K 清晰度
 *  - banana-pro / banana-2：quality + moderation 隐藏（节点高度自然收缩）
 *  - 平台切换时保留 ratio；仅当前 ratio 不被新平台支持时回退到 auto
 *  - 监听 settings 连线变化
 */

import { app } from "../../../../scripts/app.js";
import {
    IMAGE_RATIOS_BY_PLATFORM,
    GPT_IMAGE2_SIZES,
    IMAGE_RATIOS_BASE,
    MIN_WIDTH,
    getLinkedOriginNode,
    isWidgetHidden,
    hideWidget,
    showWidget,
} from "./shared.js";

const BOTTOM_SPACER_NAME = "__lx_bottom_spacer";
const BOTTOM_SPACER_HEIGHT = 6;
const AIPAI_IMAGE_RATIOS = ["auto", "1:1", "3:2", "2:3", "16:9", "9:16", "4:3", "3:4", "5:4", "4:5", "21:9"];
const AIPAI_ADOBE_RATIOS = ["auto", "1:1", "5:4", "4:3", "3:2", "16:9", "21:9", "4:5", "3:4", "2:3", "9:16", "1:2", "2:1", "9:21"];

function getAdobeProfile(settingsNode) {
    const value = (name) => settingsNode?.widgets?.find(w => w.name === name)?.value || "";
    const format = value("custom_api_format") || value("api_format");
    const model = value("custom_model") || value("model");
    return { adobe: format === "v1/images (AIPAI Adobe)" || model.endsWith("-firefly"), model };
}

// ─── 工具函数 ────────────────────────────────────────────────────────────────

function getConnectedSettingsNode(node) {
    const slot = node.inputs?.find(i => i.name === "info");
    return getLinkedOriginNode(node, slot);
}

function getPlatformFromNode(settingsNode) {
    if (!settingsNode) return "banana-pro";
    const pw = settingsNode.widgets?.find(w => w.name === "platform");
    return pw ? pw.value : "banana-pro";
}

function getEffectiveApiBase(settingsNode) {
    if (!settingsNode) return "";
    const custom = settingsNode.widgets?.find(w => w.name === "custom_api_base")?.value || "";
    const selected = settingsNode.widgets?.find(w => w.name === "api_base")?.value || "";
    return String(custom || selected).trim();
}

function isAipaiaiBase(value) {
    try {
        const text = String(value || "").trim();
        if (!text) return false;
        const url = new URL(text.includes("://") ? text : `https://${text}`);
        const host = url.hostname.toLowerCase().replace(/\.$/, "");
        return host === "aipaiai.cn" || host.endsWith(".aipaiai.cn");
    } catch {
        return false;
    }
}

function installBottomSpacer(node) {
    if (!node?.widgets) return;

    let spacer = node.widgets.find(w => w.name === BOTTOM_SPACER_NAME);
    if (!spacer) {
        spacer = {
            name: BOTTOM_SPACER_NAME,
            type: "custom",
            value: "",
            serialize: false,
            computeSize: () => [0, BOTTOM_SPACER_HEIGHT],
            draw: () => {},
        };
        node.widgets.push(spacer);
    } else {
        spacer.hidden = false;
        spacer.serialize = false;
        spacer.computeSize = () => [0, BOTTOM_SPACER_HEIGHT];
        spacer.draw = () => {};
    }

    const index = node.widgets.indexOf(spacer);
    if (index !== node.widgets.length - 1) {
        node.widgets.splice(index, 1);
        node.widgets.push(spacer);
    }
}

function clearControlAfterGenerateTooltip(node) {
    if (!node?.widgets) return;
    for (const widget of node.widgets) {
        if (widget.name !== "control_after_generate") continue;
        widget.tooltip = "";
        if (widget.element) widget.element.title = "";
        if (widget.inputEl) widget.inputEl.title = "";
    }
}

function refreshNaturalSize(node) {
    if (typeof node.computeSize === "function" && Array.isArray(node.size)) {
        requestAnimationFrame(() => {
            const [width, height] = node.computeSize();
            const targetWidth = Math.max(node.size[0], width, MIN_WIDTH);
            const targetHeight = height;
            if (node.size[0] !== targetWidth || node.size[1] !== targetHeight) {
                node.setSize([targetWidth, targetHeight]);
                node.setDirtyCanvas(true, true);
            }
        });
    }
}

// ─── 刷新 combo widget DOM ───────────────────────────────────────────────────

function rebuildSelectOptions(el, values, currentValue) {
    if (!el || el.tagName !== "SELECT") return;
    el.options.length = 0;
    for (const v of values) {
        const opt = document.createElement("option");
        opt.value = v;
        opt.textContent = v;
        el.appendChild(opt);
    }
    if (values.includes(currentValue)) {
        el.value = currentValue;
    } else if (values.length > 0) {
        el.value = values[0];
    }
}

function refreshComboWidget(node, widgetName) {
    const w = node.widgets?.find(w => w.name === widgetName);
    if (!w) return;
    const el = w.inputEl;
    if (!el) return;
    if (el.tagName === "SELECT") {
        rebuildSelectOptions(el, w.options?.values || [], w.value);
    }
    if (el.__vue__) {
        el.__vue__.requestUpdate?.();
        el.__vue__.proxy?.$forceUpdate?.();
    }
    node.setDirtyCanvas(true, true);
}

// ─── 平台切换同步 ────────────────────────────────────────────────────────────

function syncWithPlatform(node, settingsNode, preserveValues = true) {
    if (!node.widgets) return;

    const platform = getPlatformFromNode(settingsNode);
    const isGptImage2 = ["gpt-image2", "gpt-image2.5"].includes(platform);
    const isAipaiai = isGptImage2 && isAipaiaiBase(getEffectiveApiBase(settingsNode));

    const { adobe, model } = getAdobeProfile(settingsNode);
    const adobeRatios = model === "gpt-image-2.5-sunburst-firefly"
        ? [...AIPAI_ADOBE_RATIOS, "3:1"] : AIPAI_ADOBE_RATIOS;

    // ratio
    const ratioW = node.widgets.find(w => w.name === "ratio");
    if (ratioW) {
        const values = isAipaiai
            ? (adobe ? adobeRatios : AIPAI_IMAGE_RATIOS)
            : (IMAGE_RATIOS_BY_PLATFORM[platform] || IMAGE_RATIOS_BASE);
        ratioW.options.values = values;
        if (preserveValues && !values.includes(ratioW.value)) {
            ratioW.value = values.includes("auto") ? "auto" : values[0];
        }
        refreshComboWidget(node, "ratio");
    }

    // size
    const sizeW = node.widgets.find(w => w.name === "size");
    if (sizeW) {
        const values = isGptImage2 ? GPT_IMAGE2_SIZES : ["1K", "2K", "4K"];
        sizeW.options.values = values;
        if (preserveValues && !values.includes(sizeW.value)) {
            sizeW.value = "2K";
        }
        refreshComboWidget(node, "size");
    }

    // quality / moderation（仅 gpt-image2 可见）
    for (const name of ["quality", "moderation"]) {
        const w = node.widgets.find(w => w.name === name);
        if (!w) continue;
        if (isGptImage2 && (!isAipaiai || (adobe && name === "quality"))) {
            showWidget(w);
        } else {
            hideWidget(w);
        }
    }

    refreshNaturalSize(node);
    node.setDirtyCanvas(true, true);
}

// ─── Extension 注册 ──────────────────────────────────────────────────────────

app.registerExtension({
    name: "LingxiBridge.ImageGenerator",

    async nodeCreated(node) {
        if (node.comfyClass !== "LingxiBridgeImage") return;

        await new Promise(r => setTimeout(r, 100));

        installBottomSpacer(node);
        clearControlAfterGenerateTooltip(node);

        // 初始化：根据当前连接的平台状态同步 widget 显隐
        const settingsNode = getConnectedSettingsNode(node);
        syncWithPlatform(node, settingsNode, true);

        // 隐藏 format widget（Python INPUT_TYPES 有，但前端不需要用户操作）
        const formatW = node.widgets?.find(w => w.name === "format");
        if (formatW && !isWidgetHidden(formatW)) {
            hideWidget(formatW);
            refreshNaturalSize(node);
        }

        // ── 轮询：检测 platform 值变化 & settings 连线变化 ──
        node._lx_lastPlatform = null;
        const intervalId = setInterval(() => {
            if (!node.widgets) {
                clearInterval(intervalId);
                return;
            }

            const curSettings = getConnectedSettingsNode(node);
            const curPlatform = getPlatformFromNode(curSettings);
            const curProfile = `${curPlatform}|${getEffectiveApiBase(curSettings)}|${JSON.stringify(getAdobeProfile(curSettings))}`;

            const settingsChanged = curSettings !== node._lx_lastSettingsNode;
            const platformChanged = curProfile !== node._lx_lastPlatform;
            if (settingsChanged || platformChanged) {
                node._lx_lastSettingsNode = curSettings;
                node._lx_lastPlatform = curProfile;
                syncWithPlatform(node, curSettings, true);
            }
        }, 200);

        node._lx_intervalId = intervalId;

        const origOnRemoved = node.onRemoved;
        node.onRemoved = function () {
            clearInterval(node._lx_intervalId);
            if (origOnRemoved) origOnRemoved.call(this);
        };
    },
});
