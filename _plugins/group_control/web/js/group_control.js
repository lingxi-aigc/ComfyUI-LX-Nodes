/*
 * Drawing portions adapted from rgthree-comfy (MIT).
 * Copyright (c) 2023 Regis Gaughan, III (rgthree).
 * Modified for LX-Nodes group controls and localized widgets.
 * See NOTICE and licenses/rgthree-MIT.txt.
 */
import { app } from "../../../scripts/app.js";

const ZH = {
    CATEGORY: "\ud83c\udd7b\ud83c\udd87 \u7075\u7280/\u63a7\u5236\u7ec4\u8282\u70b9",
    SWITCH_TITLE: "\u7ec4\u63a7\u5f00\u5173",
    SENDER_TITLE: "\u7ec4\u72b6\u6001\u53d1\u9001",
    RECEIVER_TITLE: "\u7ec4\u72b6\u6001\u63a5\u6536",
    PORT_STATE: "REPEATER",
    ON: "\u5f00",
    OFF: "\u5173",
    MIXED: "\u6df7\u5408",
    BYPASS: "\u5ffd\u7565",
    MUTE: "\u7981\u7528",
    NOT_IN_GROUP: "\u672a\u5728\u7ec4\u5185",
    SENDING: "\u53d1\u9001",
    RECEIVING: "\u63a5\u6536",
    PROP_TITLE_FILTER: "\u6807\u9898\u8fc7\u6ee4",
    PROP_SORT_MODE: "\u6392\u5e8f\u65b9\u5f0f",
    PROP_CLOSE_MODE: "\u5173\u95ed\u65b9\u5f0f",
    PROP_TOGGLE_RULE: "\u5207\u6362\u89c4\u5219",
    PROP_SHOW_LOCATE: "\u663e\u793a\u5b9a\u4f4d\u6309\u94ae",
    PROP_TRANSFER_MODE: "\u4f20\u9012\u65b9\u5f0f",
    PROP_BROADCAST_NAME: "\u5e7f\u64ad\u540d\u79f0",
    PROP_RECEIVE_NAME: "\u63a5\u6536\u540d\u79f0",
    YES: "\u662f",
    NO: "\u5426",
    GROUP_CONTROL_PROPERTIES: "\u7ec4\u63a7\u5c5e\u6027",
    NOT_SET: "\u672a\u8bbe\u7f6e",
    SET_TITLE_FILTER: "\u8bbe\u7f6e\u6807\u9898\u8fc7\u6ee4",
};

const TYPE_SWITCH_CN = ZH.SWITCH_TITLE;
const TYPE_SENDER_CN = ZH.SENDER_TITLE;
const TYPE_RECEIVER_CN = ZH.RECEIVER_TITLE;
const GROUP_CONTROL_NODE_TYPES = new Set([
    TYPE_SWITCH_CN,
    TYPE_SENDER_CN,
    TYPE_RECEIVER_CN,
]);

const STATE_ON = "on";
const STATE_BYPASS = "bypass";
const STATE_MUTE = "mute";
const STATE_MIXED = "mixed";

const MODE_LINE = "line";
const MODE_BROADCAST = "broadcast";

const CLOSE_FOLLOW = "follow";
const CLOSE_BYPASS = "bypass";
const CLOSE_MUTE = "mute";

const RULE_NORMAL = "normal";
const RULE_MAX_ONE = "max_one";
const RULE_ALWAYS_ONE = "always_one";

const SORT_POSITION = "position";
const SORT_TITLE = "title";

const GROUP_STATE_TYPE = "GROUP_STATE";
const TICK_MS = 300;
const ROW_HEIGHT = 28;
const STATUS_HEIGHT = 24;
const SWITCH_VERTICAL_PADDING = 12;
const SWITCH_ROW_GAP = 6;
const SWITCH_MIN_WIDTH = 230;
const SWITCH_MAX_AUTO_WIDTH = 420;
const SENDER_MIN_HEIGHT = 52 + STATUS_HEIGHT;
const RECEIVER_MIN_HEIGHT = 58 + STATUS_HEIGHT;
const GROUP_STATE_ACTIVE_COLOR = "#f5c542";
const GROUP_STATE_INACTIVE_COLOR = "#666";

const STATE_LABELS = {
    [STATE_ON]: ZH.ON,
    [STATE_BYPASS]: ZH.BYPASS,
    [STATE_MUTE]: ZH.MUTE,
    [STATE_MIXED]: ZH.MIXED,
};

const PROPERTY_META = {
    titleFilter: { label: ZH.PROP_TITLE_FILTER, type: "string" },
    sortMode: { label: ZH.PROP_SORT_MODE, type: "enum", values: [SORT_POSITION, SORT_TITLE] },
    closeMode: { label: ZH.PROP_CLOSE_MODE, type: "enum", values: [CLOSE_BYPASS, CLOSE_MUTE] },
    toggleRule: { label: ZH.PROP_TOGGLE_RULE, type: "enum", values: [RULE_NORMAL, RULE_MAX_ONE, RULE_ALWAYS_ONE] },
    showLocate: { label: ZH.PROP_SHOW_LOCATE, type: "boolean" },
    transferMode: { label: ZH.PROP_TRANSFER_MODE, type: "enum", values: [MODE_LINE, MODE_BROADCAST] },
    broadcastName: { label: ZH.PROP_BROADCAST_NAME, type: "string" },
    receiveName: { label: ZH.PROP_RECEIVE_NAME, type: "string" },
};

const PROPERTY_VALUE_LABELS = {
    [SORT_POSITION]: "\u6309\u4f4d\u7f6e",
    [SORT_TITLE]: "\u6309\u6807\u9898",
    [CLOSE_FOLLOW]: "\u8ddf\u968f\u53d1\u9001",
    [CLOSE_BYPASS]: "\u5ffd\u7565",
    [CLOSE_MUTE]: "\u7981\u7528",
    [RULE_NORMAL]: "\u666e\u901a",
    [RULE_MAX_ONE]: "\u6700\u591a\u6253\u5f00\u4e00\u4e2a",
    [RULE_ALWAYS_ONE]: "\u59cb\u7ec8\u4fdd\u7559\u4e00\u4e2a",
    [MODE_LINE]: "\u8fde\u7ebf",
    [MODE_BROADCAST]: "\u5e7f\u64ad\u540d\u79f0",
};

function modeForState(state) {
    if (state === STATE_BYPASS) return 4;
    if (state === STATE_MUTE) return LiteGraph.NEVER;
    return LiteGraph.ALWAYS;
}

