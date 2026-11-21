import { app } from "../../../../scripts/app.js";
import { ComfyWidgets, addValueControlWidgets, isValidWidgetType } from "../../../../scripts/widgets.js";

const NODE_TYPE = "LXMetaNode";
const NODE_TITLE = "元节点";
const NODE_CATEGORY = "🅻🆇 灵犀/实用工具";
const NODE_DESCRIPTION = "连接到控件输入后自动匹配控件类型，并同步控件值。";
const DEFAULT_OUTPUT_NAME = "连接到控件输入";
const VALUE_WIDGET_NAME = "value";
const DEFAULT_NODE_MIN_WIDTH = 220;
const DEFAULT_NODE_WIDTH_PADDING = 16;
const DEFAULT_NODE_HEIGHT = 50;
const SEARCH_ALIASES = [
    "lx",
    "LX",
    "灵犀",
    "元节点",
    "LXMetaNode",
    "LXMeta节点",
    "LX Meta Node",
    "meta node",
];

function createNodeData() {
    return {
        name: NODE_TYPE,
        display_name: NODE_TITLE,
        description: NODE_DESCRIPTION,
        category: NODE_CATEGORY,
        search_aliases: SEARCH_ALIASES,
        input: { required: {}, optional: {}, hidden: {} },
        output: ["*"],
        output_name: [DEFAULT_OUTPUT_NAME],
        output_is_list: [false],
        output_node: false,
    };
}

function getDisplayTitle(title) {
    return typeof title === "string" ? title : NODE_TITLE;
}

function getLink(graph, linkId) {
    if (!graph || linkId == null) return null;
    if (graph.links instanceof Map) return graph.links.get(linkId) || null;
    return graph.links?.[linkId] || null;
}

function cloneInputSpec(spec) {
    if (!Array.isArray(spec)) return ["*", {}];

    const type = Array.isArray(spec[0]) ? [...spec[0]] : spec[0];
    const options = spec[1] && typeof spec[1] === "object" ? { ...spec[1] } : {};
    if (Array.isArray(options.options)) options.options = [...options.options];
    if (Array.isArray(options.values)) options.values = [...options.values];
    return [type, options];
}

function getSpecType(spec) {
    if (!Array.isArray(spec)) return "*";
    return Array.isArray(spec[0]) ? "COMBO" : spec[0];
}

function getComboValues(spec, widget) {
    if (Array.isArray(spec?.[0])) return [...spec[0]];
    if (Array.isArray(spec?.[1]?.options)) return [...spec[1].options];
    if (Array.isArray(spec?.[1]?.values)) return [...spec[1].values];
    if (Array.isArray(widget?.options?.values)) return [...widget.options.values];
    return null;
}

function makeComboSpec(baseSpec, values) {
    const options = baseSpec?.[1] && typeof baseSpec[1] === "object" ? { ...baseSpec[1] } : {};
    delete options.values;
    options.options = values;
    return ["COMBO", options];
}

function mergeControlOptions(options, nextOptions) {
    for (const key of ["control_after_generate", "control_filter_list", "control_prefix"]) {
        if (options[key] === undefined && nextOptions[key] !== undefined) {
            options[key] = nextOptions[key];
        }
    }
    return options;
}

function getWidgetName(input) {
    return input?.widget?.name || input?.name;
}

function getTargetWidget(node, input) {
    const widgetName = getWidgetName(input);
    if (!widgetName) return null;
    return node?.widgets?.find((widget) => widget?.name === widgetName) || null;
}

function getInputWidgetSpec(input) {
    const widget = input?.widget;
    if (!widget || typeof widget !== "object") return null;

    if (Array.isArray(widget.config)) return cloneInputSpec(widget.config);

    const seen = new Set();
    for (let owner = widget; owner && owner !== Object.prototype; owner = Object.getPrototypeOf(owner)) {
        for (const key of Object.getOwnPropertySymbols(owner)) {
            if (seen.has(key)) continue;
            seen.add(key);

            const getter = widget[key];
            if (typeof getter !== "function") continue;

            try {
                const spec = getter.call(widget);
                if (Array.isArray(spec)) return cloneInputSpec(spec);
            } catch {
                // Ignore non-config symbol helpers.
            }
        }
    }

    return null;
}

