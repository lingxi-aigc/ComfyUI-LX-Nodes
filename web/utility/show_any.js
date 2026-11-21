import { app } from "../../../../scripts/app.js";
import { api } from "../../../../scripts/api.js";
import { ComfyWidgets } from "../../../../scripts/widgets.js";

const SHOW_ANY_NODE_NAME = "LXShowAny";
const SHOW_TEXT_NODE_NAME = "LXShowText";
const NODE_NAMES = new Set([SHOW_ANY_NODE_NAME, SHOW_TEXT_NODE_NAME]);
const WIDGET_NAME = "__lx_show_any_text";
const DISPLAY_WIDGET_PREFIX = "text_";
const MIN_WIDTH = 160;
const MIN_HEIGHT = 30;
const SAVED_WIDGET_VALUES = Symbol("lx_show_saved_widget_values");
const SHOW_ANY_MENU_LABEL = "展示任意";
const SHOW_TEXT_MENU_LABEL = "展示文本";
const MENU_LABEL_PATCH_FLAG = "__lx_show_menu_label_patch";
const SHOW_ANY_RECOMMENDED_TYPES = [
    "*",
    "STRING",
    "IMAGE",
    "MASK",
    "LATENT",
    "CONDITIONING",
    "MODEL",
    "CLIP",
    "VAE",
    "CONTROL_NET",
    "STYLE_MODEL",
    "CLIP_VISION",
    "GLIGEN",
    "UPSCALE_MODEL",
    "AUDIO",
    "VIDEO",
    "LIST",
    "BOOLEAN",
    "INT",
    "FLOAT",
];
const CONNECTION_SHORTCUTS = [
    {
        node: SHOW_ANY_NODE_NAME,
        label: SHOW_ANY_MENU_LABEL,
        types: SHOW_ANY_RECOMMENDED_TYPES,
        includeExistingTypes: true,
    },
    {
        node: SHOW_TEXT_NODE_NAME,
        label: SHOW_TEXT_MENU_LABEL,
        types: ["STRING"],
    },
];

function getShortcutForDefaultNodeItem(value) {
    return CONNECTION_SHORTCUTS.find((shortcut) => (
        value === shortcut.node ||
        value?.node === shortcut.node ||
        value?.value === shortcut.node
    ));
}

function getShortcutByNodeName(nodeName) {
    return CONNECTION_SHORTCUTS.find((shortcut) => shortcut.node === nodeName);
}

function createDefaultNodeItem(shortcut) {
    return {
        content: shortcut.label,
        value: shortcut.node,
        node: shortcut.node,
    };
}

function prioritizeDefaultOutputNode(defaults, type, shortcut) {
    if (!defaults || !type) return;
    const values = Array.isArray(defaults[type]) ? defaults[type] : [];
    defaults[type] = [
        createDefaultNodeItem(shortcut),
        ...values.filter((value) => getShortcutForDefaultNodeItem(value)?.node !== shortcut.node),
    ];
}

function registerConnectionShortcuts() {
    const defaults = globalThis.LiteGraph?.slot_types_default_out;
    if (!defaults) return;

    for (const shortcut of [...CONNECTION_SHORTCUTS].reverse()) {
        for (const type of shortcut.types) {
            prioritizeDefaultOutputNode(defaults, type, shortcut);
        }
        if (shortcut.includeExistingTypes) {
            for (const type of Object.keys(defaults)) {
                prioritizeDefaultOutputNode(defaults, type, shortcut);
            }
        }
    }
}

function scheduleConnectionShortcuts() {
    for (const delay of [0, 250, 500, 1000, 2000]) {
        setTimeout(registerConnectionShortcuts, delay);
    }
}

function patchMenuLabels() {
    const contextMenu = globalThis.LiteGraph?.ContextMenu;
    const prototype = contextMenu?.prototype;
    if (!prototype?.addItem || prototype[MENU_LABEL_PATCH_FLAG]) return;

    const addItem = prototype.addItem;
    prototype[MENU_LABEL_PATCH_FLAG] = true;
    prototype.addItem = function (name, value, options) {
        const shortcut = getShortcutByNodeName(name) || getShortcutForDefaultNodeItem(value);
        const displayName = shortcut ? shortcut.label : name;
        return addItem.call(this, displayName, value, options);
    };
}

function applyImagesToNode(node, payload) {
    const records = [];
    for (const item of payload.images || []) {
        const img = new Image();
        img.onload = () => app.graph?.setDirtyCanvas(true, false);
        img.onerror = () => app.graph?.setDirtyCanvas(true, false);
        img.src = api.apiURL(
            `/view?filename=${encodeURIComponent(item.filename || "")}` +
            `&type=${encodeURIComponent(item.type || "temp")}` +
            `&subfolder=${encodeURIComponent(item.subfolder || "")}` +
            `&no-cache=${Date.now()}`
        );
        records.push(img);
    }
    node.imgs = records;
    if (typeof node.imageIndex !== "number" || node.imageIndex >= records.length) {
        node.imageIndex = 0;
    }
    node.onResize?.(node.size);
    node.setDirtyCanvas?.(true, false);
}

