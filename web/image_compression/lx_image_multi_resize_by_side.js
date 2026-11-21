import { app } from "../../../../scripts/app.js";

const NODE_NAME = "LXImageMultiResizeBySide";
const COUNT_WIDGET = "数量";
const COUNT_PROPERTY = "lx_multi_resize_route_count";
const MAX_DYNAMIC_ROUTES = 32;
const DEFAULT_ROUTES = 4;

const HOLLOW_CIRCLE_SHAPE = () =>
    globalThis.LiteGraph?.HOLLOW_CIRCLE_SHAPE ?? globalThis.LiteGraph?.HollowCircle ?? 7;

function clampRouteCount(value) {
    const count = Number.parseInt(value, 10);
    if (!Number.isFinite(count)) return DEFAULT_ROUTES;
    return Math.max(1, Math.min(MAX_DYNAMIC_ROUTES, count));
}

function findWidget(node, name) {
    return (node.widgets || []).find((widget) => widget?.name === name);
}

function getRouteCount(node) {
    const widget = findWidget(node, COUNT_WIDGET);
    const count = clampRouteCount(widget?.value);
    if (widget && widget.value !== count) widget.value = count;
    return count;
}

function findInputIndex(node, name) {
    return (node.inputs || []).findIndex((input) => input?.name === name);
}

function findOutputIndex(node, name) {
    return (node.outputs || []).findIndex((output) => output?.name === name);
}

function removeInputByName(node, name) {
    const index = findInputIndex(node, name);
    if (index >= 0) {
        node.removeInput(index);
        return true;
    }
    return false;
}

function ensureInput(node, name) {
    const existingIndex = findInputIndex(node, name);
    if (existingIndex >= 0) {
        const input = node.inputs[existingIndex];
        input.type = "IMAGE";
        input.shape = HOLLOW_CIRCLE_SHAPE();
        input.optional = true;
        return false;
    }

    node.addInput(name, "IMAGE", {
        shape: HOLLOW_CIRCLE_SHAPE(),
        optional: true,
    });
    return true;
}

function removeOutputByName(node, name) {
    const index = findOutputIndex(node, name);
    if (index >= 0) {
        node.removeOutput(index);
        return true;
    }
    return false;
}

function ensureOutput(node, name) {
    const existingIndex = findOutputIndex(node, name);
    if (existingIndex >= 0) {
        node.outputs[existingIndex].type = "IMAGE";
        return false;
    }

    node.addOutput(name, "IMAGE");
    return true;
}

function refreshSize(node) {
    if (typeof node.computeSize === "function" && typeof node.setSize === "function") {
        const size = node.computeSize();
        if (Array.isArray(size)) {
            node.setSize([Math.max(node.size?.[0] || 0, size[0]), size[1]]);
        }
    }
    node.setDirtyCanvas?.(true, true);
    app.graph?.setDirtyCanvas(true, true);
}

function syncRoutes(node) {
    const count = getRouteCount(node);
    node.properties = node.properties || {};
    node.properties[COUNT_PROPERTY] = count;

    let changed = false;

    for (let index = MAX_DYNAMIC_ROUTES; index > count; index -= 1) {
        changed = removeInputByName(node, `图像${index}`) || changed;
        changed = removeOutputByName(node, `图像${index}`) || changed;
    }

    for (let index = 1; index <= count; index += 1) {
        changed = ensureInput(node, `图像${index}`) || changed;
        changed = ensureOutput(node, `图像${index}`) || changed;
    }

    if (changed) {
        refreshSize(node);
        requestAnimationFrame(() => refreshSize(node));
    } else {
        app.graph?.setDirtyCanvas(true, true);
    }
}

function installCountCallback(node) {
    const widget = findWidget(node, COUNT_WIDGET);
    if (!widget || widget.__lx_multi_resize_callback) return;
    const previous = widget.callback;
    widget.callback = function () {
        const result = previous?.apply(this, arguments);
        syncRoutes(node);
        return result;
    };
    widget.__lx_multi_resize_callback = true;
}

function applySavedCount(node, info) {
    const widget = findWidget(node, COUNT_WIDGET);
    if (!widget) return;
    widget.value = clampRouteCount(info?.properties?.[COUNT_PROPERTY] ?? widget.value);
}

function install(node, info = null) {
    applySavedCount(node, info);
    installCountCallback(node);
    window.setTimeout(() => syncRoutes(node), 0);
}

app.registerExtension({
    name: "LX.ImageCompression.MultiResizeBySide",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;
        if (nodeType.prototype.__lx_multi_resize_dynamic_installed) return;
        nodeType.prototype.__lx_multi_resize_dynamic_installed = true;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            install(this);
            return result;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            const result = onConfigure?.apply(this, arguments);
            install(this, info);
            return result;
        };

        const onWidgetChanged = nodeType.prototype.onWidgetChanged;
        nodeType.prototype.onWidgetChanged = function (name) {
            const result = onWidgetChanged?.apply(this, arguments);
            if (name === COUNT_WIDGET) window.setTimeout(() => syncRoutes(this), 0);
            return result;
        };

        const onSerialize = nodeType.prototype.onSerialize;
        nodeType.prototype.onSerialize = function (data) {
            const result = onSerialize?.apply(this, arguments);
            data.properties = data.properties || {};
            data.properties[COUNT_PROPERTY] = getRouteCount(this);
            return result;
        };
    },

    async nodeCreated(node) {
        if (node?.comfyClass === NODE_NAME || node?.type === NODE_NAME) {
            install(node);
        }
    },
});
