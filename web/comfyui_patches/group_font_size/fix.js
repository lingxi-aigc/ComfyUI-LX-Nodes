import { app } from "../../../../scripts/app.js";

const PATCH_MARKER = Symbol.for("LX.ComfyUIPatches.GroupFontSize.applied");
const TITLE_EDITOR_PATCH_MARKER = Symbol.for("LX.ComfyUIPatches.GroupFontSize.titleEditorPatchApplied");
const PROPERTY_EDITOR_PATCH_MARKER = Symbol.for("LX.ComfyUIPatches.GroupFontSize.propertyEditorPatchApplied");
const GROUP_TITLE_HIT_PATCH_MARKER = Symbol.for("LX.ComfyUIPatches.GroupFontSize.titleHitPatchApplied");
const DEFAULT_MIN_FONT_SIZE = 1;
const DEFAULT_MAX_FONT_SIZE = 512;
const DEFAULT_GROUP_TEXT_SIZE = 24;
const DEFAULT_TITLE_HEIGHT = 30;
const MIN_TITLE_HEIGHT = 8;
const TITLE_EDIT_TTL_MS = 3000;
const TITLE_EDITOR_SELECTOR = ".group-title-editor.node-title-editor";
const TITLE_EDITOR_INPUT_SELECTOR = "input, textarea, [contenteditable='true']";
const GRAPH_DIALOG_SELECTOR = ".graphdialog";
const GRAPH_DIALOG_INPUT_SELECTOR = "input.value, textarea.value";

let pendingTitleEditGroup = null;
let pendingTitleEditExpiresAt = 0;

function toFiniteSize(value, fallback, min, max) {
    const number = Number(value);
    if (!Number.isFinite(number)) return fallback;
    return Math.min(max, Math.max(min, number));
}

function toFiniteFontSize(value, fallback) {
    return toFiniteSize(value, fallback, DEFAULT_MIN_FONT_SIZE, DEFAULT_MAX_FONT_SIZE);
}

function toFiniteTitleHeight(value, fallback) {
    return toFiniteSize(value, fallback, MIN_TITLE_HEIGHT, DEFAULT_MAX_FONT_SIZE);
}

function getLiteGraph() {
    return globalThis.LiteGraph;
}

function getGroupClass(liteGraph) {
    return liteGraph?.LGraphGroup || globalThis.LGraphGroup;
}

function getTitleHeightForFontSize(fontSize, baseFontSize, baseTitleHeight) {
    const scaledHeight = Math.ceil((fontSize / baseFontSize) * baseTitleHeight);
    return toFiniteTitleHeight(scaledHeight, baseTitleHeight);
}

function getBaseGroupTextSize() {
    return toFiniteFontSize(getLiteGraph()?.GROUP_TEXT_SIZE, DEFAULT_GROUP_TEXT_SIZE);
}

function getBaseTitleHeight() {
    return toFiniteTitleHeight(getLiteGraph()?.NODE_TITLE_HEIGHT, DEFAULT_TITLE_HEIGHT);
}

function getGroupFontSize(group) {
    return toFiniteFontSize(group?.font_size, getBaseGroupTextSize());
}

function getGroupTitleHeight(group) {
    return toFiniteTitleHeight(
        group?.titleHeight,
        getTitleHeightForFontSize(getGroupFontSize(group), getBaseGroupTextSize(), getBaseTitleHeight()),
    );
}

function getCanvasScale(group) {
    const graphCanvas =
        group?.graph?.list_of_graphcanvas?.[0] ||
        getLiteGraph()?.LGraphCanvas?.active_canvas ||
        globalThis.LGraphCanvas?.active_canvas ||
        app.canvas;
    const scale = Number(graphCanvas?.ds?.scale);
    return Number.isFinite(scale) && scale > 0 ? scale : 1;
}

function isGroupObject(value) {
    const Group = getGroupClass(getLiteGraph());
    return !!value && (!Group || value instanceof Group || Array.isArray(value._pos || value.pos));
}

