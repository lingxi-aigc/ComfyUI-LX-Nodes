import { app } from "../../../../scripts/app.js";
import { api } from "../../../../scripts/api.js";
import { modelMatchesPlatform } from "../lingxi_bridge/shared.js";

const API_KEY_WIDGET_NAMES = ["apikey1", "apikey2", "apikey3", "apikey4"];
const MASK_TEXT = "********";

let catalogCache = {};

async function fetchCatalog(baseUrl) {
    const key = baseUrl || "";
    if (catalogCache[key]) return catalogCache[key];
    const resp = await api.fetchApi(`/relayapi/catalog?base_url=${encodeURIComponent(key)}`);
    if (!resp.ok) return {};
    const data = await resp.json();
    catalogCache[key] = data;
    return data;
}

function widgetMap(node) {
    const map = {};
    for (const widget of node.widgets || []) {
        map[widget.name] = widget;
    }
    return map;
}

function syncSelect(widget) {
    const el = widget?.inputEl;
    if (!el || el.tagName !== "SELECT") return;
    const values = widget.options?.values || [];
    el.options.length = 0;
    for (const value of values) {
        const opt = document.createElement("option");
        opt.value = value;
        opt.textContent = value;
        el.appendChild(opt);
    }
    el.value = widget.value;
}

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

function drawMaskedWidget(widget, ctx, node, width, y, height) {
    const h = height || LiteGraph.NODE_WIDGET_HEIGHT;
    const margin = 15;
    const inner = 10;
    const midY = y + h / 2;
    const label = widget.name || "apikey";
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

function formatsForPlatform(platform, catalog) {
    const formats = catalog?.formats || [];
    const formatModels = catalog?.format_models || {};
    const matched = formats.filter((format) => {
        const models = formatModels[format] || [];
        return models.some((model) => modelMatchesPlatform(model, platform));
    });
    return matched.length ? matched : formats;
}

function modelsForPlatformFormat(platform, apiFormat, catalog) {
    const models = (catalog?.format_models || {})[apiFormat] || [];
    const matched = models.filter((model) => modelMatchesPlatform(model, platform));
    return platform === "gpt-image2.5" ? matched : (matched.length ? matched : models);
}

async function refreshNode(node) {
    const w = widgetMap(node);
    const platform = w.platform?.value || "banana-pro";
    const base = w.api_base?.value || "";
    if (!w.api_format || !w.model) return;
    const catalog = await fetchCatalog(base);

    const formats = formatsForPlatform(platform, catalog);
    if (formats.length) {
        w.api_format.options.values = formats;
        if (!formats.includes(w.api_format.value)) {
            w.api_format.value = formats[0];
        }
        syncSelect(w.api_format);
    }

    const models = modelsForPlatformFormat(platform, w.api_format.value, catalog);
    if (models.length || platform === "gpt-image2.5") {
        w.model.options.values = models;
        if (!models.includes(w.model.value)) {
            w.model.value = models[0] || "";
        }
        syncSelect(w.model);
    }
    node.setDirtyCanvas(true, true);
}

function installApiKeyMask(node) {
    const widgets = widgetMap(node);
    const keyWidgets = API_KEY_WIDGET_NAMES.map((name) => widgets[name]).filter(Boolean);
    if (!keyWidgets.length || node.__lxApiPoolMasked) return;
    node.__lxApiPoolMasked = true;

    for (const widget of keyWidgets) {
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
            if (originalCallback) {
                return originalCallback.call(this, text);
            }
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
}

app.registerExtension({
    name: "LingxiBridge.Concurrent.ApiPool",

    async nodeCreated(node) {
        if (node.comfyClass !== "LingxiBridgeApiPool") return;
        await new Promise((resolve) => setTimeout(resolve, 100));

        const w = widgetMap(node);
        for (const name of ["platform", "api_base", "api_format"]) {
            const widget = w[name];
            if (!widget) continue;
            const original = widget.callback;
            widget.callback = async function (value) {
                if (original) original.call(this, value);
                await refreshNode(node);
            };
        }
        installApiKeyMask(node);
        await refreshNode(node);
    },
});