function stateForCloseMode(closeMode) {
    return closeMode === CLOSE_MUTE ? STATE_MUTE : STATE_BYPASS;
}

function stateForTransfer(state) {
    return state === STATE_MIXED ? STATE_ON : state;
}

function valueIn(value, values, fallback) {
    return values.includes(value) ? value : fallback;
}

function defineProperty(node, name, defaultValue, type, extraInfo = {}) {
    node.properties ??= {};
    node.properties[name] ??= defaultValue;
    const info = { ...(PROPERTY_META[name] || {}), ...extraInfo, type };
    if (typeof node.addProperty === "function" && !node.properties_info?.[name]) {
        node.addProperty(name, node.properties[name], type, info);
    } else {
        node.properties_info ??= {};
        node.properties_info[name] = { ...(node.properties_info[name] || {}), ...info };
    }
}

function setNodeProperty(node, name, value) {
    const previousValue = node.properties?.[name];
    node.properties ??= {};
    node.properties[name] = value;
    node.onPropertyChanged?.(name, value, previousValue);
}

function formatPropertyValue(value) {
    if (typeof value === "boolean") return value ? ZH.YES : ZH.NO;
    if (value == null || value === "") return ZH.NOT_SET;
    return PROPERTY_VALUE_LABELS[value] || String(value);
}

function makeEnumPropertyMenu(node, name, label, values) {
    const current = node.properties?.[name];
    return {
        content: `${label}: ${formatPropertyValue(current)}`,
        has_submenu: true,
        submenu: {
            options: values.map((value) => ({
                content: `${value === current ? "\u2713 " : ""}${formatPropertyValue(value)}`,
                callback: () => setNodeProperty(node, name, value),
            })),
        },
    };
}

function makeBooleanPropertyMenu(node, name, label) {
    return makeEnumPropertyMenu(node, name, label, [true, false]);
}

function showTextPropertyEditor(node, name, label, event) {
    document.querySelectorAll(".lx-group-control-text-editor").forEach((element) => element.remove());

    const root = document.createElement("div");
    root.className = "lx-group-control-text-editor";
    Object.assign(root.style, {
        position: "fixed",
        zIndex: 10000,
        minWidth: "260px",
        padding: "10px",
        borderRadius: "6px",
        border: "1px solid #4b4b4b",
        background: "#1f1f1f",
        color: "#ddd",
        boxShadow: "0 8px 24px rgba(0, 0, 0, 0.35)",
        font: "13px Arial, sans-serif",
    });

    const title = document.createElement("div");
    title.textContent = label;
    Object.assign(title.style, {
        marginBottom: "8px",
        color: "#f0f0f0",
        fontWeight: "600",
    });

    const input = document.createElement("input");
    input.value = node.properties?.[name] ?? "";
    Object.assign(input.style, {
        boxSizing: "border-box",
        width: "100%",
        height: "28px",
        marginBottom: "10px",
        padding: "4px 7px",
        borderRadius: "4px",
        border: "1px solid #555",
        outline: "none",
        background: "#111",
        color: "#fff",
    });

    const buttons = document.createElement("div");
    Object.assign(buttons.style, {
        display: "flex",
        justifyContent: "flex-end",
        gap: "6px",
    });

    const close = () => {
        document.removeEventListener("mousedown", onOutsideMouseDown, true);
        root.remove();
    };
    const commit = (value = input.value) => {
        setNodeProperty(node, name, String(value || "").trim());
        close();
    };
    const makeButton = (text, callback, primary = false) => {
        const button = document.createElement("button");
        button.textContent = text;
        Object.assign(button.style, {
            height: "26px",
            padding: "0 10px",
            borderRadius: "4px",
            border: primary ? "1px solid #5f8fd6" : "1px solid #555",
            background: primary ? "#3d66a3" : "#2b2b2b",
            color: "#fff",
            cursor: "pointer",
        });
        button.addEventListener("mousedown", (buttonEvent) => buttonEvent.stopPropagation());
        button.addEventListener("click", callback);
        return button;
    };

    const onOutsideMouseDown = (mouseEvent) => {
        if (!root.contains(mouseEvent.target)) close();
    };

    input.addEventListener("keydown", (keyEvent) => {
        if (keyEvent.key === "Enter") {
            keyEvent.preventDefault();
            commit();
        } else if (keyEvent.key === "Escape") {
            keyEvent.preventDefault();
            close();
        }
    });
    root.addEventListener("mousedown", (mouseEvent) => mouseEvent.stopPropagation());
    root.append(title, input, buttons);
    buttons.append(
        makeButton("\u6e05\u7a7a", () => commit("")),
        makeButton("\u53d6\u6d88", close),
        makeButton("\u786e\u5b9a", () => commit(), true),
    );
    document.body.appendChild(root);

    const x = event?.clientX ?? window.innerWidth * 0.5;
    const y = event?.clientY ?? window.innerHeight * 0.5;
    const rect = root.getBoundingClientRect();
    root.style.left = `${Math.max(8, Math.min(x, window.innerWidth - rect.width - 8))}px`;
    root.style.top = `${Math.max(8, Math.min(y, window.innerHeight - rect.height - 8))}px`;

    setTimeout(() => document.addEventListener("mousedown", onOutsideMouseDown, true), 0);
    input.focus();
    input.select();
}

function makeTextPropertyMenu(node, name, label, promptLabel) {
    return {
        content: `${label}: ${formatPropertyValue(node.properties?.[name])}`,
        callback: (_value, _options, event) => showTextPropertyEditor(node, name, promptLabel || label, event),
    };
}

function isDefaultPropertiesMenu(option) {
    const content = String(option?.content || "");
    if (!content) return false;
    if (content.includes("\u5c5e\u6027\u9762\u677f")) return false;
    return content === "\u5c5e\u6027" || /^properties$/i.test(content);
}

function removeDefaultPropertiesMenu(options) {
    const index = options.findIndex(isDefaultPropertiesMenu);
    if (index >= 0) {
        options.splice(index, 1);
        if (options[index] === null && options[index - 1] === null) {
            options.splice(index, 1);
        }
    }
}

function addGroupControlPropertiesMenu(options, propertyOptions) {
    removeDefaultPropertiesMenu(options);
    if (!propertyOptions?.length) return;
    options.push(null);
    options.push({
        content: ZH.GROUP_CONTROL_PROPERTIES,
        has_submenu: true,
        submenu: { options: propertyOptions },
    });
}