function isPointInGroupTitlebar(group, x, y) {
    if (!isGroupObject(group)) return false;

    const pos = group.pos || group._pos;
    const size = group.size || group._size;
    const left = Number(pos?.[0]);
    const top = Number(pos?.[1]);
    const width = Number(size?.[0]);
    const titleHeight = getGroupTitleHeight(group);

    return (
        Number.isFinite(x) &&
        Number.isFinite(y) &&
        Number.isFinite(left) &&
        Number.isFinite(top) &&
        Number.isFinite(width) &&
        Number.isFinite(titleHeight) &&
        width > 0 &&
        titleHeight > 0 &&
        x >= left &&
        x < left + width &&
        y >= top &&
        y < top + titleHeight
    );
}

function getGraphGroups(graph) {
    if (Array.isArray(graph?._groups)) return graph._groups;
    if (Array.isArray(graph?.groups)) return graph.groups;
    return [];
}

function getGroupAtPointForTitleHeight(graph, x, y) {
    const group = graph?.getGroupOnPos?.(x, y);
    if (isGroupObject(group)) return group;

    const groups = getGraphGroups(graph);
    for (let index = groups.length - 1; index >= 0; index -= 1) {
        if (isPointInGroupTitlebar(groups[index], x, y)) return groups[index];
    }

    return null;
}

function setImportantStyle(element, name, value) {
    element?.style?.setProperty(name, value, "important");
}

function rememberTitleEditGroup(group) {
    if (!isGroupObject(group)) return;
    pendingTitleEditGroup = group;
    pendingTitleEditExpiresAt = performance.now() + TITLE_EDIT_TTL_MS;
    requestAnimationFrame(applyPendingTitleEditorStyles);
    setTimeout(applyPendingTitleEditorStyles, 0);
}

function getPendingTitleEditGroup() {
    if (!pendingTitleEditGroup) return null;
    if (performance.now() > pendingTitleEditExpiresAt) {
        pendingTitleEditGroup = null;
        return null;
    }
    return pendingTitleEditGroup;
}

function isGroupTitleEvent(detail) {
    const group = detail?.group;
    if (!isGroupObject(group)) return false;

    const canvasY = Number(detail?.originalEvent?.canvasY);
    const groupY = Number(group.pos?.[1] ?? group._pos?.[1]);
    if (!Number.isFinite(canvasY) || !Number.isFinite(groupY)) return true;

    return canvasY - groupY <= getGroupTitleHeight(group);
}

function applyTitleEditorStyles(editor, group) {
    if (!editor || !isGroupObject(group)) return;

    const scale = getCanvasScale(group);
    const fontSize = getGroupFontSize(group) * scale;
    const lineHeight = Math.ceil(fontSize * 1.18);
    const titleHeight = Math.ceil(getGroupTitleHeight(group) * scale);

    setImportantStyle(editor, "font-size", `${fontSize}px`);
    setImportantStyle(editor, "line-height", `${lineHeight}px`);
    setImportantStyle(editor, "min-height", `${titleHeight}px`);

    editor.querySelectorAll(TITLE_EDITOR_INPUT_SELECTOR).forEach((input) => {
        setImportantStyle(input, "font-size", "inherit");
        setImportantStyle(input, "line-height", `${lineHeight}px`);
        setImportantStyle(input, "height", "100%");
    });
}

function applyGraphDialogTitleStyles(dialog, group) {
    if (!dialog || !isGroupObject(group)) return;

    const label = dialog.querySelector(".name")?.textContent?.trim()?.toLowerCase();
    if (label && label !== "title") return;

    const input = dialog.querySelector(GRAPH_DIALOG_INPUT_SELECTOR);
    if (!input) return;

    const scale = getCanvasScale(group);
    const fontSize = getGroupFontSize(group) * scale;
    const lineHeight = Math.ceil(fontSize * 1.18);
    const titleHeight = Math.ceil(getGroupTitleHeight(group) * scale);

    setImportantStyle(input, "font-size", `${fontSize}px`);
    setImportantStyle(input, "line-height", `${lineHeight}px`);
    setImportantStyle(input, "height", `${Math.max(titleHeight, lineHeight + 8)}px`);
    setImportantStyle(input, "min-width", `${Math.max(260, Math.ceil(fontSize * 8))}px`);
}

