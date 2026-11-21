import { app } from "../../../../scripts/app.js";
import { ComfyWidgets } from "../../../../scripts/widgets.js";
import { setWidgetConfig } from "../../../../extensions/core/widgetInputs.js";

const NODE_NAME = "LXPromptList";
const MAX_PROMPTS = 32;
const DEFAULT_PROMPTS = 5;
const BOTTOM_SPACER_NAME = "__lx_prompt_list_bottom_spacer";
const BOTTOM_SPACER_HEIGHT = 5;
const COUNT_WIDGET = "数量";
const OUTPUTS = [
    ["列表", "LIST"],
    ["prompt_strings", "STRING"],
];
let promptListNodeData = null;
let graphToPromptWrapped = false;

function clampCount(value) {
    const count = Number.parseInt(value, 10);
    if (!Number.isFinite(count)) return DEFAULT_PROMPTS;
    return Math.max(1, Math.min(MAX_PROMPTS, count));
}

function promptIndex(name) {
    const text = String(name || "");
    const match =
        /^prompt_(\d+)$/.exec(text) ||
        /^prompt(\d+)$/.exec(text) ||
        /^\u63d0\u793a\u8bcd_?(\d+)$/.exec(text) ||
        /^\u53c2\u8003\u6587\u672c_?(\d+)$/.exec(text);
    if (!match) return 0;
    const index = Number.parseInt(match[1], 10);
    return index >= 1 && index <= MAX_PROMPTS ? index : 0;
}

function promptName(index) {
    return `prompt_${index}`;
}

function promptDisplayName(nameOrIndex) {
    const index = typeof nameOrIndex === "number" ? nameOrIndex : promptIndex(nameOrIndex);
    return index ? `提示词${index}` : String(nameOrIndex || "");
}

function promptWidgetConfig(name) {
    const displayName = promptDisplayName(name);
    return ["STRING", { default: "", multiline: true, display_name: displayName, label: displayName }];
}

function normalizePromptName(name) {
    const index = promptIndex(name);
    return index ? promptName(index) : String(name || "");
}

function normalizePromptValues(values) {
    const normalized = {};
    if (!values || typeof values !== "object") return normalized;

    for (const [key, value] of Object.entries(values)) {
        normalized[normalizePromptName(key)] = value;
    }
    return normalized;
}

function applyPromptDisplayName(target, name) {
    if (!target) return;
    const displayName = promptDisplayName(name);
    target.name = name;
    target.label = displayName;
    target.localized_name = displayName;
    if (target.options && typeof target.options === "object") {
        target.options.label = displayName;
        target.options.display_name = displayName;
    }
}

function findWidget(node, name) {
    return (node.widgets || []).find((widget) => widget.name === name);
}

function getPromptCount(node) {
    return clampCount(findWidget(node, COUNT_WIDGET)?.value);
}

function installCountCallback(node) {
    const widget = findWidget(node, COUNT_WIDGET);
    if (!widget || widget.__lx_prompt_list_callback) return;

    const previous = widget.callback;
    widget.callback = function () {
        const result = previous?.apply(this, arguments);
        deferRebuild(node);
        return result;
    };
    widget.__lx_prompt_list_callback = true;
}

function setPromptCount(node, value) {
    const count = clampCount(value);
    const widget = findWidget(node, COUNT_WIDGET);
    if (widget) widget.value = count;

    node.properties = node.properties || {};
    node.properties.lx_prompt_list_count = count;
    return count;
}

function collectPromptValues(node) {
    const values = normalizePromptValues(node.properties?.lx_prompt_list_values);
    for (const widget of node.widgets || []) {
        const index = promptIndex(widget.name);
        if (index) {
            values[promptName(index)] = widget.value ?? "";
        }
    }
    return values;
}

function savePromptValues(node) {
    node.properties = node.properties || {};
    node.properties.lx_prompt_list_values = collectPromptValues(node);
    return node.properties.lx_prompt_list_values;
}

function removeWidget(node, widget) {
    if (!widget) return;

    const index = (node.widgets || []).indexOf(widget);
    if (index >= 0) {
        node.widgets.splice(index, 1);
    }
    widget.onRemove?.();
}

function findInput(node, name) {
    return (node.inputs || []).find((input) => input.name === name);
}

function inputHasLinks(input) {
    return input?.link != null || (Array.isArray(input?.links) && input.links.length > 0);
}

function normalizePromptWidgets(node) {
    for (const widget of [...(node.widgets || [])]) {
        const index = promptIndex(widget?.name);
        if (!index) continue;

        const name = promptName(index);
        if (widget.name === name) {
            applyPromptDisplayName(widget, name);
            continue;
        }

        const existing = findWidget(node, name);
        if (existing && existing !== widget) {
            if ((existing.value == null || existing.value === "") && widget.value) {
                existing.value = widget.value;
            }
            removeWidget(node, widget);
            applyPromptDisplayName(existing, name);
            continue;
        }

        applyPromptDisplayName(widget, name);
    }
}

