import { app } from "../../../../scripts/app.js";
import { api } from "../../../../scripts/api.js";
import { ComfyWidgets } from "../../../../scripts/widgets.js";

const NODE_NAME = "LXQwenTextGenerate";
const PROGRESS_EVENT = "lx-qwen-text-progress";
const PROGRESS_WIDGET_NAME = "__lx_qwen_text_progress";
const LIVE_PREVIEW_WIDGET_NAME = "__lx_qwen_live_preview";
const IDLE_PROGRESS_HEIGHT = 5;
const PROGRESS_WIDGET_HEIGHT = 58;
const PROGRESS_PANEL_MIN_HEIGHT = 42;
const PROGRESS_PANEL_PADDING_Y = 8;
const MASK_TEXT = "********";
const TEXT_DISPLAY_NODE_CLASSES = new Set([
    "ShowText|pysssss",
    "LXShowText",
    "LXShowAny",
]);
const progressByNode = new Map();
let progressListenerInstalled = false;
let progressTimer = null;

function maskKey(value) {
    const key = String(value || "").trim();
    if (!key) return "";
    if (key.length <= 8) return key;
    return `${key.slice(0, 4)}${MASK_TEXT}${key.slice(-4)}`;
}

function fitString(ctx, text, maxWidth) {
    const value = String(text || "");
    if (ctx.measureText(value).width <= maxWidth) return value;
    const ellipsis = "...";
    let result = value;
    while (result.length > 0 && ctx.measureText(result + ellipsis).width > maxWidth) {
        result = result.slice(0, -1);
    }
    return result ? result + ellipsis : ellipsis;
}

function wrapTextLines(ctx, text, maxWidth, maxLines) {
    const source = String(text || "").replace(/\s+/g, " ").trim();
    if (!source || maxWidth <= 0 || maxLines <= 0) return [];

    const lines = [];
    let current = "";

    for (const char of source) {
        const candidate = current + char;
        if (!current || ctx.measureText(candidate).width <= maxWidth) {
            current = candidate;
            continue;
        }

        lines.push(current);
        current = char;
        if (lines.length >= maxLines) break;
    }

    if (lines.length < maxLines && current) {
        lines.push(current);
    }

    if (lines.length > 0 && ctx.measureText(lines[lines.length - 1]).width > maxWidth) {
        lines[lines.length - 1] = fitString(ctx, lines[lines.length - 1], maxWidth);
    }

    if (source.length > lines.join("").length && lines.length > 0) {
        lines[lines.length - 1] = fitString(ctx, `${lines[lines.length - 1]}...`, maxWidth);
    }

    return lines;
}

function drawMaskedWidget(widget, ctx, node, width, y, height) {
    const h = height || LiteGraph.NODE_WIDGET_HEIGHT;
    const margin = 15;
    const inner = 10;
    const midY = y + h / 2;
    const label = widget.name || "api_key";
    const masked = maskKey(widget.value);

    ctx.save();
    ctx.strokeStyle = LiteGraph.WIDGET_OUTLINE_COLOR;
    ctx.fillStyle = LiteGraph.WIDGET_BGCOLOR;
    ctx.beginPath();
    ctx.roundRect(margin, y, width - margin * 2, h, [h * 0.5]);
    ctx.fill();
    ctx.stroke();

    ctx.textBaseline = "middle";
    ctx.textAlign = "left";
    ctx.fillStyle = LiteGraph.WIDGET_SECONDARY_TEXT_COLOR;
    ctx.fillText(label, margin + inner, midY);

    const labelWidth = ctx.measureText(label).width;
    const valueX = width - margin - inner;
    const maxValueWidth = Math.max(20, valueX - (margin + inner + labelWidth + 10));
    ctx.textAlign = "right";
    ctx.fillStyle = LiteGraph.WIDGET_TEXT_COLOR;
    ctx.fillText(fitString(ctx, masked, maxValueWidth), valueX, midY);
    ctx.restore();
}

function refreshNaturalSize(node) {
    if (!node || typeof node.computeSize !== "function" || !Array.isArray(node.size)) return;
    requestAnimationFrame(() => {
        const [width, height] = node.computeSize();
        if (node.size[0] !== width || node.size[1] !== height) {
            node.setSize([Math.max(node.size[0], width), height]);
            node.setDirtyCanvas(true, true);
        }
    });
}

function normalizeNodeId(value) {
    return String(value ?? "").trim();
}

function getProgressState(node) {
    return progressByNode.get(normalizeNodeId(node?.id));
}