function findNodeInputSpec(node, input) {
    const widgetName = getWidgetName(input);
    if (!node || !input || !widgetName) return null;

    const widgetSpec = getInputWidgetSpec(input);
    if (widgetSpec) return widgetSpec;

    const nodeData = node.constructor?.nodeData;
    const spec =
        nodeData?.input?.required?.[widgetName] ||
        nodeData?.input?.optional?.[widgetName];

    if (spec) return cloneInputSpec(spec);

    const targetWidget = getTargetWidget(node, input);
    const type = input.type || targetWidget?.type;

    if (type === "COMBO" || targetWidget?.type === "combo") {
        const values = Array.isArray(targetWidget?.options?.values)
            ? [...targetWidget.options.values]
            : [];
        return ["COMBO", { options: values, default: targetWidget?.value }];
    }

    if (type === "INT" || type === "FLOAT" || targetWidget?.type === "number") {
        const options = targetWidget?.options || {};
        return [
            type === "FLOAT" ? "FLOAT" : "INT",
            {
                default: targetWidget?.value,
                min: options.min,
                max: options.max,
                step: options.step || options.step2,
            },
        ];
    }

    if (type === "BOOLEAN" || targetWidget?.type === "toggle") {
        return ["BOOLEAN", { default: Boolean(targetWidget?.value) }];
    }

    if (type === "STRING" || targetWidget?.type === "text" || targetWidget?.type === "string") {
        return ["STRING", { default: targetWidget?.value ?? "", multiline: !!targetWidget?.options?.multiline }];
    }

    if (typeof type === "string" && isValidWidgetType(type)) {
        return [type, { default: targetWidget?.value }];
    }

    return null;
}

function intersectValues(left, right) {
    const rightKeys = new Set(right.map((value) => String(value)));
    return left.filter((value) => rightKeys.has(String(value)));
}

function mergeInputSpecs(specs) {
    if (!specs.length) return null;

    let merged = cloneInputSpec(specs[0]);
    let mergedType = getSpecType(merged);

    for (let index = 1; index < specs.length; index += 1) {
        const next = cloneInputSpec(specs[index]);
        const nextType = getSpecType(next);
        if (mergedType !== nextType) return null;

        if (mergedType === "COMBO") {
            const leftValues = getComboValues(merged) || [];
            const rightValues = getComboValues(next) || [];
            if (leftValues.length && rightValues.length) {
                const values = intersectValues(leftValues, rightValues);
                if (!values.length) return null;
                merged = makeComboSpec(merged, values);
            }
            merged[1] = mergeControlOptions(merged[1] || {}, next[1] || {});
        } else if (mergedType === "INT" || mergedType === "FLOAT") {
            const options = { ...(merged[1] || {}) };
            const nextOptions = next[1] || {};
            const min = Math.max(
                options.min ?? Number.NEGATIVE_INFINITY,
                nextOptions.min ?? Number.NEGATIVE_INFINITY,
            );
            const max = Math.min(
                options.max ?? Number.POSITIVE_INFINITY,
                nextOptions.max ?? Number.POSITIVE_INFINITY,
            );
            if (min > max) return null;
            options.min = Number.isFinite(min) ? min : undefined;
            options.max = Number.isFinite(max) ? max : undefined;
            options.step = options.step ?? nextOptions.step;
            mergeControlOptions(options, nextOptions);
            merged = [mergedType, options];
        }
    }

    return merged;
}

function coerceValue(value, spec, targetWidget) {
    const type = getSpecType(spec);

    if (type === "INT") {
        const min = spec?.[1]?.min ?? targetWidget?.options?.min;
        const max = spec?.[1]?.max ?? targetWidget?.options?.max;
        let next = Number.parseInt(value, 10);
        if (!Number.isFinite(next)) next = 0;
        if (min != null) next = Math.max(min, next);
        if (max != null) next = Math.min(max, next);
        return next;
    }

    if (type === "FLOAT") {
        const min = spec?.[1]?.min ?? targetWidget?.options?.min;
        const max = spec?.[1]?.max ?? targetWidget?.options?.max;
        let next = Number(value);
        if (!Number.isFinite(next)) next = 0;
        if (min != null) next = Math.max(min, next);
        if (max != null) next = Math.min(max, next);
        return next;
    }

    if (type === "BOOLEAN") return Boolean(value);

    if (type === "COMBO") {
        const values = getComboValues(spec, targetWidget);
        if (values?.length && !values.map((item) => String(item)).includes(String(value))) {
            return values[0];
        }
    }

    if (type === "STRING") return value == null ? "" : String(value);
    return value;
}