function bindPromptInput(node, widget) {
    if (!widget) return null;

    const name = normalizePromptName(widget.name);
    applyPromptDisplayName(widget, name);

    let input = findInput(node, name);
    if (!input) {
        input = node.addInput(name, "STRING", { widget: { name } });
    }

    applyPromptDisplayName(input, name);
    input.type = "STRING";
    input.widget = { name };
    input._widget = widget;
    setWidgetConfig(input, promptWidgetConfig(name));
    return input;
}

function syncInputs(node, count, promptWidgets) {
    for (let index = (node.inputs || []).length - 1; index >= 0; index -= 1) {
        const input = node.inputs[index];
        const promptSlot = promptIndex(input?.name);
        if (!promptSlot) continue;

        const name = promptName(promptSlot);
        const duplicate = input.name === name ? null : findInput(node, name);
        if (duplicate && duplicate !== input) {
            if (inputHasLinks(input) && !inputHasLinks(duplicate)) {
                node.removeInput(node.inputs.indexOf(duplicate));
                index = node.inputs.indexOf(input);
                applyPromptDisplayName(input, name);
            } else {
                node.removeInput(index);
                continue;
            }
        } else {
            applyPromptDisplayName(input, name);
        }

        if (promptSlot > count) {
            const currentIndex = node.inputs.indexOf(input);
            if (currentIndex >= 0) {
                node.removeInput(currentIndex);
            }
        }
    }

    for (const widget of promptWidgets) {
        bindPromptInput(node, widget);
    }
}

function syncOutputs(node) {
    while ((node.outputs || []).length > OUTPUTS.length) {
        node.removeOutput(node.outputs.length - 1);
    }
    while ((node.outputs || []).length < OUTPUTS.length) {
        const [name, type] = OUTPUTS[node.outputs.length];
        node.addOutput(name, type);
    }

    OUTPUTS.forEach(([name, type], index) => {
        if (!node.outputs[index]) return;
        node.outputs[index].name = name;
        node.outputs[index].type = type;
    });
}

function createPromptWidget(node, index, value) {
    const name = promptName(index);
    const result = ComfyWidgets.STRING(
        node,
        name,
        promptWidgetConfig(name),
        app,
    );
    const widget = result?.widget || findWidget(node, name);
    if (widget) {
        applyPromptDisplayName(widget, name);
        widget.value = value ?? "";
    }
    return widget;
}

function ensurePromptWidgets(node, count, values) {
    const promptWidgets = [];
    normalizePromptWidgets(node);

    for (const widget of [...(node.widgets || [])]) {
        const index = promptIndex(widget.name);
        if (index > count) {
            removeWidget(node, widget);
        }
    }

    for (let index = 1; index <= count; index += 1) {
        const name = promptName(index);
        const widget = findWidget(node, name) || createPromptWidget(node, index, values[name]);
        if (widget && values[name] !== undefined) {
            applyPromptDisplayName(widget, name);
            widget.value = values[name];
        }
        if (widget) {
            promptWidgets.push(widget);
        }
    }
    return promptWidgets;
}

function ensureBottomSpacer(node) {
    let widget = findWidget(node, BOTTOM_SPACER_NAME);
    if (!widget) {
        widget = {
            name: BOTTOM_SPACER_NAME,
            type: "custom",
            value: "",
            serialize: false,
            computeSize: () => [0, BOTTOM_SPACER_HEIGHT],
            draw: () => {},
        };
        node.widgets = node.widgets || [];
        node.widgets.push(widget);
    } else {
        widget.hidden = false;
        widget.serialize = false;
        widget.computeSize = () => [0, BOTTOM_SPACER_HEIGHT];
        widget.draw = () => {};
    }
    return widget;
}

function orderWidgets(node, promptWidgets) {
    const countWidget = findWidget(node, COUNT_WIDGET);
    const bottomSpacer = ensureBottomSpacer(node);
    const others = (node.widgets || []).filter(
        (widget) =>
            !promptIndex(widget.name) &&
            widget !== countWidget &&
            widget !== bottomSpacer &&
            widget.name !== BOTTOM_SPACER_NAME,
    );

    node.widgets = [
        ...others,
        ...promptWidgets,
        countWidget,
        bottomSpacer,
    ].filter(Boolean);
}

function refreshNaturalSize(node) {
    if (!node.computeSize || !node.setSize) return;

    requestAnimationFrame(() => {
        const [width, height] = node.computeSize();
        const currentWidth = node.size?.[0] || width;
        const currentHeight = node.size?.[1] || height;
        node.setSize([Math.max(currentWidth, width), Math.max(currentHeight, height)]);
        node.setDirtyCanvas?.(true, true);
        app.graph?.setDirtyCanvas(true, true);
    });
}