function markDirty(node, foreground = true, background = true) {
    node?.graph?.setDirtyCanvas?.(foreground, background);
    app.canvas?.setDirty?.(foreground, background);
}

function getNodeId(node) {
    return String(node?.id ?? "");
}

function isGroupControlNode(node) {
    return node?.isGroupControlNode === true || GROUP_CONTROL_NODE_TYPES.has(String(node?.type || ""));
}

function getGraphGroups(graph) {
    return [...(graph?._groups || graph?.groups || [])];
}

function getGraphNodes(graph) {
    return [...(graph?._nodes || graph?.nodes || [])];
}

function getGroupBounds(group) {
    const bounding = group?._bounding;
    if (bounding && Number.isFinite(Number(bounding[2])) && Number(bounding[2]) > 0) {
        return [Number(bounding[0]), Number(bounding[1]), Number(bounding[2]), Number(bounding[3])];
    }

    const pos = group?._pos || group?.pos || [0, 0];
    const size = group?._size || group?.size || [0, 0];
    return [Number(pos[0] || 0), Number(pos[1] || 0), Number(size[0] || 0), Number(size[1] || 0)];
}

function getNodeCenter(node) {
    const pos = node?.pos || [0, 0];
    const size = node?.size || [0, 0];
    return [
        Number(pos[0] || 0) + Number(size[0] || 0) / 2,
        Number(pos[1] || 0) + Number(size[1] || 0) / 2,
    ];
}

function pointInBounds(point, bounds) {
    return point[0] >= bounds[0] &&
        point[0] < bounds[0] + bounds[2] &&
        point[1] >= bounds[1] &&
        point[1] < bounds[1] + bounds[3];
}

function groupArea(group) {
    const bounds = getGroupBounds(group);
    return Math.max(0, bounds[2]) * Math.max(0, bounds[3]);
}

function findGroupContainingNode(node) {
    const graph = node?.graph;
    const center = getNodeCenter(node);
    return getGraphGroups(graph)
        .filter((group) => pointInBounds(center, getGroupBounds(group)))
        .sort((a, b) => groupArea(a) - groupArea(b))[0] || null;
}

function getNodesInsideGroup(group) {
    group?.recomputeInsideNodes?.();
    if (group?._children) {
        return [...group._children].filter((item) => item instanceof LGraphNode);
    }

    const graph = group?.graph;
    const bounds = getGroupBounds(group);
    return getGraphNodes(graph).filter((node) => pointInBounds(getNodeCenter(node), bounds));
}

function expandNodeTree(nodes) {
    const result = [];
    const stack = [...nodes];
    while (stack.length) {
        const node = stack.pop();
        if (!node) continue;
        result.push(node);
        if (node.isSubgraphNode?.() && node.subgraph?.nodes?.length) {
            for (let i = node.subgraph.nodes.length - 1; i >= 0; i--) {
                stack.push(node.subgraph.nodes[i]);
            }
        }
    }
    return result;
}

function getControllableGroupNodes(group) {
    return expandNodeTree(getNodesInsideGroup(group)).filter((node) => !isGroupControlNode(node));
}

function readGroupState(group) {
    const nodes = getControllableGroupNodes(group);
    if (!nodes.length) return STATE_ON;

    const firstMode = nodes[0].mode ?? LiteGraph.ALWAYS;
    const allSame = nodes.every((node) => (node.mode ?? LiteGraph.ALWAYS) === firstMode);
    if (!allSame) return STATE_MIXED;
    if (firstMode === 4) return STATE_BYPASS;
    if (firstMode === LiteGraph.NEVER) return STATE_MUTE;
    return STATE_ON;
}

function setGroupState(group, state, options = {}) {
    const mode = modeForState(state);
    const graph = group?.graph;
    graph?.beforeChange?.();
    try {
        for (const node of getControllableGroupNodes(group)) {
            node.mode = mode;
        }
    } finally {
        graph?.afterChange?.();
    }
    graph?.change?.();
    graph?.setDirtyCanvas?.(true, false);
    if (options.notify !== false) {
        service.syncSendersForGroup(group);
        service.requestTick();
    }
}

function fitText(ctx, text, maxWidth) {
    const value = String(text || "");
    if (maxWidth <= 0) return "";
    if (ctx.measureText(value).width <= maxWidth) return value;
    let left = value;
    while (left.length > 1 && ctx.measureText(`${left}...`).width > maxWidth) {
        left = left.slice(0, -1);
    }
    return `${left}...`;
}

function isLowQualityCanvas() {
    return ((app.canvas?.ds?.scale || 1) <= 0.5);
}

function drawRgNodeWidget(ctx, options) {
    const lowQuality = isLowQualityCanvas();
    const data = {
        width: options.size[0],
        height: options.size[1],
        posY: options.pos[1],
        lowQuality,
        margin: 15,
        colorOutline: LiteGraph.WIDGET_OUTLINE_COLOR,
        colorBackground: LiteGraph.WIDGET_BGCOLOR,
        colorText: LiteGraph.WIDGET_TEXT_COLOR,
        colorTextSecondary: LiteGraph.WIDGET_SECONDARY_TEXT_COLOR,
    };

    ctx.strokeStyle = options.colorStroke || data.colorOutline;
    ctx.fillStyle = options.colorBackground || data.colorBackground;
    ctx.beginPath();
    roundedRect(ctx, data.margin, data.posY, data.width - data.margin * 2, data.height, lowQuality ? 0 : options.borderRadius || options.size[1] * 0.5);
    ctx.fill();
    if (!lowQuality) ctx.stroke();
    return data;
}

function roundedRect(ctx, x, y, width, height, radius) {
    if (ctx.roundRect) {
        ctx.roundRect(x, y, width, height, radius);
        return;
    }
    ctx.rect(x, y, width, height);
}

function getLinkById(graph, linkId) {
    if (!graph || linkId == null) return null;
    if (graph._links?.get) return graph._links.get(linkId);
    if (graph.links?.get) return graph.links.get(linkId);
    return graph._links?.[linkId] || graph.links?.[linkId] || null;
}

function getOutputTargetNodes(node, outputIndex = 0) {
    const output = node?.outputs?.[outputIndex];
    const links = output?.links || [];
    const targets = [];
    for (const linkId of links) {
        const link = getLinkById(node.graph, linkId);
        const targetId = link?.target_id ?? link?.targetId;
        const targetNode = targetId != null ? node.graph?.getNodeById?.(targetId) : null;
        if (targetNode) targets.push(targetNode);
    }
    return targets;
}