function getInitialNodeSize(node) {
    const computed = node.computeSize ? node.computeSize() : node.size;
    const width = Math.max(
        DEFAULT_NODE_MIN_WIDTH,
        (computed?.[0] || 0) + DEFAULT_NODE_WIDTH_PADDING,
    );
    const height = Math.max(DEFAULT_NODE_HEIGHT, computed?.[1] || 0);
    return [Math.ceil(width), Math.ceil(height)];
}

function setNodeSize(node, size = getInitialNodeSize(node)) {
    node.setSize?.(size);
    node.onResize?.(node.size);
    app.graph?.setDirtyCanvas?.(true, true);
}

function setNodeSizeToWidgets(node, oldWidth = 0, oldHeight = 0) {
    const fallback = getInitialNodeSize(node);
    const computed = node.computeSize ? node.computeSize() : node.size;
    node.setSize?.([
        Math.max(oldWidth, computed?.[0] || node.size?.[0] || fallback[0]),
        Math.max(oldHeight, computed?.[1] || node.size?.[1] || fallback[1]),
    ]);
    node.onResize?.(node.size);
    app.graph?.setDirtyCanvas?.(true, true);
}

function getLinksForOutput(node, extraLinks = []) {
    const ids = node.outputs?.[0]?.links || [];
    return [
        ...ids.map((linkId) => getLink(node.graph, linkId)).filter(Boolean),
        ...extraLinks.filter(Boolean),
    ];
}

function getFirstLinkedWidgetValue(node) {
    for (const link of getLinksForOutput(node)) {
        const targetNode = node.graph?.getNodeById(link.target_id);
        const input = targetNode?.inputs?.[link.target_slot];
        const targetWidget = getTargetWidget(targetNode, input);
        if (targetWidget) return targetWidget.value;
    }
    return undefined;
}

function getLinkedWidgets(widget) {
    return Array.isArray(widget?.linkedWidgets)
        ? widget.linkedWidgets.filter(Boolean)
        : [];
}

function getLinkedWidgetValues(widget) {
    return getLinkedWidgets(widget).map((linkedWidget) => linkedWidget.value);
}

function getFirstLinkedControlValues(node) {
    for (const link of getLinksForOutput(node)) {
        const targetNode = node.graph?.getNodeById(link.target_id);
        const input = targetNode?.inputs?.[link.target_slot];
        const targetWidget = getTargetWidget(targetNode, input);
        const values = getLinkedWidgetValues(targetWidget);
        if (values.length) return values;
    }
    return [];
}

function getDefaultControlValue(spec) {
    const configured = spec?.[1]?.control_after_generate;
    if (typeof configured === "string") return configured;
    return getSpecType(spec) === "FLOAT" ? "fixed" : "randomize";
}

function isControlCapableWidget(widget) {
    return widget?.type === "number" || widget?.type === "combo";
}

function getControlRestoreValues(node, previousControlValues = []) {
    const savedControlValues = Array.isArray(node.widgets_values)
        ? node.widgets_values.slice(1)
        : [];
    const linkedControlValues = getFirstLinkedControlValues(node);
    return previousControlValues.length
        ? previousControlValues
        : savedControlValues.length
            ? savedControlValues
            : linkedControlValues;
}

function configureControlWidgets(node, controlWidgets, restoreValues = []) {
    for (let index = 0; index < controlWidgets.length; index += 1) {
        const controlWidget = controlWidgets[index];
        if (restoreValues[index] !== undefined) {
            controlWidget.value = restoreValues[index];
        }

        if (controlWidget.__lx_meta_callback_wrapped) continue;

        const originalCallback = controlWidget.callback;
        controlWidget.callback = (...args) => {
            const result = originalCallback?.apply(controlWidget, args);
            node.applyToGraph?.();
            return result;
        };
        controlWidget.__lx_meta_callback_wrapped = true;
    }
}

function addValueControlsToWidget(node, widget, spec, previousControlValues = []) {
    const existingControlWidgets = getLinkedWidgets(widget);
    const hasControlSpec = Boolean(spec?.[1]?.control_after_generate);
    if (!isControlCapableWidget(widget) || (!hasControlSpec && !existingControlWidgets.length)) return;

    const restoreValues = getControlRestoreValues(node, previousControlValues);
    if (existingControlWidgets.length) {
        configureControlWidgets(node, existingControlWidgets, restoreValues);
        return;
    }

    if (typeof addValueControlWidgets !== "function") return;

    const defaultValue = restoreValues[0] ?? getDefaultControlValue(spec);
    const controlWidgets = addValueControlWidgets(node, widget, defaultValue, undefined, spec) || [];
    if (!controlWidgets.length) return;

    widget.linkedWidgets = controlWidgets;
    configureControlWidgets(node, controlWidgets, restoreValues);
}

