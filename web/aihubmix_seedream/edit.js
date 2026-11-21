import { app } from "../../../../scripts/app.js";

const MASK_TEXT = "********";

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

function installApiKeyMask(node) {
    if (node.__aihubmixSeedreamMasked) return;
    const apikey = (node.widgets || []).find((widget) => widget.name === "apikey");
    if (!apikey) return;

    node.__aihubmixSeedreamMasked = true;
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
    name: "AIHUBMIX.Seedream.Edit",

    async nodeCreated(node) {
        if (node.comfyClass !== "AIHubmixSeedreamEdit") return;
        await new Promise((resolve) => setTimeout(resolve, 100));
        installApiKeyMask(node);
    },
});