function applyPendingTitleEditorStyles() {
    const group = getPendingTitleEditGroup();
    if (!group) return;
    document.querySelectorAll(TITLE_EDITOR_SELECTOR).forEach((editor) => applyTitleEditorStyles(editor, group));
    document.querySelectorAll(GRAPH_DIALOG_SELECTOR).forEach((dialog) => applyGraphDialogTitleStyles(dialog, group));
}

function patchGroupTitleEditorFontSize() {
    if (document[TITLE_EDITOR_PATCH_MARKER]) return;

    document.addEventListener(
        "litegraph:canvas",
        (event) => {
            const detail = event?.detail;
            if (detail?.subType === "group-double-click" && isGroupTitleEvent(detail)) {
                rememberTitleEditGroup(detail.group);
            }
        },
        true,
    );

    new MutationObserver(() => applyPendingTitleEditorStyles()).observe(document.documentElement, {
        childList: true,
        subtree: true,
    });

    Object.defineProperty(document, TITLE_EDITOR_PATCH_MARKER, {
        value: true,
        configurable: false,
        enumerable: false,
        writable: false,
    });
}

function patchGroupPropertyEditorFontSize() {
    const Canvas = getLiteGraph()?.LGraphCanvas || globalThis.LGraphCanvas;
    if (!Canvas || Canvas[PROPERTY_EDITOR_PATCH_MARKER] || typeof Canvas.onShowPropertyEditor !== "function") return;

    const originalOnShowPropertyEditor = Canvas.onShowPropertyEditor;
    Canvas.onShowPropertyEditor = function groupFontSizeShowPropertyEditor(item, _options, _event, _menu, target) {
        const property = item?.property || "title";
        if (property === "title" && isGroupObject(target)) {
            rememberTitleEditGroup(target);
        }
        return originalOnShowPropertyEditor.apply(this, arguments);
    };

    Object.defineProperty(Canvas, PROPERTY_EDITOR_PATCH_MARKER, {
        value: true,
        configurable: false,
        enumerable: false,
        writable: false,
    });
}

function patchGroupTitleHitArea() {
    const liteGraph = getLiteGraph();
    const Canvas = liteGraph?.LGraphCanvas || globalThis.LGraphCanvas;
    const proto = Canvas?.prototype;
    if (!liteGraph || !proto || proto[GROUP_TITLE_HIT_PATCH_MARKER]) return;

    const originalProcessPrimaryButton = proto._processPrimaryButton;
    if (typeof originalProcessPrimaryButton !== "function") {
        console.warn("[LX ComfyUI Patch] LGraphCanvas._processPrimaryButton is not available.");
        return;
    }

    proto._processPrimaryButton = function groupFontSizeProcessPrimaryButton(event, node) {
        if (node || !event) {
            return originalProcessPrimaryButton.apply(this, arguments);
        }

        const x = Number(event.canvasX);
        const y = Number(event.canvasY);
        const group = getGroupAtPointForTitleHeight(this.graph, x, y);
        if (!group) {
            return originalProcessPrimaryButton.apply(this, arguments);
        }

        const titleHeight = getGroupTitleHeight(group);
        const previousTitleHeight = liteGraph.NODE_TITLE_HEIGHT;
        if (titleHeight === previousTitleHeight) {
            return originalProcessPrimaryButton.apply(this, arguments);
        }

        liteGraph.NODE_TITLE_HEIGHT = titleHeight;
        try {
            return originalProcessPrimaryButton.apply(this, arguments);
        } finally {
            liteGraph.NODE_TITLE_HEIGHT = previousTitleHeight;
        }
    };

    Object.defineProperty(proto, GROUP_TITLE_HIT_PATCH_MARKER, {
        value: true,
        configurable: false,
        enumerable: false,
        writable: false,
    });
}