function syncLinkedControlWidgets(sourceWidget, targetNode, targetWidget) {
    const sourceControls = getLinkedWidgets(sourceWidget);
    const targetControls = getLinkedWidgets(targetWidget);
    const count = Math.min(sourceControls.length, targetControls.length);

    for (let index = 0; index < count; index += 1) {
        const sourceControl = sourceControls[index];
        const targetControl = targetControls[index];
        const oldValue = targetControl.value;
        const nextValue = sourceControl.value;
        if (oldValue === nextValue) continue;

        targetControl.value = nextValue;
        targetControl.callback?.(
            nextValue,
            app.canvas,
            targetNode,
            app.canvas?.graph_mouse,
            {},
        );
        targetNode.onWidgetChanged?.(targetControl.name, nextValue, oldValue, targetControl);
    }
}

app.registerExtension({
    name: "LX.MetaNode",

    beforeRegisterVueAppNodeDefs(nodeDefs) {
        const nodeDef = nodeDefs?.find((def) => def?.name === NODE_TYPE);
        if (!nodeDef) return;

        nodeDef.display_name = NODE_TITLE;
        nodeDef.description = NODE_DESCRIPTION;
        nodeDef.category = NODE_CATEGORY;
        nodeDef.search_aliases = SEARCH_ALIASES;
    },

    registerCustomNodes() {
        const LiteGraph = globalThis.LiteGraph;
        const LGraphNode = globalThis.LGraphNode || LiteGraph?.LGraphNode;
        if (!LiteGraph || !LGraphNode || !ComfyWidgets) return;

        class LXMetaNode extends LGraphNode {
            static title = NODE_TITLE;
            static category = NODE_CATEGORY;
            static collapsable = true;
            static title_mode = LiteGraph.NORMAL_TITLE;
            static comfyClass = NODE_TYPE;
            static nodeData = createNodeData();

            constructor(title) {
                const displayTitle = getDisplayTitle(title);
                super(displayTitle);
                this.title = displayTitle;
                this.addOutput(DEFAULT_OUTPUT_NAME, "*");
                this.serialize_widgets = true;
                this.isVirtualNode = true;
                this.__lx_meta_spec = null;
                this.resetToInitialState();
            }

            getValueWidget() {
                return this.widgets?.find((widget) => widget?.name === VALUE_WIDGET_NAME) || null;
            }

            resetToInitialState() {
                if (typeof this.title !== "string") this.title = NODE_TITLE;
                if (!this.outputs?.length) this.addOutput(DEFAULT_OUTPUT_NAME, "*");
                this.outputs[0].type = "*";
                this.outputs[0].name = DEFAULT_OUTPUT_NAME;
                if (!this.outputs[0].links?.length) this.outputs[0].links = null;
                this.__lx_meta_spec = null;
                this.removeValueWidgets();
                this.widgets_values = [];
                setNodeSize(this);
            }

            clone() {
                const node = LiteGraph.createNode(NODE_TYPE);
                if (!node) return null;

                node.pos = [...(this.pos || [0, 0])];
                node.resetToInitialState?.();
                return node;
            }

            onConfigure(info) {
                if (info?.title !== undefined) {
                    this.title = getDisplayTitle(info.title);
                } else if (typeof this.title !== "string") {
                    this.title = NODE_TITLE;
                }
                if (!this.outputs?.[0]?.links?.length) {
                    this.resetToInitialState();
                }
            }

            applyToGraph(extraLinks = []) {
                const valueWidget = this.getValueWidget();
                if (!valueWidget || !this.graph) return;

                const links = getLinksForOutput(this, extraLinks);
                for (const link of links) {
                    const targetNode = this.graph.getNodeById(link.target_id);
                    const input = targetNode?.inputs?.[link.target_slot];
                    if (!targetNode || !input) continue;

                    const targetWidget = getTargetWidget(targetNode, input);
                    if (!targetWidget) continue;

                    const targetSpec = findNodeInputSpec(targetNode, input) || this.__lx_meta_spec;
                    const oldValue = targetWidget.value;
                    const nextValue = coerceValue(valueWidget.value, targetSpec, targetWidget);
                    targetWidget.value = nextValue;
                    targetWidget.callback?.(
                        nextValue,
                        app.canvas,
                        targetNode,
                        app.canvas?.graph_mouse,
                        {},
                    );
                    targetNode.onWidgetChanged?.(targetWidget.name, nextValue, oldValue, targetWidget);
                    syncLinkedControlWidgets(valueWidget, targetNode, targetWidget);
                }
            }

            refreshComboInNode() {
                this.recreateWidget(true);
            }

            onAfterGraphConfigured() {
                if (this.outputs?.[0]?.links?.length && !this.widgets?.length) {
                    this.recreateWidget(true);
                    const saved = this.widgets_values;
                    const widget = this.getValueWidget();
                    if (widget && Array.isArray(saved) && saved.length) {
                        widget.value = coerceValue(saved[0], this.__lx_meta_spec, widget);
                    }
                    this.applyToGraph();
                }
            }

            onConnectionsChange(_type, _index, connected) {
                if (app.configuringGraph) return;
                if (connected || this.outputs?.[0]?.links?.length) {
                    this.recreateWidget(true);
                    this.applyToGraph();
                } else {
                    this.onLastDisconnect();
                }
            }

            onConnectOutput(slot, _type, input, targetNode, targetSlot) {
                if (slot !== 0) return false;
                const inputSpec = findNodeInputSpec(targetNode, input);
                if (!inputSpec) return false;

                const pendingLink = {
                    target_id: targetNode.id,
                    target_slot: targetSlot,
                };
                const specs = this.collectLinkedSpecs([pendingLink]);
                return !!mergeInputSpecs(specs);
            }

            collectLinkedSpecs(extraLinks = []) {
                if (!this.graph) return [];
                const links = getLinksForOutput(this, extraLinks);
                const specs = [];
                for (const link of links) {
                    const targetNode = this.graph.getNodeById(link.target_id);
                    const input = targetNode?.inputs?.[link.target_slot];
                    const spec = findNodeInputSpec(targetNode, input);
                    if (spec) specs.push(spec);
                }
                return specs;
            }

            recreateWidget(keepValue = false) {
                const previousWidget = this.getValueWidget();
                const previousValue = previousWidget?.value;
                const previousControlValues = getLinkedWidgetValues(previousWidget);
                const previousSize = [...(this.size || getInitialNodeSize(this))];
                const spec = mergeInputSpecs(this.collectLinkedSpecs());

                if (!spec) {
                    this.onLastDisconnect();
                    return null;
                }

                this.removeValueWidgets();
                this.__lx_meta_spec = spec;

                const type = getSpecType(spec);
                this.outputs[0].type = type;
                this.outputs[0].name = type;

                let created;
                if (isValidWidgetType(type) && ComfyWidgets[type]) {
                    created = ComfyWidgets[type](this, VALUE_WIDGET_NAME, spec, app);
                } else {
                    created = { widget: this.addWidget(type, VALUE_WIDGET_NAME, null, () => {}, {}) };
                }

                const widget = created?.widget || this.getValueWidget();
                if (!widget) return null;

                addValueControlsToWidget(this, widget, spec, previousControlValues);

                const linkedValue = getFirstLinkedWidgetValue(this);
                const targetValue = keepValue && previousValue !== undefined
                    ? previousValue
                    : linkedValue ?? spec?.[1]?.default ?? widget.value;
                widget.value = coerceValue(targetValue, spec, widget);

                const originalCallback = widget.callback;
                widget.callback = (...args) => {
                    const result = originalCallback?.apply(widget, args);
                    this.applyToGraph();
                    return result;
                };

                setNodeSizeToWidgets(this, previousSize[0], previousSize[1]);
                return widget;
            }

            removeValueWidgets() {
                if (!this.widgets) return;
                for (const widget of this.widgets) {
                    widget.onRemove?.();
                }
                this.widgets.length = 0;
            }

            onLastDisconnect() {
                this.resetToInitialState();
            }
        }

        const nodeData = createNodeData();
        LiteGraph.registerNodeType(
            NODE_TYPE,
            Object.assign(LXMetaNode, {
                title: NODE_TITLE,
                display_name: NODE_TITLE,
                comfyClass: NODE_TYPE,
                nodeData,
                category: NODE_CATEGORY,
                title_mode: LiteGraph.NORMAL_TITLE,
                collapsable: true,
            }),
        );
        LXMetaNode.category = NODE_CATEGORY;
    },
});
