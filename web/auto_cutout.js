import { app } from "../../../../scripts/app.js";

const AUTO_CUTOUT_NODE_NAME = "AutoCutout";
const SEMANTIC_CUTOUT_NODE_NAME = "SemanticCutout";
const NODE_NAMES = new Set([AUTO_CUTOUT_NODE_NAME, SEMANTIC_CUTOUT_NODE_NAME]);
const SENSITIVITY_WIDGET_NAME = "灵敏度";
const BACKGROUND_COLOR_WIDGET_NAME = "\u80cc\u666f\u989c\u8272";
const RESIZE_RETRY_DELAYS = [60, 160, 420, 900, 1600, 3000];
const SIZE_EPSILON = 2;
const SEMANTIC_BOTTOM_SPACER_NAME = "__lx_semantic_cutout_bottom_spacer";
const SEMANTIC_BOTTOM_SPACER_HEIGHT = 5;

function isNodeClass(node, name) {
    return node?.comfyClass === name || node?.type === name || node?.constructor?.comfyClass === name;
}

function isManagedCutoutNode(node) {
    return isNodeClass(node, AUTO_CUTOUT_NODE_NAME) || isNodeClass(node, SEMANTIC_CUTOUT_NODE_NAME);
}

function ensureBottomSpacer(node, spacerName, spacerHeight) {
    node.widgets = node.widgets || [];
    let spacer = node.widgets.find((widget) => widget?.name === spacerName);

    if (!spacer) {
        spacer = {
            name: spacerName,
            type: "custom",
            value: "",
            serialize: false,
            options: { canvasOnly: true },
            computeSize: () => [0, spacerHeight],
            draw: () => {},
        };
        node.widgets.push(spacer);
    } else {
        spacer.hidden = false;
        spacer.type = "custom";
        spacer.value = "";
        spacer.serialize = false;
        spacer.options = { ...(spacer.options || {}), canvasOnly: true };
        spacer.computeSize = () => [0, spacerHeight];
        spacer.draw = () => {};
    }

    const index = node.widgets.indexOf(spacer);
    if (index !== node.widgets.length - 1) {
        node.widgets.splice(index, 1);
        node.widgets.push(spacer);
    }
}

function ensureSemanticBottomSpacer(node) {
    if (!isNodeClass(node, SEMANTIC_CUTOUT_NODE_NAME)) return;
    ensureBottomSpacer(node, SEMANTIC_BOTTOM_SPACER_NAME, SEMANTIC_BOTTOM_SPACER_HEIGHT);
}

function normalizeCutoutNodeWidgets(node) {
    if (!isManagedCutoutNode(node)) return;
    removeDuplicateBackgroundColorWidgets(node);
    ensureSemanticBottomSpacer(node);
}

function resizeNodeToNaturalHeight(node) {
    if (!isManagedCutoutNode(node)) return;
    if (typeof node?.computeSize !== "function" || typeof node?.setSize !== "function") return;
    if (!Array.isArray(node.size)) return;

    normalizeCutoutNodeWidgets(node);

    const computed = node.computeSize();
    if (!Array.isArray(computed)) return;

    const currentWidth = Number(node.size[0]);
    const currentHeight = Number(node.size[1]);
    const targetHeight = Number(computed[1]);

    if (!Number.isFinite(targetHeight) || targetHeight <= 0) return;

    const width = Number.isFinite(currentWidth) && currentWidth > 0 ? currentWidth : Number(computed[0]);
    if (!Number.isFinite(width) || width <= 0) return;

    if (!Number.isFinite(currentHeight) || Math.abs(currentHeight - targetHeight) > SIZE_EPSILON) {
        node.setSize([width, targetHeight]);
        node.setDirtyCanvas?.(true, true);
        app.graph?.setDirtyCanvas(true, true);
    }
}

function scheduleResizeNode(node) {
    if (!isManagedCutoutNode(node)) return;
    normalizeCutoutNodeWidgets(node);
    resizeNodeToNaturalHeight(node);
    requestAnimationFrame(() => {
        normalizeCutoutNodeWidgets(node);
        resizeNodeToNaturalHeight(node);
    });
    for (const delay of RESIZE_RETRY_DELAYS) {
        window.setTimeout(() => {
            normalizeCutoutNodeWidgets(node);
            resizeNodeToNaturalHeight(node);
        }, delay);
    }
}

function getGraphNodes() {
    const nodes = app.graph?._nodes || app.graph?.nodes || [];
    return Array.isArray(nodes) ? nodes : [];
}

function resizeExistingNodes() {
    for (const node of getGraphNodes()) {
        normalizeCutoutNodeWidgets(node);
        resizeNodeToNaturalHeight(node);
    }
}

function scheduleResizeExistingNodes() {
    resizeExistingNodes();
    requestAnimationFrame(resizeExistingNodes);
    for (const delay of RESIZE_RETRY_DELAYS) {
        window.setTimeout(resizeExistingNodes, delay);
    }
}

function markSensitivityAsNumber(nodeData) {
    const sections = [nodeData?.input?.required, nodeData?.input?.optional];
    for (const section of sections) {
        const spec = section?.[SENSITIVITY_WIDGET_NAME];
        if (!Array.isArray(spec)) continue;

        spec[1] = spec[1] || {};
        spec[1].display = "number";
    }
}

function isHexColorValue(value) {
    return /^#[0-9a-fA-F]{6}$/.test(String(value ?? "").trim());
}

function disableWidgetElement(widget) {
    const elements = [widget?.inputEl, widget?.element].filter(Boolean);
    for (const element of elements) {
        if (!element?.style) continue;
        element.style.display = "none";
        element.style.visibility = "hidden";
        element.style.pointerEvents = "none";
        element.tabIndex = -1;
    }
}

function removeDuplicateBackgroundColorWidgets(node) {
    if (!isManagedCutoutNode(node)) return;
    if (!Array.isArray(node.widgets)) return;

    const colorWidgets = node.widgets.filter((widget) => widget?.name === BACKGROUND_COLOR_WIDGET_NAME);
    if (colorWidgets.length <= 1) return;

    const keepWidget = colorWidgets.find((widget) => isHexColorValue(widget.value)) || colorWidgets[0];
    for (const widget of colorWidgets) {
        if (widget === keepWidget) continue;
        disableWidgetElement(widget);
    }

    node.widgets = node.widgets.filter((widget) => widget === keepWidget || widget?.name !== BACKGROUND_COLOR_WIDGET_NAME);
    node.setDirtyCanvas?.(true, true);
    node.graph?.setDirtyCanvas?.(true, true);
}

app.registerExtension({
    name: "LX.AutoCutout.Size",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!NODE_NAMES.has(nodeData?.name)) return;

        markSensitivityAsNumber(nodeData);

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            scheduleResizeNode(this);
            return result;
        };

        const onAdded = nodeType.prototype.onAdded;
        nodeType.prototype.onAdded = function () {
            const result = onAdded?.apply(this, arguments);
            scheduleResizeNode(this);
            return result;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = onConfigure?.apply(this, arguments);
            scheduleResizeNode(this);
            return result;
        };
    },

    nodeCreated(node) {
        scheduleResizeNode(node);
    },

    loadedGraphNode(node) {
        scheduleResizeNode(node);
    },

    setup() {
        scheduleResizeExistingNodes();
    },

    afterConfigureGraph() {
        scheduleResizeExistingNodes();
    },
});