function findGraphNode(nodeId) {
    const targetId = normalizeNodeId(nodeId);
    if (!targetId) return null;
    const nodes = app.graph?._nodes || app.graph?.nodes || [];
    return nodes.find((node) => normalizeNodeId(node?.id) === targetId) || null;
}

function getGraphNode(nodeId) {
    return app.graph?.getNodeById?.(nodeId) || findGraphNode(nodeId);
}

function getGraphLink(linkId) {
    const links = app.graph?.links;
    if (!links) return null;
    if (Array.isArray(links)) {
        return links.find((link) => normalizeNodeId(link?.id) === normalizeNodeId(linkId)) || null;
    }
    return links[linkId] || links[normalizeNodeId(linkId)] || null;
}

function isTextDisplayNode(node) {
    const comfyClass = String(node?.comfyClass || "");
    if (TEXT_DISPLAY_NODE_CLASSES.has(comfyClass)) return true;

    const text = `${comfyClass} ${node?.type || ""} ${node?.title || ""}`.toLowerCase();
    return (
        text.includes("showtext")
        || text.includes("show text")
        || text.includes("show any")
        || text.includes("显示文本")
        || text.includes("展示文本")
    );
}

function getDownstreamTextNodes(sourceNode) {
    const result = [];
    const seen = new Set();
    for (const output of sourceNode?.outputs || []) {
        for (const linkId of output?.links || []) {
            const link = getGraphLink(linkId);
            const targetId = link?.target_id ?? link?.targetId;
            const target = getGraphNode(targetId);
            if (!target || seen.has(target.id) || !isTextDisplayNode(target)) continue;
            seen.add(target.id);
            result.push(target);
        }
    }
    return result;
}

function findLivePreviewWidget(node) {
    const widgets = node?.widgets || [];
    return widgets.find((widget) => widget.__lxQwenTextLivePreview)
        || widgets.find((widget) => widget.name === LIVE_PREVIEW_WIDGET_NAME)
        || widgets.find((widget) => /^text_\d+$/.test(String(widget.name || "")))
        || widgets.find((widget) => ["text", "文本", "result", "output", "displaytext"].includes(String(widget.name || "")))
        || widgets.find((widget) => typeof widget.value === "string" && widget.inputEl);
}

function ensureLivePreviewWidget(node) {
    if (!node) return null;
    let widget = findLivePreviewWidget(node);
    if (!widget && ComfyWidgets?.STRING) {
        widget = ComfyWidgets.STRING(
            node,
            LIVE_PREVIEW_WIDGET_NAME,
            ["STRING", { multiline: true }],
            app,
        )?.widget;
    }
    if (!widget) return null;

    widget.__lxQwenTextLivePreview = true;
    widget.serialize = false;
    if (widget.inputEl) {
        widget.inputEl.readOnly = true;
        widget.inputEl.style.opacity = 0.72;
    }
    return widget;
}

function setWidgetValue(widget, value) {
    const text = String(value || "");
    widget.value = text;
    if (widget.inputEl) widget.inputEl.value = text;
    try {
        widget.callback?.(text, app.canvas, widget.node, app.canvas?.graph_mouse, {});
    } catch (error) {
        console.debug("[LX] Qwen live preview callback failed", error);
    }
}

function refreshDisplayNode(node) {
    requestAnimationFrame(() => {
        const size = typeof node.computeSize === "function" ? node.computeSize() : node.size;
        if (Array.isArray(size) && typeof node.onResize === "function") {
            node.onResize([
                Math.max(node.size?.[0] || 0, size[0] || 0),
                Math.max(node.size?.[1] || 0, size[1] || 0),
            ]);
        }
        node.setDirtyCanvas?.(true, true);
        app.graph?.setDirtyCanvas(true, true);
    });
}

function updateDownstreamTextPreview(sourceNode, text, status) {
    if (!sourceNode || !text || !["streaming", "done", "cache", "cancelled"].includes(status)) return;
    for (const target of getDownstreamTextNodes(sourceNode)) {
        const widget = ensureLivePreviewWidget(target);
        if (!widget) continue;
        setWidgetValue(widget, text);
        refreshDisplayNode(target);
    }
}

function setNodeDirty(node) {
    node?.setDirtyCanvas?.(true, true);
    app.graph?.setDirtyCanvas(true, true);
}

function isActiveProgress(status) {
    return status === "start" || status === "connected" || status === "streaming";
}

