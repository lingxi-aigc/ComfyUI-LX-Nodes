import { app } from "../../../../scripts/app.js";
import {
    GPT_IMAGE2_SIZES,
    IMAGE_RATIOS_BASE,
    IMAGE_RATIOS_BY_PLATFORM,
    hideWidget,
    isWidgetHidden,
    showWidget,
} from "../lingxi_bridge/shared.js";

const TASK_NODE = "LingxiImageTask";
const SPLIT_NODE = "LingxiResultSplit";
const TASK_BOTTOM_SPACER_NAME = "__lx_lingxi_task_bottom_spacer";
const TASK_BOTTOM_SPACER_HEIGHT = 5;
const SPLIT_COUNT_WIDGET = "拆分数量";
const SPLIT_COUNT_PROPERTY = "lx_result_split_count";
const MAX_SPLIT_OUTPUTS = 32;
const DEFAULT_SPLIT_OUTPUTS = 8;
const AIPAI_IMAGE_RATIOS = ["auto", "1:1", "3:2", "2:3", "16:9", "9:16", "4:3", "3:4", "5:4", "4:5", "21:9"];

function normalizeTaskWidgetValues(info) {
    const values = info?.widgets_values;
    if (!Array.isArray(values) || values.length < 8) return;
    if (typeof values[0] !== "boolean") return;

    // Legacy order: 启用, prompt, ratio, size, quality, moderation, 重新生成, 任务名称.
    info.widgets_values = values.slice(1, 7).concat(values.slice(8));
}

function findWidget(node, name) {
    return (node.widgets || []).find((widget) => widget.name === name);
}

function ensureTaskBottomSpacer(node) {
    if (!node?.widgets) return;
    let spacer = node.widgets.find((widget) => widget?.name === TASK_BOTTOM_SPACER_NAME);

    if (!spacer) {
        spacer = {
            name: TASK_BOTTOM_SPACER_NAME,
            type: "custom",
            value: "",
            serialize: false,
            options: { canvasOnly: true },
            computeSize: () => [0, TASK_BOTTOM_SPACER_HEIGHT],
            draw: () => {},
        };
        node.widgets.push(spacer);
    } else {
        spacer.hidden = false;
        spacer.type = "custom";
        spacer.value = "";
        spacer.serialize = false;
        spacer.options = { ...(spacer.options || {}), canvasOnly: true };
        spacer.computeSize = () => [0, TASK_BOTTOM_SPACER_HEIGHT];
        spacer.draw = () => {};
    }

    const index = node.widgets.indexOf(spacer);
    if (index !== node.widgets.length - 1) {
        node.widgets.splice(index, 1);
        node.widgets.push(spacer);
    }
}

function linkedNode(node, inputName) {
    const input = node.inputs?.find((item) => item.name === inputName);
    if (input?.link == null) return null;
    const graph = node.graph || app.graph;
    const link = graph.links[input.link];
    return link ? graph.getNodeById(link.origin_id) : null;
}

function apiProfile(node) {
    return JSON.stringify(["platform", "api_base", "custom_api_base", "api_format",
        "custom_api_format", "model", "custom_model"].map(name =>
        node?.widgets?.find(widget => widget.name === name)?.value || ""));
}

function platformFromNode(node) {
    if (!node) return null;
    const widget = node.widgets?.find((item) => item.name === "platform");
    return widget?.value || null;
}