function removeTextWidget(node) {
    if (!Array.isArray(node.widgets)) return;
    for (let index = node.widgets.length - 1; index >= 0; index -= 1) {
        const widget = node.widgets[index];
        const isDisplayWidget =
            widget?.name === WIDGET_NAME ||
            widget?.__lx_show_display === true ||
            String(widget?.name || "").startsWith(DISPLAY_WIDGET_PREFIX);
        if (!isDisplayWidget) continue;
        node.widgets.splice(index, 1);
        widget?.onRemove?.();
    }
}

function isTextDisplayWidget(widget) {
    return (
        widget?.name === WIDGET_NAME ||
        widget?.__lx_show_display === true ||
        String(widget?.name || "").startsWith(DISPLAY_WIDGET_PREFIX)
    );
}

function getTextWidgets(node) {
    if (!Array.isArray(node.widgets)) return [];
    return node.widgets.filter(isTextDisplayWidget);
}

function removeImages(node) {
    node.imgs = [];
    node.imageIndex = 0;
}

function setWidgetText(widget, value) {
    if (!widget) return;
    widget.value = value ?? "";
    if (widget.inputEl) {
        widget.inputEl.value = widget.value;
        widget.inputEl.readOnly = true;
        widget.inputEl.style.opacity = "0.6";
    }
}

function createTextWidget(node, index, value) {
    const result = ComfyWidgets["STRING"](
        node,
        `${DISPLAY_WIDGET_PREFIX}${index}`,
        ["STRING", { multiline: true }],
        app,
    );
    const widget = result?.widget || node.widgets?.find((w) => w?.name === `${DISPLAY_WIDGET_PREFIX}${index}`);
    if (widget) {
        widget.__lx_show_display = true;
        setWidgetText(widget, value);
    }
    return widget;
}

function normalizeTextLines(lines) {
    const source = Array.isArray(lines) ? lines : [lines];
    const values = [];
    for (const item of source) {
        const nested = Array.isArray(item) ? item : [item];
        for (const value of nested) {
            if (value == null) continue;
            const text = String(value);
            if (!text) continue;
            values.push(text);
        }
    }
    return values;
}

function refreshTextLayout(node) {
    requestAnimationFrame(() => {
        node.onResize?.(node.size);
        node.setDirtyCanvas?.(true, false);
        app.graph?.setDirtyCanvas(true, false);
    });
}

function applyTextToNode(node, lines) {
    removeImages(node);
    const values = normalizeTextLines(lines);
    const widgets = getTextWidgets(node);
    values.forEach((text, index) => {
        const widget = widgets[index] || createTextWidget(node, index, text);
        if (widget) {
            widget.name = `${DISPLAY_WIDGET_PREFIX}${index}`;
            widget.__lx_show_display = true;
            setWidgetText(widget, text);
        }
    });
    for (let index = widgets.length - 1; index >= values.length; index -= 1) {
        const widget = widgets[index];
        const widgetIndex = node.widgets?.indexOf(widget) ?? -1;
        if (widgetIndex >= 0) node.widgets.splice(widgetIndex, 1);
        widget?.onRemove?.();
    }
    refreshTextLayout(node);
}

function applyPayload(node, payload) {
    if (!payload) return;
    if (Array.isArray(payload.images) && payload.images.length) {
        removeTextWidget(node);
        applyImagesToNode(node, payload);
        return;
    }
    const lines = Array.isArray(payload.text) && payload.text.length ? payload.text : [""];
    applyTextToNode(node, lines);
}

function readPayload(message) {
    if (!message) return null;
    if (Array.isArray(message.images) || Array.isArray(message.text)) {
        return { images: message.images, text: message.text };
    }
    const wrapped = message.lx_show_any;
    if (Array.isArray(wrapped) && wrapped[0]) return wrapped[0];
    return wrapped || null;
}

app.registerExtension({
    name: "LX.TextTools.ShowAny",

    setup() {
        patchMenuLabels();
        scheduleConnectionShortcuts();
    },

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!NODE_NAMES.has(nodeData.name)) return;
        scheduleConnectionShortcuts();

        function resetNodeSize(node) {
            if (typeof node.setSize !== "function") return;
            node.setSize([
                Math.max(MIN_WIDTH, node.size?.[0] || MIN_WIDTH),
                MIN_HEIGHT,
            ]);
        }

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            removeTextWidget(this);
            removeImages(this);
            resetNodeSize(this);
            return result;
        };

        const configure = nodeType.prototype.configure;
        nodeType.prototype.configure = function (info) {
            this[SAVED_WIDGET_VALUES] = info?.widgets_values;
            return configure?.apply(this, arguments);
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = onConfigure?.apply(this, arguments);
            removeTextWidget(this);
            removeImages(this);
            const values = this[SAVED_WIDGET_VALUES];
            if (Array.isArray(values) && values.length) {
                requestAnimationFrame(() => applyTextToNode(this, values));
            }
            return result;
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);
            const payload = readPayload(message);
            if (payload) applyPayload(this, payload);
        };
    },
});