function locateGroup(group) {
    const canvas = app.canvas;
    if (!canvas || !group) return;
    const bounds = getGroupBounds(group);
    if (typeof canvas.centerOnNode === "function") {
        canvas.centerOnNode(group);
    } else if (canvas.ds?.offset) {
        const scale = canvas.ds.scale || 1;
        const rect = canvas.canvas?.getBoundingClientRect?.();
        const width = rect?.width || canvas.canvas?.width || 1200;
        const height = rect?.height || canvas.canvas?.height || 800;
        canvas.ds.offset[0] = -bounds[0] - bounds[2] / 2 + width / scale / 2;
        canvas.ds.offset[1] = -bounds[1] - bounds[3] / 2 + height / scale / 2;
    }
    canvas.setDirty?.(true, true);
}

function setSlotLabel(slot, label) {
    if (!slot) return;
    slot.name = label;
    slot.label = label;
    slot.localized_name = label;
}

function setRepeaterSlot(slot, label, options = {}) {
    setSlotLabel(slot, label);
    if (!slot) return;
    slot.color_on = GROUP_STATE_ACTIVE_COLOR;
    slot.color_off = options.inactiveColor || GROUP_STATE_INACTIVE_COLOR;
    if (options.arrow) {
        slot.shape = LiteGraph.ARROW_SHAPE;
    }
}

function ensureMinSize(node, minWidth, minHeight) {
    const width = Math.max(minWidth, Number(node?.size?.[0] || 0));
    const height = Math.max(minHeight, Number(node?.size?.[1] || 0));
    node.setSize?.([width, height]);
}

function drawGroupStatusSubtext(ctx, node, text) {
    if (node.flags?.collapsed) return;
    if (!text) return;

    ctx.save();
    ctx.textAlign = "left";
    ctx.textBaseline = "alphabetic";
    ctx.fillStyle = text === ZH.NOT_IN_GROUP ? "#d99a2b" : LiteGraph.WIDGET_SECONDARY_TEXT_COLOR;
    const oldFont = ctx.font;
    ctx.font = `${text === ZH.NOT_IN_GROUP ? "italic " : ""}${Math.max(10, (LiteGraph.NODE_SUBTEXT_SIZE || 14) - 2)}px Arial`;
    ctx.fillText(fitText(ctx, text, node.size[0] - 30), 15, node.size[1] - 7);
    ctx.font = oldFont;
    ctx.restore();
}

function getSwitchRowsHeight(rowCount) {
    return rowCount * ROW_HEIGHT + Math.max(0, rowCount - 1) * SWITCH_ROW_GAP;
}

function getSwitchRowsStartY(node, rows) {
    return SWITCH_VERTICAL_PADDING;
}

function getSwitchNaturalHeight(rows) {
    const rowCount = rows.length;
    return rowCount
        ? SWITCH_VERTICAL_PADDING * 2 + getSwitchRowsHeight(rowCount)
        : SWITCH_VERTICAL_PADDING;
}

function estimateTextWidth(text) {
    return [...String(text || "")].reduce((width, char) => width + (char.charCodeAt(0) > 127 ? 15 : 8), 0);
}

function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
}

function getSwitchNaturalWidth(node, rows) {
    const titleWidth = estimateTextWidth(node?.title || ZH.SWITCH_TITLE) + 86;
    const maxRowTitleWidth = rows.reduce((width, group) => {
        return Math.max(width, estimateTextWidth(group?.title || "(untitled)"));
    }, 0);
    const locateWidth = node.properties.showLocate !== false ? 36 : 0;
    const controlsWidth = 108 + locateWidth;
    return clamp(Math.ceil(Math.max(titleWidth, maxRowTitleWidth + controlsWidth)), SWITCH_MIN_WIDTH, SWITCH_MAX_AUTO_WIDTH);
}

function getSwitchNaturalSize(node, rows) {
    return [
        getSwitchNaturalWidth(node, rows),
        getSwitchNaturalHeight(rows),
    ];
}

function drawSwitchRow(ctx, node, group, rowY, rowHeight) {
    const state = readGroupState(group);
    const isOn = state === STATE_ON;
    const showLocate = node.properties.showLocate !== false;
    const nodeWidth = Math.max(1, Number(node?.size?.[0] || SWITCH_MIN_WIDTH));
    const widgetData = drawRgNodeWidget(ctx, { size: [nodeWidth, rowHeight], pos: [15, rowY] });
    let currentX = widgetData.width - widgetData.margin;

    ctx.save();
    ctx.beginPath();
    ctx.rect(0, rowY, nodeWidth, rowHeight);
    ctx.clip();

    if (!widgetData.lowQuality && showLocate) {
        currentX -= 7;
        const midY = widgetData.posY + widgetData.height * 0.5;
        ctx.fillStyle = ctx.strokeStyle = "#6fbf86";
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        const arrow = new Path2D(`M${currentX} ${midY} l -7 6 v -3 h -7 v -6 h 7 v -3 z`);
        ctx.fill(arrow);
        ctx.stroke(arrow);
        currentX -= 14;
        currentX -= 7;
        ctx.strokeStyle = widgetData.colorOutline;
        ctx.stroke(new Path2D(`M ${currentX} ${widgetData.posY} v ${widgetData.height}`));
    } else if (widgetData.lowQuality && showLocate) {
        currentX -= 28;
    }

    currentX -= 7;
    ctx.fillStyle = isOn ? "#6fbf86" : "#333";
    ctx.beginPath();
    const toggleRadius = rowHeight * 0.36;
    const toggleCenterX = currentX - toggleRadius;
    ctx.arc(toggleCenterX, rowY + rowHeight * 0.5, toggleRadius, 0, Math.PI * 2);
    ctx.fill();
    currentX -= toggleRadius * 2;

    if (!widgetData.lowQuality) {
        currentX -= 4;
        ctx.textAlign = "right";
        ctx.fillStyle = widgetData.colorTextSecondary;
        const stateLabel = isOn ? ZH.ON : ZH.OFF;
        const stateLabelWidth = Math.max(ctx.measureText(ZH.ON).width, ctx.measureText(ZH.OFF).width);
        const stateLabelRightX = currentX;
        ctx.fillText(stateLabel, stateLabelRightX, rowY + rowHeight * 0.7);
        currentX -= stateLabelWidth;
        currentX -= 7;
        ctx.textAlign = "left";
        ctx.fillStyle = isOn ? widgetData.colorText : widgetData.colorTextSecondary;
        const maxLabelWidth = widgetData.width - widgetData.margin - 10 - (widgetData.width - currentX);
        ctx.fillText(fitText(ctx, group.title || "(untitled)", maxLabelWidth), widgetData.margin + 10, rowY + rowHeight * 0.7);
    }

    ctx.restore();

    return {
        rowX: widgetData.margin,
        rowY: widgetData.posY,
        rowW: widgetData.width - widgetData.margin * 2,
        rowH: widgetData.height,
        locateX: widgetData.width - widgetData.margin - 28,
        locateY: widgetData.posY,
        locateW: showLocate ? 28 : 0,
        locateH: widgetData.height,
    };
}