function patchGroupFontSize() {
    const liteGraph = getLiteGraph();
    const Group = getGroupClass(liteGraph);

    if (!liteGraph || !Group?.prototype) {
        console.warn("[LX ComfyUI Patch] LiteGraph group class is not available.");
        return;
    }

    const proto = Group.prototype;
    if (proto[PATCH_MARKER]) return;

    const originalConfigure = proto.configure;
    const originalSerialize = proto.serialize;
    const originalDraw = proto.draw;
    const originalIsPointInside = proto.isPointInside;
    const originalTitleHeightDescriptor = Object.getOwnPropertyDescriptor(proto, "titleHeight");
    const baseGroupTextSize = toFiniteFontSize(liteGraph.GROUP_TEXT_SIZE, DEFAULT_GROUP_TEXT_SIZE);
    const baseTitleHeight = toFiniteTitleHeight(liteGraph.NODE_TITLE_HEIGHT, DEFAULT_TITLE_HEIGHT);

    if (typeof originalDraw !== "function") {
        console.warn("[LX ComfyUI Patch] LGraphGroup.draw is not available.");
        return;
    }

    proto.configure = function groupFontSizeConfigure(data) {
        const result = originalConfigure?.apply(this, arguments);
        if (data && Object.prototype.hasOwnProperty.call(data, "font_size")) {
            this.font_size = toFiniteFontSize(data.font_size, baseGroupTextSize);
        } else if (!Number.isFinite(Number(this.font_size))) {
            this.font_size = baseGroupTextSize;
        }
        return result;
    };

    proto.serialize = function groupFontSizeSerialize() {
        const data = originalSerialize?.apply(this, arguments) || {};
        const fallback = baseGroupTextSize;
        const size = toFiniteFontSize(this.font_size, fallback);
        if (size !== fallback) data.font_size = size;
        return data;
    };

    Object.defineProperty(proto, "titleHeight", {
        configurable: true,
        enumerable: originalTitleHeightDescriptor?.enumerable ?? false,
        get() {
            const size = toFiniteFontSize(this.font_size, baseGroupTextSize);
            return getTitleHeightForFontSize(size, baseGroupTextSize, baseTitleHeight);
        },
    });

    proto.draw = function groupFontSizeDraw(graphCanvas, ctx) {
        const fallback = baseGroupTextSize;
        const size = toFiniteFontSize(this.font_size, fallback);
        const titleHeight = getTitleHeightForFontSize(size, baseGroupTextSize, baseTitleHeight);

        if (size === fallback && titleHeight === baseTitleHeight) {
            return originalDraw.apply(this, arguments);
        }

        const previousSize = liteGraph.GROUP_TEXT_SIZE;
        const previousTitleHeight = liteGraph.NODE_TITLE_HEIGHT;
        liteGraph.GROUP_TEXT_SIZE = size;
        liteGraph.NODE_TITLE_HEIGHT = titleHeight;
        try {
            return originalDraw.apply(this, arguments);
        } finally {
            liteGraph.GROUP_TEXT_SIZE = previousSize;
            liteGraph.NODE_TITLE_HEIGHT = previousTitleHeight;
        }
    };

    proto.isPointInside = function groupFontSizeIsPointInside(x, y) {
        if (typeof originalIsPointInside === "function" && originalIsPointInside.apply(this, arguments)) {
            return true;
        }
        return isPointInGroupTitlebar(this, Number(x), Number(y));
    };

    Object.defineProperty(proto, PATCH_MARKER, {
        value: true,
        configurable: false,
        enumerable: false,
        writable: false,
    });

    console.info("[LX ComfyUI Patch] Group font size rendering, title height, title hit area, and title editor fix applied.");
}

app.registerExtension({
    name: "LX.ComfyUIPatches.GroupFontSize",
    setup() {
        patchGroupFontSize();
        patchGroupTitleHitArea();
        patchGroupTitleEditorFontSize();
        patchGroupPropertyEditorFontSize();
    },
});
