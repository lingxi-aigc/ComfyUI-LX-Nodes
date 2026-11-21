import { app } from "../../../../scripts/app.js";

const NODE_NAME = "LXBooguImageEdit";
const IMAGE_COUNT_WIDGET = "image_count";
const BOTTOM_SPACER_NAME = "__lx_boogu_image_edit_bottom_spacer";
const BOTTOM_SPACER_HEIGHT = 5;
const HOLLOW_CIRCLE_SHAPE = () =>
    globalThis.LiteGraph?.HOLLOW_CIRCLE_SHAPE ?? globalThis.LiteGraph?.HollowCircle ?? 7;
const FIXED_INPUT_ORDER = [
    { name: "clip", type: "CLIP" },
    { name: "vae", type: "VAE" },
    { name: "image1", type: "IMAGE" },
];

function parseImageCount(value) {
    const match = String(value ?? "").match(/\d+/);
    if (!match) return 1;
    return Math.max(1, Math.min(3, Number.parseInt(match[0], 10)));
}

function getImageCount(node) {
    const widget = (node.widgets || []).find((item) => item?.name === IMAGE_COUNT_WIDGET);
    return parseImageCount(widget?.value);
}

function findInputIndex(node, name) {
    return (node.inputs || []).findIndex((input) => input?.name === name);
}

function findInput(node, name) {
    return (node.inputs || []).find((input) => input?.name === name);
}

function removeInputByName(node, name) {
    const index = findInputIndex(node, name);
    if (index >= 0) {
        node.removeInput(index);
        return true;
    }
    return false;
}

function applyOptionalInputShape(input) {
    if (!input) return false;
    let changed = false;
    const shape = HOLLOW_CIRCLE_SHAPE();
    if (input.shape !== shape) {
        input.shape = shape;
        changed = true;
    }
    if (input.optional !== true) {
        input.optional = true;
        changed = true;
    }
    return changed;
}

function ensureInput(node, name, type, options = {}) {
    const existingInput = findInput(node, name);
    if (existingInput) {
        return options.optional ? applyOptionalInputShape(existingInput) : false;
    }

    const extraInfo = options.optional ? { shape: HOLLOW_CIRCLE_SHAPE(), optional: true } : undefined;
    node.addInput(name, type, extraInfo);
    return true;
}

function ensureBottomSpacer(node) {
    node.widgets = node.widgets || [];
    let spacer = node.widgets.find((widget) => widget?.name === BOTTOM_SPACER_NAME);

    if (!spacer) {
        spacer = {
            name: BOTTOM_SPACER_NAME,
            type: "custom",
            value: "",
            serialize: false,
            options: { canvasOnly: true },
            computeSize: () => [0, BOTTOM_SPACER_HEIGHT],
            draw: () => {},
        };
        node.widgets.push(spacer);
    } else {
        spacer.hidden = false;
        spacer.type = "custom";
        spacer.value = "";
        spacer.serialize = false;
        spacer.options = { ...(spacer.options || {}), canvasOnly: true };
        spacer.computeSize = () => [0, BOTTOM_SPACER_HEIGHT];
        spacer.draw = () => {};
    }

    const index = node.widgets.indexOf(spacer);
    if (index !== node.widgets.length - 1) {
        node.widgets.splice(index, 1);
        node.widgets.push(spacer);
    }
}

function refreshSize(node) {
    if (!node || typeof node.computeSize !== "function" || typeof node.setSize !== "function") return;
    ensureBottomSpacer(node);
    const size = node.computeSize();
    if (!Array.isArray(size)) return;
    node.setSize([
        Math.max(node.size?.[0] || 0, size[0]),
        Math.max(node.size?.[1] || 0, size[1]),
    ]);
    node.setDirtyCanvas?.(true, true);
    app.graph?.setDirtyCanvas(true, true);
}

function syncImageInputs(node) {
    if (!node?.inputs) return;
    const imageCount = getImageCount(node);
    let changed = false;

    for (const input of FIXED_INPUT_ORDER) {
        changed = ensureInput(node, input.name, input.type) || changed;
    }

    for (let index = 3; index > imageCount; index -= 1) {
        changed = removeInputByName(node, `image${index}`) || changed;
    }

    for (let index = 2; index <= imageCount; index += 1) {
        changed = ensureInput(node, `image${index}`, "IMAGE", { optional: true }) || changed;
    }

    if (changed) {
        refreshSize(node);
        requestAnimationFrame(() => refreshSize(node));
    }
}

function hookImageCountWidget(node) {
    const widget = (node.widgets || []).find((item) => item?.name === IMAGE_COUNT_WIDGET);
    if (!widget || widget.__lxBooguImageEditHooked) return;
    widget.__lxBooguImageEditHooked = true;

    const originalCallback = widget.callback;
    widget.callback = function () {
        const result = originalCallback?.apply(this, arguments);
        syncImageInputs(node);
        return result;
    };
}

function install(node) {
    ensureBottomSpacer(node);
    hookImageCountWidget(node);
    syncImageInputs(node);
    refreshSize(node);
    requestAnimationFrame(() => {
        syncImageInputs(node);
        refreshSize(node);
    });
    window.setTimeout(() => {
        syncImageInputs(node);
        refreshSize(node);
    }, 150);

    if (!node.__lxBooguImageEditDrawHooked) {
        node.__lxBooguImageEditDrawHooked = true;
        const onDrawForeground = node.onDrawForeground;
        node.onDrawForeground = function () {
            const result = onDrawForeground?.apply(this, arguments);
            const imageCount = getImageCount(this);
            if (this.__lxBooguImageEditLastImageCount !== imageCount) {
                this.__lxBooguImageEditLastImageCount = imageCount;
                syncImageInputs(this);
            }
            return result;
        };
    }
}

app.registerExtension({
    name: "LX.ImageEdit.Boogu",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            install(this);
            return result;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = onConfigure?.apply(this, arguments);
            install(this);
            return result;
        };
    },

    async nodeCreated(node) {
        if (node?.comfyClass === NODE_NAME || node?.type === NODE_NAME) {
            install(node);
        }
    },
});
