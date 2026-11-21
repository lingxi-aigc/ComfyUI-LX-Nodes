import { app } from "../../../../scripts/app.js";
import { api } from "../../../../scripts/api.js";

const NODE_NAME = "MultiLoraLoader";
const WIDGET_NAME = "loras";
const WIDGET_VERSION = 2;
const DEFAULT_ROW = Object.freeze({ on: true, lora: null, strength: 1.0 });
const LORA_PLACEHOLDER = "选择 LoRA";
const MIN_WIDTH = 430;
const ROW_HEIGHT = 34;
const ADD_HEIGHT = 28;
const PADDING_X = 12;
const PADDING_Y = 8;
const STRENGTH_STEP = 0.01;

let loraNamesPromise = null;

function setNodeDirty(node) {
    node.setDirtyCanvas?.(true, true);
    app.graph?.setDirtyCanvas(true, true);
}

function normalizeRow(row) {
    const value = row && typeof row === "object" ? row : {};
    const strength = Number.parseFloat(value.strength);
    const lora = value.lora || value.name || value.lora_name || null;
    return {
        on: value.on !== false && value.enabled !== false,
        lora: lora === "None" || lora === LORA_PLACEHOLDER ? null : lora,
        strength: Number.isFinite(strength) ? strength : 1.0,
    };
}

function normalizeRows(value) {
    let rows = value;
    if (typeof rows === "string") {
        try {
            rows = JSON.parse(rows);
        } catch {
            rows = null;
        }
    }
    if (!Array.isArray(rows)) rows = [DEFAULT_ROW];
    rows = rows.map(normalizeRow);
    return rows.length ? rows : [normalizeRow(DEFAULT_ROW)];
}

function isFiniteNumberLike(value) {
    return value !== "" && Number.isFinite(Number(value));
}

function migrateLegacyWidgetValues(values) {
    if (!Array.isArray(values)) return null;

    for (const value of values) {
        if (Array.isArray(value)) return value;
        if (typeof value === "string") {
            try {
                const parsed = JSON.parse(value);
                if (Array.isArray(parsed)) return parsed;
            } catch {
                // Keep scanning for older native widget layouts.
            }
        }
    }

    const rows = [];
    for (let index = 0; index < values.length; index += 1) {
        const value = values[index];
        const next = values[index + 1];
        const afterNext = values[index + 2];

        if (typeof value === "boolean" && typeof next === "string" && isFiniteNumberLike(afterNext)) {
            rows.push({ on: value, lora: next, strength: Number(afterNext) });
            index += 2;
        } else if (typeof value === "string" && isFiniteNumberLike(next)) {
            rows.push({ on: true, lora: value, strength: Number(next) });
            index += 1;
        }
    }

    const normalized = rows.map(normalizeRow).filter((row) => row.lora);
    return normalized.length ? normalized : null;
}

function readSavedRows(info, widgetIndex) {
    const direct = widgetIndex >= 0 ? info?.widgets_values?.[widgetIndex] : null;
    if (Array.isArray(direct)) return direct;
    return migrateLegacyWidgetValues(info?.widgets_values);
}

async function getLoraNames(force = false) {
    if (!loraNamesPromise || force) {
        loraNamesPromise = api.fetchApi("/object_info/LoraLoader", { cache: "no-store" })
            .then((response) => response.json())
            .then((data) => {
                const values = data?.LoraLoader?.input?.required?.lora_name?.[0];
                return Array.isArray(values) ? values : [];
            })
            .catch((error) => {
                console.warn("[LoRA加载器（多重）] 获取 LoRA 列表失败:", error);
                return [];
            });
    }
    return loraNamesPromise;
}