function rebuildPromptList(node, explicitValues = null, explicitCount = null) {
    node.properties = node.properties || {};
    const values = explicitValues ? normalizePromptValues(explicitValues) : savePromptValues(node);
    const count = setPromptCount(node, explicitCount ?? getPromptCount(node));

    syncOutputs(node);

    const promptWidgets = ensurePromptWidgets(node, count, values);
    syncInputs(node, count, promptWidgets);
    orderWidgets(node, promptWidgets);
    refreshNaturalSize(node);
    app.graph?.setDirtyCanvas(true, true);
}

function initializePromptList(node, values = null, count = null) {
    const initialValues = values || savePromptValues(node);
    const initialCount = count ?? getPromptCount(node);
    rebuildPromptList(node, initialValues, initialCount);
    installCountCallback(node);
}

function deferRebuild(node, values = null, count = null) {
    if (!values && count == null && node.__lx_prompt_list_rebuild_queued) return;
    if (!values && count == null) node.__lx_prompt_list_rebuild_queued = true;
    window.setTimeout(() => {
        node.__lx_prompt_list_rebuild_queued = false;
        rebuildPromptList(node, values, count);
        installCountCallback(node);
    }, 0);
}

function trimNodeDefinition(nodeData) {
    const optional = nodeData?.input?.optional;
    if (!optional) return;

    const normalized = {};
    for (const [name, config] of Object.entries(optional)) {
        const index = promptIndex(name);
        if (!index) {
            normalized[name] = config;
            continue;
        }
        if (index > DEFAULT_PROMPTS) continue;
        normalized[promptName(index)] = promptWidgetConfig(promptName(index));
    }

    for (const name of Object.keys(optional)) {
        delete optional[name];
    }
    Object.assign(optional, normalized);

    const order = nodeData.input_order?.optional;
    if (Array.isArray(order)) {
        const seen = new Set();
        nodeData.input_order.optional = order.filter((name) => {
            const index = promptIndex(name);
            if (!index) return true;
            return index <= DEFAULT_PROMPTS;
        }).map((name) => {
            const index = promptIndex(name);
            return index ? promptName(index) : name;
        }).filter((name) => {
            if (seen.has(name)) return false;
            seen.add(name);
            return true;
        });
    }
}

function registerDynamicPromptInputsForPrompt() {
    const optional = promptListNodeData?.input?.optional;
    if (!optional) return () => {};

    const added = [];
    for (const node of app.graph?._nodes || app.graph?.nodes || []) {
        if (node?.comfyClass !== NODE_NAME && node?.type !== NODE_NAME) continue;
        for (const input of node.inputs || []) {
            const name = normalizePromptName(input.name);
            if (!promptIndex(input?.name) || optional[name]) continue;
            optional[name] = promptWidgetConfig(name);
            added.push(name);
        }
    }

    return () => {
        for (const name of added) {
            delete optional[name];
        }
    };
}

function ensureGraphToPromptWrapped() {
    if (graphToPromptWrapped || !app.graphToPrompt) return;
    graphToPromptWrapped = true;
    const originalGraphToPrompt = app.graphToPrompt;
    app.graphToPrompt = async function () {
        const restore = registerDynamicPromptInputsForPrompt();
        try {
            return await originalGraphToPrompt.apply(this, arguments);
        } finally {
            restore();
        }
    };
}

app.registerExtension({
    name: "LX.TextTools.PromptList",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;
        if (nodeType.prototype.__lx_prompt_list_dynamic_installed) return;
        nodeType.prototype.__lx_prompt_list_dynamic_installed = true;

        promptListNodeData = nodeData;
        trimNodeDefinition(nodeData);

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            initializePromptList(this);
            return result;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            const result = onConfigure?.apply(this, arguments);
            initializePromptList(
                this,
                info?.properties?.lx_prompt_list_values || null,
                info?.properties?.lx_prompt_list_count ?? null,
            );
            return result;
        };

        const onWidgetChanged = nodeType.prototype.onWidgetChanged;
        nodeType.prototype.onWidgetChanged = function (name) {
            const result = onWidgetChanged?.apply(this, arguments);
            if (name === COUNT_WIDGET) deferRebuild(this);
            return result;
        };

        const onSerialize = nodeType.prototype.onSerialize;
        nodeType.prototype.onSerialize = function (data) {
            const result = onSerialize?.apply(this, arguments);
            data.properties = data.properties || {};
            data.properties.lx_prompt_list_count = getPromptCount(this);
            data.properties.lx_prompt_list_values = savePromptValues(this);
            return result;
        };
    },

    setup() {
        ensureGraphToPromptWrapped();
    },
});