class GroupControlService {
    constructor() {
        this.nodes = new Set();
        this.timer = null;
        this.raf = null;
    }

    add(node) {
        this.nodes.add(node);
        if (!this.timer) {
            this.timer = setInterval(() => this.tick(), TICK_MS);
        }
        this.requestTick();
        this.forceSenderSync();
    }

    remove(node) {
        this.nodes.delete(node);
        if (!this.nodes.size && this.timer) {
            clearInterval(this.timer);
            this.timer = null;
        }
        if (!this.nodes.size && this.raf) {
            cancelAnimationFrame(this.raf);
            this.raf = null;
        }
    }

    tick() {
        for (const node of [...this.nodes]) {
            if (!node.graph) continue;
            node.groupControlTick?.();
        }
    }

    requestTick() {
        if (this.raf) return;
        this.raf = requestAnimationFrame(() => {
            this.raf = null;
            this.tick();
        });
    }

    syncSendersForGroup(group) {
        if (!group) return;
        for (const node of [...this.nodes]) {
            if (!(node instanceof GroupStateSenderNode)) continue;
            if (!node.graph || node.graph !== group.graph) continue;
            if (node.detectGroup?.() !== group) continue;
            node.sendCurrentState?.(true);
        }
    }

    forceSenderSync() {
        for (const node of [...this.nodes]) {
            if (!(node instanceof GroupStateSenderNode)) continue;
            if (!node.graph) continue;
            node.sendCurrentState?.(true);
        }
    }

    broadcast(name, payload, sender) {
        const normalized = String(name || "").trim();
        if (!normalized) return;
        for (const node of [...this.nodes]) {
            if (node === sender) continue;
            if (!(node instanceof GroupStateReceiverNode)) continue;
            if (node.properties.transferMode !== MODE_BROADCAST) continue;
            if (String(node.properties.receiveName || "").trim() !== normalized) continue;
            node.receiveGroupState({ ...payload, channel: MODE_BROADCAST }, sender);
        }
    }
}

const service = new GroupControlService();

class GroupControlBaseNode extends LGraphNode {
    constructor(displayTitle) {
        super(displayTitle);
        this.displayTitle = displayTitle;
        this.title = displayTitle;
        this.isVirtualNode = true;
        this.isGroupControlNode = true;
        this.serialize_widgets = false;
        this.properties = this.properties || {};
    }

    syncDisplayTitle() {
        if (!this.title || this.title === this.type) {
            this.title = this.displayTitle;
        }
    }

    cleanupInternalProperties() {
        delete this.properties?.ue_properties;
        delete this.properties_info?.ue_properties;
    }

    onAdded() {
        service.add(this);
        this.cleanupInternalProperties();
        this.syncDisplayTitle();
    }

    onRemoved() {
        service.remove(this);
    }

    configure(info) {
        super.configure(info);
        this.ensureProperties?.();
        this.cleanupInternalProperties();
        this.syncDisplayTitle();
        this.afterConfigure?.();
    }

    onPropertyChanged(name, value, previousValue) {
        const nextValue = this.normalizeProperty?.(name, value) ?? value;
        this.properties[name] = nextValue;
        this.handlePropertyChanged?.(name, nextValue, previousValue);
        markDirty(this);
        return true;
    }

    onConnectionsChange(type, slotIndex, isConnected, linkInfo, ioSlot) {
        if (typeof super.onConnectionsChange === "function") {
            super.onConnectionsChange(type, slotIndex, isConnected, linkInfo, ioSlot);
        }
        this.lastPayloadKey = "";
        service.requestTick();
        service.forceSenderSync();
    }

    getExtraMenuOptions(canvas, options) {
        if (typeof super.getExtraMenuOptions === "function") {
            super.getExtraMenuOptions(canvas, options);
        }
        this.cleanupInternalProperties();
        addGroupControlPropertiesMenu(options, this.getGroupControlPropertyMenuOptions?.() || []);
    }

    relayLineState(payload) {
        const visited = new Set(payload.visited || []);
        visited.add(getNodeId(this));
        const nextPayload = { ...payload, channel: MODE_LINE, visited: [...visited] };
        for (const targetNode of getOutputTargetNodes(this, 0)) {
            if (typeof targetNode.receiveGroupState === "function") {
                targetNode.receiveGroupState(nextPayload, this);
            }
        }
    }
}

class GroupControlSwitchNode extends GroupControlBaseNode {
    constructor() {
        super(ZH.SWITCH_TITLE);
        this.comfyClass = TYPE_SWITCH_CN;
        this.lastRowsSignature = "";
        this.groupRows = [];
        this.rowHits = [];
        this.__userResizedHeight = false;
        this.ensureProperties();
        this.refreshRows();
    }

    ensureProperties() {
        defineProperty(this, "titleFilter", "", "string");
        defineProperty(this, "sortMode", SORT_POSITION, "enum", { values: [SORT_POSITION, SORT_TITLE] });
        defineProperty(this, "closeMode", CLOSE_BYPASS, "enum", { values: [CLOSE_BYPASS, CLOSE_MUTE] });
        defineProperty(this, "toggleRule", RULE_NORMAL, "enum", { values: [RULE_NORMAL, RULE_MAX_ONE, RULE_ALWAYS_ONE] });
        defineProperty(this, "showLocate", true, "boolean");
        this.properties.sortMode = valueIn(this.properties.sortMode, [SORT_POSITION, SORT_TITLE], SORT_POSITION);
        this.properties.closeMode = valueIn(this.properties.closeMode, [CLOSE_BYPASS, CLOSE_MUTE], CLOSE_BYPASS);
        this.properties.toggleRule = valueIn(this.properties.toggleRule, [RULE_NORMAL, RULE_MAX_ONE, RULE_ALWAYS_ONE], RULE_NORMAL);
        this.properties.showLocate = this.properties.showLocate !== false;
    }