function roundRect(ctx, x, y, width, height, radius) {
    const r = Math.min(radius, width / 2, height / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + width - r, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + r);
    ctx.lineTo(x + width, y + height - r);
    ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
    ctx.lineTo(x + r, y + height);
    ctx.quadraticCurveTo(x, y + height, x, y + height - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
}

function truncateText(ctx, text, maxWidth) {
    const value = String(text || "");
    if (ctx.measureText(value).width <= maxWidth) return value;

    const ellipsis = "...";
    let lo = 0;
    let hi = value.length;
    while (lo < hi) {
        const mid = Math.ceil((lo + hi) / 2);
        if (ctx.measureText(value.slice(0, mid) + ellipsis).width <= maxWidth) lo = mid;
        else hi = mid - 1;
    }
    return value.slice(0, lo) + ellipsis;
}

function pointInBounds(pos, bounds) {
    if (!bounds) return false;
    const [x, y, width, height] = bounds;
    return pos[0] >= x && pos[0] <= x + width && pos[1] >= y && pos[1] <= y + height;
}

function drawRowBg(ctx, x, y, width, height, active) {
    ctx.save();
    ctx.globalAlpha = active ? 1 : 0.45;
    roundRect(ctx, x, y, width, height, 7);
    ctx.fillStyle = LiteGraph.WIDGET_BGCOLOR || "#222";
    ctx.strokeStyle = LiteGraph.WIDGET_OUTLINE_COLOR || "#666";
    ctx.lineWidth = 1;
    ctx.fill();
    ctx.stroke();
    ctx.restore();
}

function drawAddButton(ctx, x, y, width, height) {
    drawRowBg(ctx, x, y, width, height, true);
    ctx.save();
    ctx.fillStyle = LiteGraph.WIDGET_TEXT_COLOR || "#ddd";
    ctx.font = "14px Arial";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("+ 添加 LoRA", x + width / 2, y + height / 2);
    ctx.restore();
}

class MultiLoraWidget {
    constructor(node) {
        this.name = WIDGET_NAME;
        this.type = "custom";
        this.__multiLoraCompact = true;
        this.__multiLoraWidgetVersion = WIDGET_VERSION;
        this.node = node;
        this.hitAreas = [];
        this.draggingStrength = null;
        this._value = normalizeRows([DEFAULT_ROW]);
        this.options = { serialize: true };
    }

    get value() {
        return this._value;
    }

    set value(next) {
        this._value = normalizeRows(next);
        setNodeDirty(this.node);
    }

    computeSize(width) {
        const rows = Math.max(1, this._value.length);
        return [
            Math.max(MIN_WIDTH, width || MIN_WIDTH),
            PADDING_Y + rows * ROW_HEIGHT + ADD_HEIGHT + PADDING_Y,
        ];
    }

    serializeValue() {
        return this._value.map((row) => ({
            on: row.on !== false,
            lora: row.lora || null,
            strength: Number.isFinite(Number(row.strength)) ? Number(row.strength) : 1.0,
        }));
    }

    deserializeValue(value) {
        this._value = normalizeRows(value);
        this.resizeNode();
    }

    resizeNode() {
        const node = this.node;
        if (typeof node.computeSize === "function" && typeof node.setSize === "function") {
            const size = node.computeSize();
            if (Array.isArray(size)) {
                node.setSize([Math.max(MIN_WIDTH, size[0], node.size?.[0] || 0), size[1]]);
            }
        }
        setNodeDirty(node);
    }

    addRow() {
        this._value.push(normalizeRow(DEFAULT_ROW));
        this.resizeNode();
    }

    removeRow(index) {
        this._value.splice(index, 1);
        if (!this._value.length) this._value.push(normalizeRow(DEFAULT_ROW));
        this.resizeNode();
    }

    moveRow(index, direction) {
        const nextIndex = index + direction;
        if (nextIndex < 0 || nextIndex >= this._value.length) return;
        const [row] = this._value.splice(index, 1);
        this._value.splice(nextIndex, 0, row);
        this.resizeNode();
    }

    copyRow(index) {
        this._value.splice(index + 1, 0, normalizeRow(this._value[index]));
        this.resizeNode();
    }

    showLoraMenu(event, index) {
        getLoraNames().then((names) => {
            const options = ["None", ...names];
            new LiteGraph.ContextMenu(options, {
                event,
                title: "选择 LoRA",
                className: "dark",
                scale: Math.max(1, app.canvas?.ds?.scale || 1),
                callback: (value) => {
                    if (this._value[index]) {
                        this._value[index].lora = value === "None" ? null : value;
                        setNodeDirty(this.node);
                    }
                },
            });
        });
    }

    showRowMenu(event, index) {
        new LiteGraph.ContextMenu(
            [
                { content: "删除", callback: () => this.removeRow(index) },
                { content: "上移", disabled: index <= 0, callback: () => this.moveRow(index, -1) },
                {
                    content: "下移",
                    disabled: index >= this._value.length - 1,
                    callback: () => this.moveRow(index, 1),
                },
                { content: "复制", callback: () => this.copyRow(index) },
            ],
            {
                event,
                title: "LoRA",
                className: "dark",
                scale: Math.max(1, app.canvas?.ds?.scale || 1),
            },
        );
    }

    editStrength(event, index) {
        const current = this._value[index].strength;
        const canvas = app.canvas;
        const applyValue = (value) => {
            const next = Number.parseFloat(value);
            if (Number.isFinite(next)) {
                this._value[index].strength = Math.round(next * 100) / 100;
                setNodeDirty(this.node);
            }
        };
        if (canvas?.prompt) canvas.prompt("强度", current, applyValue, event);
        else applyValue(window.prompt("强度", String(current)));
    }

    stepStrength(index, delta) {
        const current = Number(this._value[index].strength);
        const next = (Number.isFinite(current) ? current : 1.0) + delta;
        this._value[index].strength = Math.round(next * 100) / 100;
        setNodeDirty(this.node);
    }

    beginStrengthDrag(event, pos, index) {
        const current = Number(this._value[index].strength);
        this.draggingStrength = {
            index,
            startX: pos[0],
            startStrength: Number.isFinite(current) ? current : 1.0,
            moved: false,
        };
        event?.preventDefault?.();
    }

    updateStrengthDrag(event, pos) {
        const drag = this.draggingStrength;
        if (!drag) return false;

        const deltaPixels = pos[0] - drag.startX;
        if (Math.abs(deltaPixels) >= 2) drag.moved = true;

        const step = event?.shiftKey ? 0.05 : 0.01;
        const next = drag.startStrength + deltaPixels * step;
        this._value[drag.index].strength = Math.round(next * 100) / 100;
        setNodeDirty(this.node);
        return true;
    }

    endStrengthDrag(event) {
        const drag = this.draggingStrength;
        if (!drag) return false;

        this.draggingStrength = null;
        if (!drag.moved) this.editStrength(event, drag.index);
        setNodeDirty(this.node);
        return true;
    }

    mouse(event, pos, node) {
        if (event.type === "mousemove" || event.type === "pointermove") {
            return this.updateStrengthDrag(event, pos);
        }

        if (event.type === "mouseup" || event.type === "pointerup") {
            return this.endStrengthDrag(event);
        }

        if (event.type !== "mousedown" && event.type !== "pointerdown") return false;

        for (const area of this.hitAreas) {
            if (!pointInBounds(pos, area.bounds)) continue;

            if (area.action === "toggle") {
                this._value[area.index].on = !this._value[area.index].on;
            } else if (area.action === "lora") {
                this.showLoraMenu(event, area.index);
            } else if (area.action === "strength") {
                this.beginStrengthDrag(event, pos, area.index);
            } else if (area.action === "minus") {
                this.stepStrength(area.index, -STRENGTH_STEP);
            } else if (area.action === "plus") {
                this.stepStrength(area.index, STRENGTH_STEP);
            } else if (area.action === "menu") {
                this.showRowMenu(event, area.index);
            } else if (area.action === "add") {
                this.addRow();
            }

            setNodeDirty(node);
            return true;
        }

        return false;
    }

    drawStatus(ctx, x, y, active) {
        ctx.save();
        ctx.beginPath();
        ctx.arc(x, y, 4.5, 0, Math.PI * 2);
        ctx.fillStyle = active ? "rgba(95, 184, 120, 0.92)" : "rgba(120, 120, 120, 0.55)";
        ctx.fill();
        ctx.lineWidth = 1;
        ctx.strokeStyle = active ? "rgba(210, 255, 218, 0.75)" : "rgba(170, 170, 170, 0.45)";
        ctx.stroke();
        ctx.restore();
    }

    drawStrengthControl(ctx, x, y, width, height, value, active) {
        const arrowWidth = 18;
        const centerY = y + height / 2;
        const textColor = LiteGraph.WIDGET_TEXT_COLOR || "#ddd";
        const subtleColor = LiteGraph.WIDGET_SECONDARY_TEXT_COLOR || "#aaa";

        ctx.save();
        ctx.globalAlpha = active ? 0.82 : 0.42;
        ctx.font = "13px Arial";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillStyle = subtleColor;
        ctx.fillText("‹", x + arrowWidth / 2, centerY);
        ctx.fillText("›", x + width - arrowWidth / 2, centerY);

        ctx.globalAlpha = active ? 1 : 0.45;
        ctx.fillStyle = textColor;
        ctx.fillText(Number(value || 0).toFixed(2), x + width / 2, centerY);
        ctx.restore();
    }

    draw(ctx, node, width, y) {
        const nodeWidth = Math.max(MIN_WIDTH, node.size?.[0] || width || MIN_WIDTH);
        const left = PADDING_X;
        const rowWidth = nodeWidth - PADDING_X * 2;
        const right = left + rowWidth;
        const menuWidth = 24;
        const strengthWidth = 94;
        const arrowWidth = 18;
        const nameX = left + 28;
        const strengthX = right - menuWidth - strengthWidth;
        let rowY = y + PADDING_Y;
        this.hitAreas = [];

        ctx.save();
        ctx.textBaseline = "middle";

        for (let index = 0; index < this._value.length; index += 1) {
            const row = this._value[index];
            const active = row.on !== false;
            const centerY = rowY + ROW_HEIGHT / 2;

            drawRowBg(ctx, left, rowY + 2, rowWidth, ROW_HEIGHT - 4, active);
            this.drawStatus(ctx, left + 14, centerY, active);

            ctx.globalAlpha = active ? 1 : 0.45;
            ctx.font = "14px Arial";
            ctx.textAlign = "left";
            ctx.fillStyle = row.lora ? (LiteGraph.WIDGET_TEXT_COLOR || "#ddd") : (LiteGraph.WIDGET_SECONDARY_TEXT_COLOR || "#aaa");
            const nameWidth = Math.max(60, strengthX - nameX - 14);
            ctx.fillText(truncateText(ctx, row.lora || LORA_PLACEHOLDER, nameWidth), nameX, centerY, nameWidth);

            this.drawStrengthControl(ctx, strengthX, rowY, strengthWidth, ROW_HEIGHT, row.strength, active);
            ctx.globalAlpha = active ? 0.78 : 0.5;
            ctx.font = "16px Arial";
            ctx.textAlign = "center";
            ctx.fillStyle = LiteGraph.WIDGET_TEXT_COLOR || "#ddd";
            ctx.fillText("⋮", right - menuWidth / 2, centerY);

            this.hitAreas.push({ action: "toggle", index, bounds: [left, rowY, 28, ROW_HEIGHT] });
            this.hitAreas.push({ action: "lora", index, bounds: [nameX - 4, rowY, nameWidth + 8, ROW_HEIGHT] });
            this.hitAreas.push({ action: "minus", index, bounds: [strengthX, rowY, arrowWidth, ROW_HEIGHT] });
            this.hitAreas.push({
                action: "strength",
                index,
                bounds: [strengthX + arrowWidth, rowY, strengthWidth - arrowWidth * 2, ROW_HEIGHT],
            });
            this.hitAreas.push({
                action: "plus",
                index,
                bounds: [strengthX + strengthWidth - arrowWidth, rowY, arrowWidth, ROW_HEIGHT],
            });
            this.hitAreas.push({ action: "menu", index, bounds: [right - menuWidth, rowY, menuWidth, ROW_HEIGHT] });

            rowY += ROW_HEIGHT;
            ctx.globalAlpha = 1;
        }

        drawAddButton(ctx, left, rowY + 2, rowWidth, ADD_HEIGHT - 6);
        this.hitAreas.push({ action: "add", bounds: [left, rowY + 2, rowWidth, ADD_HEIGHT - 6] });
        ctx.restore();
    }
}

function findWidget(node, name) {
    return (node.widgets || []).find((widget) => widget?.name === name);
}

function applyDefaultTitle(node) {
    if (!node.title || node.title === NODE_NAME) {
        node.title = "LoRA加载器（多重）";
    }
}

function ensureWidget(node) {
    let widget = findWidget(node, WIDGET_NAME);
    if (!widget) {
        widget = node.addCustomWidget(new MultiLoraWidget(node));
    } else if (widget.__multiLoraCompact !== true || widget.__multiLoraWidgetVersion !== WIDGET_VERSION) {
        const value = widget.value || widget.serializeValue?.() || [DEFAULT_ROW];
        const index = node.widgets.indexOf(widget);
        if (index >= 0) {
            node.widgets.splice(index, 1, new MultiLoraWidget(node));
            widget = node.widgets[index];
            widget.value = value;
        }
    }
    node.lorasWidget = widget;
    node.serialize_widgets = true;
    applyDefaultTitle(node);
    widget.resizeNode?.();
}

app.registerExtension({
    name: "LX.LoraTools.MultiLoraLoader",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            ensureWidget(this);
            return result;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            ensureWidget(this);
            const index = this.widgets?.findIndex((widget) => widget.name === WIDGET_NAME) ?? -1;
            const value = readSavedRows(info, index);
            let result;
            try {
                result = onConfigure?.apply(this, arguments);
            } catch (error) {
                console.warn("[LoRA加载器（多重）] 已跳过旧控件恢复错误:", error);
            }
            if (value != null && this.lorasWidget?.deserializeValue) {
                this.lorasWidget.deserializeValue(value);
            }
            return result;
        };

        const onSerialize = nodeType.prototype.onSerialize;
        nodeType.prototype.onSerialize = function (serialized) {
            const result = onSerialize?.apply(this, arguments);
            const index = this.widgets?.findIndex((widget) => widget.name === WIDGET_NAME) ?? -1;
            if (index >= 0 && serialized?.widgets_values) {
                serialized.widgets_values[index] = this.widgets[index].serializeValue();
            }
            return result;
        };

        const refreshComboInNode = nodeType.prototype.refreshComboInNode;
        nodeType.prototype.refreshComboInNode = function () {
            loraNamesPromise = null;
            return refreshComboInNode?.apply(this, arguments);
        };

        const computeSize = nodeType.prototype.computeSize;
        nodeType.prototype.computeSize = function () {
            const size = computeSize?.apply(this, arguments) || [MIN_WIDTH, 120];
            return [Math.max(MIN_WIDTH, size[0]), size[1]];
        };
    },

    async nodeCreated(node) {
        if (node?.comfyClass === NODE_NAME || node?.type === NODE_NAME) {
            ensureWidget(node);
        }
    },
});