function cleanupProgressStates() {
    const now = performance.now();
    let hasActive = false;

    for (const [nodeId, state] of progressByNode.entries()) {
        if (isActiveProgress(state.status)) {
            hasActive = true;
            continue;
        }

        const ttl = state.status === "error" ? 12000 : 5000;
        if (now - state.updatedAt > ttl) {
            progressByNode.delete(nodeId);
            const node = findGraphNode(nodeId);
            setNodeDirty(node);
            refreshNaturalSize(node);
        }
    }

    if (!hasActive && progressTimer) {
        clearInterval(progressTimer);
        progressTimer = null;
    }
}

function ensureProgressTimer() {
    if (progressTimer) return;
    progressTimer = setInterval(() => {
        for (const nodeId of progressByNode.keys()) {
            setNodeDirty(findGraphNode(nodeId));
        }
        cleanupProgressStates();
    }, 500);
}

function updateProgressState(data) {
    const nodeId = normalizeNodeId(data?.node);
    if (!nodeId) return;

    const previous = progressByNode.get(nodeId);
    const now = performance.now();
    const status = String(data.status || "streaming");
    const next = {
        ...previous,
        nodeId,
        status,
        model: String(data.model || previous?.model || ""),
        text: String(data.text || previous?.text || ""),
        chars: Number.isFinite(Number(data.chars)) ? Number(data.chars) : previous?.chars || 0,
        elapsed: Number.isFinite(Number(data.elapsed)) ? Number(data.elapsed) : previous?.elapsed || 0,
        message: String(data.message || ""),
        usage: data.usage || previous?.usage || null,
        startedAt: previous?.startedAt && status !== "start" ? previous.startedAt : now,
        updatedAt: now,
    };

    progressByNode.set(nodeId, next);
    const node = findGraphNode(nodeId);
    updateDownstreamTextPreview(node, next.text, status);
    setNodeDirty(node);
    refreshNaturalSize(node);
    if (isActiveProgress(status)) ensureProgressTimer();
    cleanupProgressStates();
}

function installProgressListener() {
    if (progressListenerInstalled || !api?.addEventListener) return;
    progressListenerInstalled = true;
    api.addEventListener(PROGRESS_EVENT, (event) => {
        updateProgressState(event?.detail || {});
    });
    api.addEventListener("execution_interrupted", (event) => {
        const nodeId = normalizeNodeId(event?.detail?.node_id);
        const previous = progressByNode.get(nodeId);
        if (!previous || !isActiveProgress(previous.status)) return;
        updateProgressState({
            node: nodeId,
            status: "cancelled",
            model: previous.model,
            text: previous.text,
            chars: previous.chars,
            elapsed: progressElapsedSeconds(previous),
            message: "已取消",
        });
    });
}

function progressElapsedSeconds(state) {
    if (!state) return 0;
    if (isActiveProgress(state.status)) {
        return Math.max(0, (performance.now() - state.startedAt) / 1000);
    }
    return Math.max(0, Number(state.elapsed || 0));
}

function progressLabel(state) {
    const elapsed = progressElapsedSeconds(state).toFixed(1);
    const chars = Math.max(0, Number(state.chars || 0));
    if (state.status === "cache") return `命中缓存 · ${chars} 字`;
    if (state.status === "done") return `生成完成 · ${elapsed}s · ${chars} 字`;
    if (state.status === "cancelled") return `已取消 · ${elapsed}s · ${chars} 字`;
    if (state.status === "error") return state.message || "生成失败";
    if (state.status === "start") return `连接中 · ${elapsed}s`;
    if (state.status === "connected") return `已连接，等待首段文本 · ${elapsed}s`;
    return `正在生成 · ${elapsed}s · ${chars} 字`;
}

function progressPreview(state) {
    if (state.status === "error") return String(state.message || "").replace(/^错误：?/, "");
    if (state.status === "done") return "结果已输出";
    if (state.status === "cache") return "使用缓存结果";
    if (state.status === "cancelled") return "任务已中断";
    if (state.status === "start") return "正在建立请求";
    if (state.status === "connected") return "等待模型返回第一段文本";
    return "正文同步到下游显示节点";
}

function progressWidgetHeight(node) {
    const state = getProgressState(node);
    if (!state) return IDLE_PROGRESS_HEIGHT;
    return PROGRESS_WIDGET_HEIGHT;
}