function effectiveApiBaseFromNode(node) {
    if (!node) return "";
    const custom = node.widgets?.find((item) => item.name === "custom_api_base")?.value || "";
    const selected = node.widgets?.find((item) => item.name === "api_base")?.value || "";
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

function refreshComboWidget(node, widgetName) {
    const widget = node.widgets?.find((item) => item.name === widgetName);
    const el = widget?.inputEl;
    if (!widget || !el || el.tagName !== "SELECT") return;
    const values = widget.options?.values || [];
    el.options.length = 0;
    for (const value of values) {
        const opt = document.createElement("option");
        opt.value = value;
        opt.textContent = value;
        el.appendChild(opt);
    }
    el.value = widget.value;
    node.setDirtyCanvas(true, true);
}

function allRatios() {
    const seen = new Set();
    const result = [];
    for (const ratios of Object.values(IMAGE_RATIOS_BY_PLATFORM)) {
        for (const ratio of ratios || IMAGE_RATIOS_BASE) {
            if (!seen.has(ratio)) {
                seen.add(ratio);
                result.push(ratio);
            }
        }
    }
    return result.length ? result : IMAGE_RATIOS_BASE;
}

function syncTaskNode(node) {
    if (!node.widgets) return;
    ensureTaskBottomSpacer(node);

    const apiNode = linkedNode(node, "本任务API");
    const platform = platformFromNode(apiNode);
    const isAipaiai = ["gpt-image2", "gpt-image2.5"].includes(platform) && isAipaiaiBase(effectiveApiBaseFromNode(apiNode));
    const value = name => apiNode?.widgets?.find(w => w.name === name)?.value || "";
    const model = value("custom_model") || value("model");
    const apiFormat = value("custom_api_format") || value("api_format");
    const adobe = isAipaiai && (apiFormat === "v1/images (AIPAI Adobe)" || model.endsWith("-firefly"));
    let aipaiRatios = AIPAI_IMAGE_RATIOS;
    if (adobe) aipaiRatios = ["auto", "1:1", "5:4", "4:3", "3:2", "16:9", "21:9", "4:5", "3:4", "2:3", "9:16", "1:2", "2:1", "9:21"];
    if (adobe && model === "gpt-image-2.5-sunburst-firefly") aipaiRatios = [...aipaiRatios, "3:1"];
    const ratios = isAipaiai
        ? aipaiRatios
        : (platform ? (IMAGE_RATIOS_BY_PLATFORM[platform] || IMAGE_RATIOS_BASE) : allRatios());
    const hasGptImage2 = !platform || ["gpt-image2", "gpt-image2.5"].includes(platform);

    const ratioWidget = findWidget(node, "ratio");
    if (ratioWidget) {
        ratioWidget.options.values = ratios;
        if (!ratios.includes(ratioWidget.value)) {
            ratioWidget.value = ratios.includes("auto") ? "auto" : ratios[0];
        }
        refreshComboWidget(node, "ratio");
    }

    const sizeWidget = findWidget(node, "size");
    if (sizeWidget) {
        const values = hasGptImage2 ? GPT_IMAGE2_SIZES : ["1K", "2K", "4K"];
        sizeWidget.options.values = values;
        if (!values.includes(sizeWidget.value)) {
            sizeWidget.value = "2K";
        }
        refreshComboWidget(node, "size");
    }

    for (const name of ["quality", "moderation"]) {
        const widget = findWidget(node, name);
        if (!widget) continue;
        if (hasGptImage2 && (!isAipaiai || (adobe && name === "quality"))) {
            showWidget(widget);
        } else if (!isWidgetHidden(widget)) {
            hideWidget(widget);
        }
    }

    if (typeof node.computeSize === "function" && Array.isArray(node.size)) {
        requestAnimationFrame(() => {
            const [width, height] = node.computeSize();
            node.setSize([Math.max(node.size[0], width, 420), height]);
            node.setDirtyCanvas(true, true);
        });
    }
}

function clampSplitCount(value) {
    const count = Number.parseInt(value, 10);
    if (!Number.isFinite(count)) return DEFAULT_SPLIT_OUTPUTS;
    return Math.max(1, Math.min(MAX_SPLIT_OUTPUTS, count));
}

function splitCount(node) {
    const widget = findWidget(node, SPLIT_COUNT_WIDGET);
    const count = clampSplitCount(widget?.value);
    if (widget && widget.value !== count) widget.value = count;
    return count;
}

function markDirty(node) {
    if (node.computeSize) {
        node.setSize(node.computeSize());
    }
    app.graph?.setDirtyCanvas(true, true);
}

function syncSplitOutputs(node) {
    const count = splitCount(node);
    node.properties = node.properties || {};
    node.properties[SPLIT_COUNT_PROPERTY] = count;

    while ((node.outputs || []).length < count) {
        const index = (node.outputs || []).length + 1;
        node.addOutput(`image${index}`, "IMAGE");
    }

    while ((node.outputs || []).length > count) {
        node.removeOutput(node.outputs.length - 1);
    }

    for (let index = 0; index < (node.outputs || []).length; index += 1) {
        node.outputs[index].name = `image${index + 1}`;
        node.outputs[index].type = "IMAGE";
    }

    markDirty(node);
}

function installSplitCountCallback(node) {
    const widget = findWidget(node, SPLIT_COUNT_WIDGET);
    if (!widget || widget.__lx_result_split_callback) return;
    const previous = widget.callback;
    widget.callback = function () {
        const result = previous?.apply(this, arguments);
        syncSplitOutputs(node);
        return result;
    };
    widget.__lx_result_split_callback = true;
}

function deferSplitSync(node) {
    window.setTimeout(() => syncSplitOutputs(node), 0);
}

app.registerExtension({
    name: "Lingxi.TaskQueue",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name === TASK_NODE) {
            const onConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function (info) {
                normalizeTaskWidgetValues(info);
                return onConfigure?.apply(this, arguments);
            };
        }

        if (nodeData.name === SPLIT_NODE) {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                const result = onNodeCreated?.apply(this, arguments);
                installSplitCountCallback(this);
                deferSplitSync(this);
                return result;
            };

            const onConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function (info) {
                const result = onConfigure?.apply(this, arguments);
                const count = clampSplitCount(info?.properties?.[SPLIT_COUNT_PROPERTY] ?? findWidget(this, SPLIT_COUNT_WIDGET)?.value);
                const widget = findWidget(this, SPLIT_COUNT_WIDGET);
                if (widget) widget.value = count;
                installSplitCountCallback(this);
                deferSplitSync(this);
                return result;
            };

            const onWidgetChanged = nodeType.prototype.onWidgetChanged;
            nodeType.prototype.onWidgetChanged = function (name) {
                const result = onWidgetChanged?.apply(this, arguments);
                if (name === SPLIT_COUNT_WIDGET) deferSplitSync(this);
                return result;
            };

            const onSerialize = nodeType.prototype.onSerialize;
            nodeType.prototype.onSerialize = function (data) {
                const result = onSerialize?.apply(this, arguments);
                data.properties = data.properties || {};
                data.properties[SPLIT_COUNT_PROPERTY] = splitCount(this);
                return result;
            };
        }
    },

    async nodeCreated(node) {
        if (node.comfyClass !== TASK_NODE) return;
        await new Promise((resolve) => setTimeout(resolve, 100));
        syncTaskNode(node);

        node._lxTaskLastPlatform = "";
        const intervalId = setInterval(() => {
            if (!node.widgets) {
                clearInterval(intervalId);
                return;
            }
            const apiNode = linkedNode(node, "本任务API");
            const profile = apiProfile(apiNode);
            if (profile !== node._lxTaskLastPlatform) {
                node._lxTaskLastPlatform = profile;
                syncTaskNode(node);
            }
        }, 250);

        node._lxTaskInterval = intervalId;
        const originalOnRemoved = node.onRemoved;
        node.onRemoved = function () {
            clearInterval(node._lxTaskInterval);
            if (originalOnRemoved) originalOnRemoved.call(this);
        };
    },
});