    afterConfigure() {
        this.refreshRows(true);
    }

    normalizeProperty(name, value) {
        if (name === "sortMode") return valueIn(value, [SORT_POSITION, SORT_TITLE], SORT_POSITION);
        if (name === "closeMode") return valueIn(value, [CLOSE_BYPASS, CLOSE_MUTE], CLOSE_BYPASS);
        if (name === "toggleRule") return valueIn(value, [RULE_NORMAL, RULE_MAX_ONE, RULE_ALWAYS_ONE], RULE_NORMAL);
        if (name === "showLocate") return value !== false && value !== "false";
        if (name === "titleFilter") return String(value || "").trim();
        return value;
    }

    handlePropertyChanged(name) {
        if (["titleFilter", "sortMode", "showLocate"].includes(name)) {
            this.__userResizedHeight = false;
            this.refreshRows(true);
            return;
        }
        markDirty(this);
    }

    getGroupControlPropertyMenuOptions() {
        return [
            makeTextPropertyMenu(this, "titleFilter", ZH.PROP_TITLE_FILTER, ZH.SET_TITLE_FILTER),
            makeEnumPropertyMenu(this, "sortMode", ZH.PROP_SORT_MODE, [SORT_POSITION, SORT_TITLE]),
            makeEnumPropertyMenu(this, "closeMode", ZH.PROP_CLOSE_MODE, [CLOSE_BYPASS, CLOSE_MUTE]),
            makeEnumPropertyMenu(this, "toggleRule", ZH.PROP_TOGGLE_RULE, [RULE_NORMAL, RULE_MAX_ONE, RULE_ALWAYS_ONE]),
            makeBooleanPropertyMenu(this, "showLocate", ZH.PROP_SHOW_LOCATE),
        ];
    }

    getGroups() {
        const filter = String(this.properties.titleFilter || "").trim().toLocaleLowerCase();
        const groups = getGraphGroups(this.graph).filter((group) => {
            if (!filter) return true;
            return String(group.title || "").toLocaleLowerCase().includes(filter);
        });

        if (this.properties.sortMode === SORT_TITLE) {
            groups.sort((a, b) => String(a.title || "").localeCompare(String(b.title || "")));
        } else {
            groups.sort((a, b) => {
                const ab = getGroupBounds(a);
                const bb = getGroupBounds(b);
                const ay = Math.floor(ab[1] / 30);
                const by = Math.floor(bb[1] / 30);
                if (ay !== by) return ay - by;
                return Math.floor(ab[0] / 30) - Math.floor(bb[0] / 30);
            });
        }
        return groups;
    }

    getRowsSignature(groups) {
        const filter = String(this.properties.titleFilter || "");
        const sort = String(this.properties.sortMode || "");
        const locate = String(this.properties.showLocate !== false);
        return `${filter}::${sort}::${locate}::${groups.map((group) => {
            const bounds = getGroupBounds(group);
            return `${group.id ?? ""}:${group.title ?? ""}:${bounds.join(",")}`;
        }).join("|")}`;
    }

    refreshRows(forceSize = false) {
        const groups = this.getGroups();
        const signature = this.getRowsSignature(groups);
        if (!forceSize && signature === this.lastRowsSignature) {
            const minWidth = getSwitchNaturalWidth(this, groups);
            const naturalHeight = getSwitchNaturalHeight(groups);
            const nextWidth = Math.max(this.size?.[0] || 0, minWidth);
            const nextHeight = this.__userResizedHeight
                ? Math.max(this.size?.[1] || 0, naturalHeight)
                : naturalHeight;
            if (this.size?.[0] !== nextWidth || this.size?.[1] !== nextHeight) {
                this.setSwitchSize([nextWidth, nextHeight]);
            }
            markDirty(this, true, false);
            return;
        }

        this.lastRowsSignature = signature;
        this.__userResizedHeight = false;
        this.groupRows = groups;
        this.rowHits = [];
        this.widgets = [];
        const size = getSwitchNaturalSize(this, groups);
        size[0] = Math.max(this.size?.[0] || 0, size[0]);
        this.setSwitchSize(size);
        markDirty(this);
    }

    setSwitchSize(size) {
        this.__switchResizeGuard = true;
        try {
            this.setSize(size);
        } finally {
            this.__switchResizeGuard = false;
        }
    }

    onDrawForeground(ctx) {
        super.onDrawForeground?.(ctx);
        if (this.flags?.collapsed) return;

        const rows = this.groupRows || [];
        this.rowHits = [];
        if (!rows.length) return;

        let rowY = getSwitchRowsStartY(this, rows);
        for (const group of rows) {
            const hit = drawSwitchRow(ctx, this, group, rowY, ROW_HEIGHT);
            this.rowHits.push({ ...hit, group });
            rowY += ROW_HEIGHT + SWITCH_ROW_GAP;
        }
    }

    onMouseDown(event, pos) {
        if (event.button !== 0 || this.flags?.collapsed) return super.onMouseDown?.(event, pos);
        const showLocate = this.properties.showLocate !== false;
        const isInside = (point, hit, key) => (
            point[0] >= hit[`${key}X`] &&
            point[0] <= hit[`${key}X`] + hit[`${key}W`] &&
            point[1] >= hit[`${key}Y`] &&
            point[1] <= hit[`${key}Y`] + hit[`${key}H`]
        );

        for (const hit of this.rowHits || []) {
            if (showLocate && isInside(pos, hit, "locate")) {
                locateGroup(hit.group);
                return true;
            }

            if (isInside(pos, hit, "row")) {
                this.toggleGroup(hit.group);
                return true;
            }
        }

        return super.onMouseDown?.(event, pos);
    }

    onResize(size) {
        if (this.__switchResizeGuard) return;
        super.onResize?.(size);
        const rows = this.groupRows || [];
        if (!rows.length) return;
        this.__userResizedHeight = true;

        const minHeight = getSwitchNaturalHeight(rows);
        const minWidth = getSwitchNaturalWidth(this, rows);
        const nextWidth = Math.max(this.size?.[0] || 0, minWidth);
        const nextHeight = Math.max(this.size?.[1] || 0, minHeight);
        if (nextWidth === this.size?.[0] && nextHeight === this.size?.[1]) return;

        this.setSwitchSize([nextWidth, nextHeight]);
    }

    groupControlTick() {
        this.refreshRows(false);
    }

    closeState() {
        return stateForCloseMode(this.properties.closeMode);
    }

