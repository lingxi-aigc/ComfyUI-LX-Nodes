import { app } from "../../../../scripts/app.js";

const NODE_NAME = "LXPromptSplitter";
const MAX_OUTPUTS = 32;
const DEFAULT_OUTPUTS = 8;
const COUNT_WIDGET = "数量";
const PREFIX_WIDGET = "添加前缀";
const SUFFIX_WIDGET = "添加后缀";
const WIDGET_ORDER = [COUNT_WIDGET, PREFIX_WIDGET, SUFFIX_WIDGET];
const VALUES_PROPERTY = "lx_prompt_splitter_values";

function clampCount(value) {
    const count = Number.parseInt(value, 10);
    if (!Number.isFinite(count)) return DEFAULT_OUTPUTS;
    return Math.max(1, Math.min(MAX_OUTPUTS, count));
}

function findWidget(node, name) {
    return (node.widgets || []).find((widget) => widget.name === name);
}

function getCountWidget(node) {
    return findWidget(node, COUNT_WIDGET);
}

function getOutputCount(node) {
    const widget = getCountWidget(node);
    const count = clampCount(widget?.value);
    if (widget && widget.value !== count) {
        widget.value = count;
    }
    return count;
}

function getTextWidgetValue(node, name) {
    const value = findWidget(node, name)?.value;
    return value == null ? "" : String(value);
}

function getSavedValues(info) {
    const values = info?.properties?.[VALUES_PROPERTY];
    if (!values || typeof values !== "object") return null;
    return {
        prefix: values.prefix == null ? "" : String(values.prefix),
        suffix: values.suffix == null ? "" : String(values.suffix),
        count: clampCount(values.count),
    };
}

function captureValues(node) {
    return {
        prefix: getTextWidgetValue(node, PREFIX_WIDGET),
        suffix: getTextWidgetValue(node, SUFFIX_WIDGET),
        count: getOutputCount(node),
    };
}

function applyValues(node, values) {
    if (!values) return;
    const prefixWidget = findWidget(node, PREFIX_WIDGET);
    if (prefixWidget) prefixWidget.value = values.prefix;

    const suffixWidget = findWidget(node, SUFFIX_WIDGET);
    if (suffixWidget) suffixWidget.value = values.suffix;

    const countWidget = getCountWidget(node);
    if (countWidget) countWidget.value = values.count;
}

function markDirty(node) {
    if (node.computeSize) {
        node.setSize(node.computeSize());
    }
    app.graph?.setDirtyCanvas(true, true);
}

function orderWidgets(node) {
    if (!Array.isArray(node.widgets)) return;

    const widgetsByName = new Map();
    for (const widget of node.widgets) {
        if (WIDGET_ORDER.includes(widget.name) && !widgetsByName.has(widget.name)) {
            widgetsByName.set(widget.name, widget);
        }
    }

    const orderedWidgets = WIDGET_ORDER.map((name) => widgetsByName.get(name)).filter(Boolean);
    if (orderedWidgets.length < 2) return;

    const orderedSet = new Set(orderedWidgets);
    const nextWidgets = [];
    let inserted = false;
    for (const widget of node.widgets) {
        if (orderedSet.has(widget)) {
            if (!inserted) {
                nextWidgets.push(...orderedWidgets);
                inserted = true;
            }
        } else {
            nextWidgets.push(widget);
        }
    }
    node.widgets = nextWidgets;
}

function syncPromptOutputs(node) {
    const count = getOutputCount(node);
    node.properties = node.properties || {};
    node.properties.lx_prompt_output_count = count;
    node.properties[VALUES_PROPERTY] = captureValues(node);
    orderWidgets(node);

    while ((node.outputs || []).length < count) {
        const index = (node.outputs || []).length + 1;
        node.addOutput(`prompt${index}`, "STRING");
    }

    while ((node.outputs || []).length > count) {
        node.removeOutput(node.outputs.length - 1);
    }

    for (let index = 0; index < (node.outputs || []).length; index += 1) {
        node.outputs[index].name = `prompt${index + 1}`;
        node.outputs[index].type = "STRING";
    }

    markDirty(node);
}

function installCountCallback(node) {
    const widget = getCountWidget(node);
    if (!widget || widget.__lx_prompt_splitter_callback) return;
    const previous = widget.callback;
    widget.callback = function () {
        const result = previous?.apply(this, arguments);
        syncPromptOutputs(node);
        return result;
    };
    widget.__lx_prompt_splitter_callback = true;
}

function deferSync(node) {
    window.setTimeout(() => syncPromptOutputs(node), 0);
}

app.registerExtension({
    name: "LX.PromptTools.Splitter",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;
        if (nodeType.prototype.__lx_prompt_splitter_dynamic_installed) return;
        nodeType.prototype.__lx_prompt_splitter_dynamic_installed = true;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            installCountCallback(this);
            deferSync(this);
            return result;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            const savedValues = getSavedValues(info);
            const result = onConfigure?.apply(this, arguments);
            applyValues(this, savedValues);
            const widget = getCountWidget(this);
            if (widget) {
                widget.value = clampCount(widget.value ?? info?.properties?.lx_prompt_output_count);
            }
            installCountCallback(this);
            deferSync(this);
            return result;
        };

        const onWidgetChanged = nodeType.prototype.onWidgetChanged;
        nodeType.prototype.onWidgetChanged = function (name) {
            const result = onWidgetChanged?.apply(this, arguments);
            if (name === COUNT_WIDGET) deferSync(this);
            return result;
        };

        const onSerialize = nodeType.prototype.onSerialize;
        nodeType.prototype.onSerialize = function (data) {
            const result = onSerialize?.apply(this, arguments);
            data.properties = data.properties || {};
            data.properties[VALUES_PROPERTY] = captureValues(this);
            data.properties.lx_prompt_output_count = data.properties[VALUES_PROPERTY].count;
            return result;
        };
    },
});
