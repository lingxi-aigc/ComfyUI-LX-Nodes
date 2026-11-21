import { app } from "../../../../scripts/app.js";

const NODE_NAME = "LXFlux2KleinImageEdit";
const IMAGE_COUNT_WIDGET = "image_count";
const BOTTOM_SPACER_NAME = "__lx_flux2_klein_image_edit_bottom_spacer";
const BOTTOM_SPACER_HEIGHT = 5;
const HOLLOW_CIRCLE_SHAPE = () =>
    globalThis.LiteGraph?.HOLLOW_CIRCLE_SHAPE ?? globalThis.LiteGraph?.HollowCircle ?? 7;
const FIXED_INPUT_ORDER = [
    { name: "clip", type: "CLIP" },
    { name: "vae", type: "VAE" },
    { name: "image1_mask", type: "MASK", optional: true },
];
const IMAGE_INPUT_RE = /^image(\d+)$/;

function parseImageCount(value) {
    const match = String(value ?? "").match(/\d+/);
    if (!match) return 2;
    return Math.max(1, Math.min(10, Number.parseInt(match[0], 10)));
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

function removeLegacyChineseInputs(node) {
    let changed = false;
    const legacyNames = ["图像1遮罩"];
    for (let index = 1; index <= 10; index += 1) {
        legacyNames.push(`图像${index}`);
    }
    for (const name of legacyNames) {
        changed = removeInputByName(node, name) || changed;
    }
    return changed;
}

function refreshSize(node, allowShrink = false) {
    if (!node || typeof node.computeSize !== "function" || typeof node.setSize !== "function") return;
    ensureBottomSpacer(node);
    const size = node.computeSize();
    if (!Array.isArray(size)) return;
    const currentHeight = node.size?.[1] || 0;
    node.setSize([
        Math.max(node.size?.[0] || 0, size[0]),
        allowShrink ? size[1] : Math.max(currentHeight, size[1]),
    ]);
    node.setDirtyCanvas?.(true, true);
    app.graph?.setDirtyCanvas(true, true);
}

function syncImageInputs(node, options = {}) {
    if (!node?.inputs) return;
    const imageCount = getImageCount(node);
    let changed = false;

    changed = removeLegacyChineseInputs(node) || changed;

    for (const input of FIXED_INPUT_ORDER) {
        changed = ensureInput(node, input.name, input.type, { optional: input.optional }) || changed;
    }

    for (let index = 10; index > imageCount; index -= 1) {
        changed = removeInputByName(node, `image${index}`) || changed;
    }

    for (let index = 1; index <= imageCount; index += 1) {
        changed = ensureInput(node, `image${index}`, "IMAGE", { optional: true }) || changed;
    }

    if (changed) {
        refreshSize(node, options.allowShrink);
        requestAnimationFrame(() => refreshSize(node, options.allowShrink));
    }
}

function hookImageCountWidget(node) {
    const widget = (node.widgets || []).find((item) => item?.name === IMAGE_COUNT_WIDGET);
    if (!widget || widget.__lxFlux2KleinHooked) return;
    widget.__lxFlux2KleinHooked = true;

    const originalCallback = widget.callback;
    widget.callback = function () {
        const result = originalCallback?.apply(this, arguments);
        syncImageInputs(node);
        return result;
    };
}

function install(node, options = {}) {
    ensureBottomSpacer(node);
    hookImageCountWidget(node);
    const shouldShrink = () => !!options.allowShrink && !node.__lxFlux2KleinPreserveSize;
    syncImageInputs(node, { allowShrink: shouldShrink() });
    refreshSize(node, shouldShrink());
    requestAnimationFrame(() => {
        syncImageInputs(node, { allowShrink: shouldShrink() });
        refreshSize(node, shouldShrink());
    });
    window.setTimeout(() => {
        syncImageInputs(node, { allowShrink: shouldShrink() });
        refreshSize(node, shouldShrink());
    }, 150);

    if (!node.__lxFlux2KleinDrawHooked) {
        node.__lxFlux2KleinDrawHooked = true;
        const onDrawForeground = node.onDrawForeground;
        node.onDrawForeground = function () {
            const result = onDrawForeground?.apply(this, arguments);
            const imageCount = getImageCount(this);
            if (this.__lxFlux2KleinLastImageCount !== imageCount) {
                this.__lxFlux2KleinLastImageCount = imageCount;
                syncImageInputs(this);
            }
            return result;
        };
    }
}

app.registerExtension({
    name: "LX.ImageEdit.Flux2Klein",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            install(this, { allowShrink: !app.configuringGraph });
            return result;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            this.__lxFlux2KleinPreserveSize = true;
            const result = onConfigure?.apply(this, arguments);
            install(this);
            return result;
        };
    },

    async nodeCreated(node) {
        if (node?.comfyClass === NODE_NAME || node?.type === NODE_NAME) {
            install(node, { allowShrink: !app.configuringGraph && !node.__lxFlux2KleinPreserveSize });
        }
    },
});
