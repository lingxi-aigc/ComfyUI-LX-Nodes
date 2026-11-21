import { app } from "../../../../scripts/app.js";

const BOTTOM_SPACER_NAME = "__lx_qwen3vl_bottom_spacer";
const BOTTOM_SPACER_HEIGHT = 5;
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

function installBottomSpacer(node) {
    if (!node?.widgets) return;
    let spacer = node.widgets.find((w) => w.name === BOTTOM_SPACER_NAME);
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
    refreshNaturalSize(node);
}

function installApiKeyMask(node) {
    const widget = node.widgets?.find((w) => w.name === "api_key");
    if (!widget || widget.__lxQwen3VLMasked) return;
    widget.__lxQwen3VLMasked = true;

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
    name: "LX.Qwen3VLReverse.ApiKeyMask",

    async nodeCreated(node) {
        if (node.comfyClass !== "LXQwen3VLReverse") return;
        await new Promise((resolve) => setTimeout(resolve, 80));
        installApiKeyMask(node);
        installBottomSpacer(node);
    },
});