function drawProgressWidget(node, ctx, width, y, height) {
    const state = getProgressState(node);
    if (!state) return;

    const widgetWidth = Number(width || node.size?.[0] || 0);
    if (widgetWidth <= 80) return;

    const margin = 12;
    const widgetHeight = Number(height || progressWidgetHeight(node));
    const panelHeight = Math.max(PROGRESS_PANEL_MIN_HEIGHT, widgetHeight - PROGRESS_PANEL_PADDING_Y * 2);
    const x = margin;
    const top = y + PROGRESS_PANEL_PADDING_Y;
    const w = Math.max(40, widgetWidth - margin * 2);
    const active = isActiveProgress(state.status);
    const error = state.status === "error";
    const cancelled = state.status === "cancelled";

    ctx.save();
    ctx.globalAlpha = active ? 0.96 : 0.9;
    ctx.fillStyle = error
        ? "rgba(96, 35, 35, 0.94)"
        : cancelled
            ? "rgba(58, 51, 45, 0.94)"
            : active
                ? "rgba(36, 48, 62, 0.94)"
                : "rgba(37, 49, 39, 0.92)";
    ctx.strokeStyle = error
        ? "rgba(255, 125, 125, 0.85)"
        : cancelled
            ? "rgba(215, 165, 110, 0.82)"
            : active
                ? "rgba(125, 184, 255, 0.9)"
                : "rgba(130, 220, 145, 0.78)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.roundRect(x, top, w, panelHeight, 8);
    ctx.fill();
    ctx.stroke();

    if (active) {
        const pulse = 0.45 + Math.sin(performance.now() / 180) * 0.25;
        ctx.fillStyle = `rgba(125, 184, 255, ${pulse})`;
        ctx.beginPath();
        ctx.arc(x + 16, top + 16, 4, 0, Math.PI * 2);
        ctx.fill();
    }

    const label = progressLabel(state);
    const preview = progressPreview(state);
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.font = "12px Arial";
    ctx.fillStyle = error ? "#ffd8d8" : "#eef5ff";
    ctx.fillText(fitString(ctx, label, w - 34), x + 26, top + 15);

    if (preview) {
        ctx.font = "11px Arial";
        ctx.fillStyle = error ? "#ffb9b9" : cancelled ? "#dec5a6" : "#b9c6d5";
        ctx.fillText(fitString(ctx, preview, w - 24), x + 12, top + 33);
    }
    ctx.restore();
}

function installProgressWidget(node) {
    if (!node?.widgets) return;
    let widget = node.widgets.find((w) => w.name === PROGRESS_WIDGET_NAME);
    if (!widget) {
        widget = {
            name: PROGRESS_WIDGET_NAME,
            type: "custom",
            value: "",
            serialize: false,
            computeSize: (width) => [width || node.size?.[0] || 0, progressWidgetHeight(node)],
            draw: (ctx, drawNode, width, y, height) => drawProgressWidget(drawNode || node, ctx, width, y, height),
        };
        node.widgets.push(widget);
    } else {
        widget.hidden = false;
        widget.serialize = false;
        widget.computeSize = (width) => [width || node.size?.[0] || 0, progressWidgetHeight(node)];
        widget.draw = (ctx, drawNode, width, y, height) => drawProgressWidget(drawNode || node, ctx, width, y, height);
    }

    const index = node.widgets.indexOf(widget);
    if (index !== node.widgets.length - 1) {
        node.widgets.splice(index, 1);
        node.widgets.push(widget);
    }
    refreshNaturalSize(node);
}

function installApiKeyMask(node) {
    const widget = node.widgets?.find((w) => w.name === "api_key");
    if (!widget || widget.__lxQwenTextMasked) return;
    widget.__lxQwenTextMasked = true;

    if (widget.inputEl) {
        widget.inputEl.type = "text";
        widget.inputEl.autocomplete = "off";
        widget.inputEl.spellcheck = false;
    }

    const originalCallback = widget.callback;
    widget.callback = function (value) {
        const text = String(value || "").trim();
        widget.value = text;
        node.setDirtyCanvas(true, true);
        if (originalCallback) return originalCallback.call(this, text);
        return text;
    };

    const originalDraw = widget.draw;
    widget.draw = function (ctx, drawNode, width, y, height) {
        if (originalDraw) {
            const realValue = widget.value;
            widget.value = maskKey(realValue);
            try {
                return originalDraw.call(this, ctx, drawNode, width, y, height);
            } finally {
                widget.value = realValue;
            }
        }
        return drawMaskedWidget(widget, ctx, drawNode, width, y, height);
    };

    widget.serializeValue = () => String(widget.value || "").trim();
}

app.registerExtension({
    name: "LX.QwenTextGenerate.ApiKeyMask",

    setup() {
        installProgressListener();
    },

    async nodeCreated(node) {
        if (node.comfyClass !== NODE_NAME) return;
        await new Promise((resolve) => setTimeout(resolve, 80));
        installApiKeyMask(node);
        installProgressWidget(node);
    },
});
