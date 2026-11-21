import { app } from "../../../../scripts/app.js";
import { api } from "../../../../scripts/api.js";
import { modelMatchesPlatform } from "./shared.js";

const MASK_TEXT = "********";

function maskKey(value) {
    const key = String(value || "").trim();
    if (!key) return "";
    if (key.length <= 8) return key;
    return key.slice(0, 4) + MASK_TEXT + key.slice(-4);
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

async function loadCatalog(baseUrl) {
    try {
        const resp = await api.fetchApi(`/relayapi/catalog?base_url=${encodeURIComponent(baseUrl)}`);
        if (!resp.ok) return null;
        return await resp.json();
    } catch (e) {
        console.warn("[LingxiBridge] loadCatalog", e);
        return null;
    }
}

function syncSelectWidget(widget, labels = null) {
    const values = widget.options?.values || [];
    const el = widget.inputEl;
    if (el && el.tagName === "SELECT") {
        el.options.length = 0;
        for (const value of values) {
            const opt = document.createElement("option");
            opt.value = value;
            opt.textContent = value && labels?.[value] ? `${value} [${labels[value]}]` : value;
            el.appendChild(opt);
        }
        el.value = values.includes(widget.value) ? widget.value : (values[0] || "");
    }
}

function formatsForPlatform(platform, catalogData) {
    const formats = catalogData?.formats || [];
    const fm = catalogData?.format_models || {};
    if (!formats.length) return [];

    const matched = formats.filter((fmt) => {
        const models = fm[fmt] || [];
        return models.some((model) => modelMatchesPlatform(model, platform));
    });
    return matched.length ? matched : formats;
}

function modelsForFormat(platform, apiFormat, catalogData) {
    const allModels = (catalogData?.format_models || {})[apiFormat] || [];
    const matched = allModels.filter((model) => modelMatchesPlatform(model, platform));
    return platform === "gpt-image2.5" ? matched : (matched.length ? matched : allModels);
}

function refreshModels(platform, apiFormat, model, catalogData) {
    if (!catalogData) return;
    const plat = platform.value || "banana-pro";
    const values = modelsForFormat(plat, apiFormat.value || "", catalogData);

    model.options.values = values;
    if (!values.includes(model.value)) {
        model.value = values[0] || "";
    }
    syncSelectWidget(model, catalogData.model_labels || {});
    app.graph.setDirtyCanvas(true);
}

function refreshFormats(platform, apiFormat, model, catalogData) {
    if (!catalogData || !Array.isArray(catalogData.formats) || catalogData.formats.length === 0) return;

    const plat = platform.value || "banana-pro";
    const allowed = formatsForPlatform(plat, catalogData);
    const prevValue = apiFormat.value;
    apiFormat.options.values = allowed;
    if (!allowed.includes(prevValue)) {
        apiFormat.value = allowed[0] || "";
    }

    syncSelectWidget(apiFormat);
    refreshModels(platform, apiFormat, model, catalogData);
}

function installApiKeyMask(node, apikey) {
    if (!apikey || apikey.__lxRelayApiKeyMasked) return;
    apikey.__lxRelayApiKeyMasked = true;

    if (apikey.inputEl) {
        apikey.inputEl.type = "text";
        apikey.inputEl.autocomplete = "off";
        apikey.inputEl.spellcheck = false;
    }

    const originalCallback = apikey.callback;
    apikey.callback = function (value) {
        const text = String(value || "").trim();
        apikey.value = text;
        node.setDirtyCanvas(true, true);
        if (originalCallback) return originalCallback.call(this, text);
        return text;
    };

    const originalDraw = apikey.draw;
    apikey.draw = function (ctx, drawNode, width, y, height) {
        if (originalDraw) {
            const realValue = apikey.value;
            apikey.value = maskKey(realValue);
            try {
                return originalDraw.call(this, ctx, drawNode, width, y, height);
            } finally {
                apikey.value = realValue;
            }
        }
        return drawMaskedWidget(apikey, ctx, drawNode, width, y, height);
    };

    apikey.serializeValue = () => String(apikey.value || "").trim();
}

app.registerExtension({
    name: "LingxiBridge.Settings",

    async nodeCreated(node) {
        if (node.comfyClass !== "LingxiBridgeSettings") return;

        await new Promise((resolve) => setTimeout(resolve, 100));

        const w = {};
        for (const widget of node.widgets || []) {
            w[widget.name] = widget;
        }

        const {
            platform,
            api_base,
            api_format,
            model,
            apikey,
            custom_api_base,
            custom_api_format,
            custom_model,
        } = w;
        if (!platform || !api_base || !api_format || !model) return;

        let catalogData = null;
        let catalogBase = null;
        let requestVersion = 0;
        if (apikey) installApiKeyMask(node, apikey);

        async function refreshCatalog() {
            const base = String(custom_api_base?.value || api_base.value || "").trim();
            if (base !== catalogBase) {
                catalogBase = base;
                catalogData = null;
                const version = ++requestVersion;
                const data = await loadCatalog(base);
                if (version !== requestVersion) return;
                if (!data) { catalogBase = null; return; }
                catalogData = data;
            }
            refreshFormats(platform, api_format, model, catalogData);
        }

        for (const widget of [platform, api_base, api_format, custom_api_base]) {
            if (!widget) continue;
            const original = widget.callback;
            widget.callback = function (value) {
                widget.value = value;
                original?.call(this, value);
                return refreshCatalog();
            };
        }
        let lastProfile = "";
        const interval = setInterval(() => {
            const profile = JSON.stringify([platform.value, api_base.value, custom_api_base?.value, api_format.value]);
            if (profile === lastProfile) return;
            lastProfile = profile;
            refreshCatalog();
        }, 250);
        const onRemoved = node.onRemoved;
        node.onRemoved = function () {
            clearInterval(interval);
            requestVersion++;
            onRemoved?.apply(this, arguments);
        };
        await refreshCatalog();
    },
});