    toggleGroup(group) {
        const state = readGroupState(group);
        const nextState = state === STATE_ON ? this.closeState() : STATE_ON;
        const groups = this.getGroups();

        if (nextState === STATE_ON && this.properties.toggleRule !== RULE_NORMAL) {
            for (const otherGroup of groups) {
                if (otherGroup !== group) setGroupState(otherGroup, this.closeState());
            }
        }

        if (nextState !== STATE_ON && this.properties.toggleRule === RULE_ALWAYS_ONE) {
            const openGroups = groups.filter((candidate) => candidate !== group && readGroupState(candidate) === STATE_ON);
            if (!openGroups.length) {
                markDirty(this);
                return;
            }
        }

        setGroupState(group, nextState);
        markDirty(this);
    }

}

class GroupStateSenderNode extends GroupControlBaseNode {
    constructor() {
        super(ZH.SENDER_TITLE);
        this.comfyClass = TYPE_SENDER_CN;
        this.ensureProperties();
        this.addOutput(ZH.PORT_STATE, GROUP_STATE_TYPE, {
            color_on: GROUP_STATE_ACTIVE_COLOR,
            color_off: GROUP_STATE_ACTIVE_COLOR,
            shape: LiteGraph.ARROW_SHAPE,
        });
        setRepeaterSlot(this.outputs?.[0], ZH.PORT_STATE, { arrow: true, inactiveColor: GROUP_STATE_ACTIVE_COLOR });
        this.setSize([240, SENDER_MIN_HEIGHT]);
        this.lastPayloadKey = "";
        this.currentGroup = null;
    }

    ensureProperties() {
        defineProperty(this, "transferMode", MODE_LINE, "enum", { values: [MODE_LINE, MODE_BROADCAST] });
        defineProperty(this, "broadcastName", "default", "string");
        this.properties.transferMode = valueIn(this.properties.transferMode, [MODE_LINE, MODE_BROADCAST], MODE_LINE);
        this.properties.broadcastName = String(this.properties.broadcastName || "default").trim() || "default";
    }

    afterConfigure() {
        setRepeaterSlot(this.outputs?.[0], ZH.PORT_STATE, { arrow: true, inactiveColor: GROUP_STATE_ACTIVE_COLOR });
        ensureMinSize(this, 240, SENDER_MIN_HEIGHT);
    }

    normalizeProperty(name, value) {
        if (name === "transferMode") return valueIn(value, [MODE_LINE, MODE_BROADCAST], MODE_LINE);
        if (name === "broadcastName") return String(value || "default").trim() || "default";
        return value;
    }

    handlePropertyChanged(name) {
        if (["transferMode", "broadcastName"].includes(name)) {
            this.lastPayloadKey = "";
            this.sendCurrentState(true);
        }
    }

    getGroupControlPropertyMenuOptions() {
        return [
            makeEnumPropertyMenu(this, "transferMode", ZH.PROP_TRANSFER_MODE, [MODE_LINE, MODE_BROADCAST]),
            makeTextPropertyMenu(this, "broadcastName", ZH.PROP_BROADCAST_NAME, ZH.PROP_BROADCAST_NAME),
        ];
    }

    detectGroup() {
        this.currentGroup = findGroupContainingNode(this);
        return this.currentGroup;
    }

    groupControlTick() {
        this.sendCurrentState();
    }

    getPayloadKey(group, state) {
        const outputLinks = (this.outputs?.[0]?.links || []).join(",");
        return [
            this.properties.transferMode,
            this.properties.broadcastName,
            state,
            group?.id ?? "",
            group?.title ?? "",
            outputLinks,
        ].join("|");
    }

    sendCurrentState(force = false) {
        const group = this.detectGroup();
        if (!group) {
            this.lastPayloadKey = "";
            markDirty(this, true, false);
            return;
        }

        const state = stateForTransfer(readGroupState(group));
        const payload = {
            state,
            origin: getNodeId(this),
            senderType: TYPE_SENDER_CN,
            visited: [getNodeId(this)],
        };

        const payloadKey = this.getPayloadKey(group, state);
        if (!force && payloadKey === this.lastPayloadKey) {
            markDirty(this, true, false);
            return;
        }
        this.lastPayloadKey = payloadKey;
        if (this.properties.transferMode === MODE_BROADCAST) {
            service.broadcast(this.properties.broadcastName, payload, this);
        } else {
            this.relayLineState(payload);
        }
        markDirty(this, true, false);
    }

    getStatusText() {
        const group = this.currentGroup || this.detectGroup();
        if (!group) return ZH.NOT_IN_GROUP;
        return `${ZH.SENDING}\uff1a${STATE_LABELS[readGroupState(group)] || ZH.ON}`;
    }

    onDrawForeground(ctx) {
        drawGroupStatusSubtext(ctx, this, this.getStatusText());
    }

}

class GroupStateReceiverNode extends GroupControlBaseNode {
    constructor() {
        super(ZH.RECEIVER_TITLE);
        this.comfyClass = TYPE_RECEIVER_CN;
        this.ensureProperties();
        this.addInput(ZH.PORT_STATE, GROUP_STATE_TYPE);
        this.addOutput(ZH.PORT_STATE, GROUP_STATE_TYPE);
        setRepeaterSlot(this.inputs?.[0], ZH.PORT_STATE);
        setRepeaterSlot(this.outputs?.[0], ZH.PORT_STATE);
        this.setSize([260, RECEIVER_MIN_HEIGHT]);
        this.currentGroup = null;
        this.lastReceivedState = null;
    }

    ensureProperties() {
        defineProperty(this, "transferMode", MODE_LINE, "enum", { values: [MODE_LINE, MODE_BROADCAST] });
        defineProperty(this, "receiveName", "default", "string");
        defineProperty(this, "closeMode", CLOSE_FOLLOW, "enum", { values: [CLOSE_FOLLOW, CLOSE_BYPASS, CLOSE_MUTE] });
        this.properties.transferMode = valueIn(this.properties.transferMode, [MODE_LINE, MODE_BROADCAST], MODE_LINE);
        this.properties.receiveName = String(this.properties.receiveName || "default").trim() || "default";
        this.properties.closeMode = valueIn(this.properties.closeMode, [CLOSE_FOLLOW, CLOSE_BYPASS, CLOSE_MUTE], CLOSE_FOLLOW);
    }

    afterConfigure() {
        setRepeaterSlot(this.inputs?.[0], ZH.PORT_STATE);
        setRepeaterSlot(this.outputs?.[0], ZH.PORT_STATE);
        ensureMinSize(this, 260, RECEIVER_MIN_HEIGHT);
    }

    normalizeProperty(name, value) {
        if (name === "transferMode") return valueIn(value, [MODE_LINE, MODE_BROADCAST], MODE_LINE);
        if (name === "receiveName") return String(value || "default").trim() || "default";
        if (name === "closeMode") return valueIn(value, [CLOSE_FOLLOW, CLOSE_BYPASS, CLOSE_MUTE], CLOSE_FOLLOW);
        return value;
    }

    handlePropertyChanged(name) {
        if (["transferMode", "receiveName"].includes(name)) {
            service.forceSenderSync();
        }
    }

    getGroupControlPropertyMenuOptions() {
        return [
            makeEnumPropertyMenu(this, "transferMode", ZH.PROP_TRANSFER_MODE, [MODE_LINE, MODE_BROADCAST]),
            makeTextPropertyMenu(this, "receiveName", ZH.PROP_RECEIVE_NAME, ZH.PROP_RECEIVE_NAME),
            makeEnumPropertyMenu(this, "closeMode", ZH.PROP_CLOSE_MODE, [CLOSE_FOLLOW, CLOSE_BYPASS, CLOSE_MUTE]),
        ];
    }

    detectGroup() {
        this.currentGroup = findGroupContainingNode(this);
        return this.currentGroup;
    }

    groupControlTick() {
        this.detectGroup();
        markDirty(this, true, false);
    }

    stateToApply(incomingState) {
        if (incomingState === STATE_ON) return STATE_ON;
        if (this.properties.closeMode === CLOSE_MUTE) return STATE_MUTE;
        if (this.properties.closeMode === CLOSE_BYPASS) return STATE_BYPASS;
        return incomingState === STATE_MUTE ? STATE_MUTE : STATE_BYPASS;
    }

    receiveGroupState(payload) {
        const channel = payload.channel || MODE_LINE;
        if (this.properties.transferMode !== channel) return;

        const visited = new Set(payload.visited || []);
        const ownId = getNodeId(this);
        if (visited.has(ownId)) return;
        visited.add(ownId);

        const incomingState = payload.state || STATE_ON;
        this.lastReceivedState = incomingState;
        const group = this.detectGroup();
        if (group) {
            setGroupState(group, this.stateToApply(incomingState), { notify: false });
        }

        this.relayLineState({ ...payload, visited: [...visited] });
        markDirty(this);
    }

    getStatusText() {
        const group = this.currentGroup || this.detectGroup();
        if (!group) return ZH.NOT_IN_GROUP;
        const state = this.lastReceivedState || readGroupState(group);
        return `${ZH.RECEIVING}\uff1a${STATE_LABELS[state] || ZH.ON}`;
    }

    onDrawForeground(ctx) {
        drawGroupStatusSubtext(ctx, this, this.getStatusText());
    }

}

function createNodeData(type, displayTitle, io = {}) {
    return {
        name: type,
        display_name: displayTitle,
        description: displayTitle,
        category: ZH.CATEGORY,
        search_aliases: ["lx", "LX", "\u7075\u7280", "\u7ec4\u63a7", "\u63a7\u5236\u7ec4\u8282\u70b9", displayTitle, type],
        input: io.input || { required: {}, optional: {}, hidden: {} },
        output: io.output || [],
        output_name: io.outputName || [],
        output_is_list: io.outputIsList || [],
        output_node: false,
    };
}

const SWITCH_NODE_DATA = createNodeData(TYPE_SWITCH_CN, ZH.SWITCH_TITLE);
const SENDER_NODE_DATA = createNodeData(TYPE_SENDER_CN, ZH.SENDER_TITLE, {
    output: [GROUP_STATE_TYPE],
    outputName: [ZH.PORT_STATE],
    outputIsList: [false],
});
const RECEIVER_NODE_DATA = createNodeData(TYPE_RECEIVER_CN, ZH.RECEIVER_TITLE, {
    input: { required: { [ZH.PORT_STATE]: [GROUP_STATE_TYPE, {}] }, optional: {}, hidden: {} },
    output: [GROUP_STATE_TYPE],
    outputName: [ZH.PORT_STATE],
    outputIsList: [false],
});

function makeNodeAlias(BaseClass, type, displayTitle, nodeData) {
    return class extends BaseClass {
        static title = displayTitle;
        static display_name = displayTitle;
        static displayTitle = displayTitle;
        static category = ZH.CATEGORY;
        static comfyClass = type;
        static nodeData = nodeData;

        constructor() {
            super();
            this.type = type;
            this.comfyClass = type;
            this.title = displayTitle;
            this.displayTitle = displayTitle;
        }
    };
}

function registerGroupControlNodeType(type, nodeClass, displayTitle, nodeData) {
    LiteGraph.registerNodeType(
        type,
        Object.assign(nodeClass, {
            title: displayTitle,
            display_name: displayTitle,
            comfyClass: type,
            nodeData,
            category: ZH.CATEGORY,
            title_mode: LiteGraph.NORMAL_TITLE,
        }),
    );
    for (const target of [nodeClass, LiteGraph.registered_node_types?.[type]].filter(Boolean)) {
        target.title = displayTitle;
        target.display_name = displayTitle;
        target.displayTitle = displayTitle;
        target.comfyClass = type;
        target.nodeData = nodeData;
        target.category = ZH.CATEGORY;
    }
}

const SwitchChineseNode = makeNodeAlias(GroupControlSwitchNode, TYPE_SWITCH_CN, ZH.SWITCH_TITLE, SWITCH_NODE_DATA);
const SenderChineseNode = makeNodeAlias(GroupStateSenderNode, TYPE_SENDER_CN, ZH.SENDER_TITLE, SENDER_NODE_DATA);
const ReceiverChineseNode = makeNodeAlias(GroupStateReceiverNode, TYPE_RECEIVER_CN, ZH.RECEIVER_TITLE, RECEIVER_NODE_DATA);

app.registerExtension({
    name: "LX.GroupControl",
    registerCustomNodes() {
        registerGroupControlNodeType(TYPE_SWITCH_CN, SwitchChineseNode, ZH.SWITCH_TITLE, SWITCH_NODE_DATA);
        registerGroupControlNodeType(TYPE_SENDER_CN, SenderChineseNode, ZH.SENDER_TITLE, SENDER_NODE_DATA);
        registerGroupControlNodeType(TYPE_RECEIVER_CN, ReceiverChineseNode, ZH.RECEIVER_TITLE, RECEIVER_NODE_DATA);
    },
});
