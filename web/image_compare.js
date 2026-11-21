import { app } from "../../../../scripts/app.js";
import { api } from "../../../../scripts/api.js";

const NODE_NAME = "LXImageCompare";
const WIDGET_NAME = "__lx_image_compare";
const MIN_WIDTH = 240;
const MIN_HEIGHT = 80;
const LABEL_ROW_HEIGHT = 18;
const LABEL_PADDING = 4;
const LABEL_SPACING = 8;
const IMAGE_MARGIN_BOTTOM = 6;

function imageDataToUrl(data) {
    return api.apiURL(
        `/view?filename=${encodeURIComponent(data.filename)}` +
        `&type=${encodeURIComponent(data.type || "temp")}` +
        `&subfolder=${encodeURIComponent(data.subfolder || "")}` +
        (typeof app.getPreviewFormatParam === "function" ? app.getPreviewFormatParam() : "") +
        (typeof app.getRandParam === "function" ? app.getRandParam() : "")
    );
}

function measureText(ctx, text) {
    if (typeof ctx?.measureText === "function") return ctx.measureText(text).width;
    return String(text || "").length * 7;
}

function cloneImageData(data, group, index, selected) {
    return {
        name: data.name || `${group}${index + 1}`,
        group,
        url: data.url,
        selected: !!selected,
        img: data.img,
    };
}

function inferGroup(data, index) {
    if (data.group === "A" || data.group === "B") return data.group;
    if (typeof data.name === "string" && data.name.toUpperCase().startsWith("B")) return "B";
    if (typeof data.name === "string" && data.name.toUpperCase().startsWith("A")) return "A";
    return index === 1 ? "B" : "A";
}

function getLabelRows(ctx, items, width) {
    if (items.length <= 2) return 0;
    let rows = 1;
    let rowWidth = 0;
    const maxWidth = Math.max(1, width - LABEL_PADDING * 2);
    for (const item of items) {
        const itemWidth = measureText(ctx, item.name) + LABEL_SPACING;
        if (rowWidth > 0 && rowWidth + itemWidth > maxWidth) {
            rows += 1;
            rowWidth = itemWidth;
        } else {
            rowWidth += itemWidth;
        }
    }
    return rows;
}

function buildItemsFromOutput(output) {
    let aImages = output.a_images || output.ui?.a_images || [];
    let bImages = output.b_images || output.ui?.b_images || [];

    if (!aImages.length && !bImages.length && Array.isArray(output.images) && output.images.length) {
        aImages = output.images.filter((_, i) => i % 2 === 0);
        bImages = output.images.filter((_, i) => i % 2 === 1);
    }

    const items = [];

    if (aImages.length && !bImages.length) {
        if (aImages.length === 1) {
            items.push({
                name: "A",
                group: "A",
                selected: true,
                url: imageDataToUrl(aImages[0]),
            });
            return items;
        }

        aImages.forEach((d, i) => {
            items.push({
                name: `A${i + 1}`,
                group: "A",
                selected: i === 0,
                url: imageDataToUrl(d),
            });
        });
        aImages.forEach((d, i) => {
            items.push({
                name: `B${i + 1}`,
                group: "B",
                selected: i === 1,
                url: imageDataToUrl(d),
            });
        });
        return items;
    }

    if (!aImages.length && bImages.length) {
        if (bImages.length === 1) {
            items.push({
                name: "B",
                group: "B",
                selected: true,
                url: imageDataToUrl(bImages[0]),
            });
            return items;
        }

        bImages.forEach((d, i) => {
            items.push({
                name: `A${i + 1}`,
                group: "A",
                selected: i === 0,
                url: imageDataToUrl(d),
            });
        });
        bImages.forEach((d, i) => {
            items.push({
                name: `B${i + 1}`,
                group: "B",
                selected: i === 1,
                url: imageDataToUrl(d),
            });
        });
        return items;
    }

    const multiple = aImages.length + bImages.length > 2;
    aImages.forEach((d, i) => {
        items.push({
            name: aImages.length > 1 || multiple ? `A${i + 1}` : "A",
            group: "A",
            selected: i === 0,
            url: imageDataToUrl(d),
        });
    });
    bImages.forEach((d, i) => {
        items.push({
            name: bImages.length > 1 || multiple ? `B${i + 1}` : "B",
            group: "B",
            selected: i === 0,
            url: imageDataToUrl(d),
        });
    });

    return items;
}

function keepSelectionByName(items, previousSelected) {
    if (!items.length || !previousSelected?.length) return items;

    const selectedByGroup = new Map();
    for (const item of previousSelected) {
        const group = item?.group || inferGroup(item, 0);
        if (group === "A" || group === "B") selectedByGroup.set(group, item.name);
    }
    if (!selectedByGroup.size) return items;

    const next = items.map((item) => ({ ...item, selected: false }));
    let restored = 0;
    for (const group of ["A", "B"]) {
        const name = selectedByGroup.get(group);
        const match = next.find((item) => item.group === group && item.name === name);
        if (match) {
            match.selected = true;
            restored += 1;
        }
    }

    return restored ? next : items;
}

class LXImageCompareWidget {
    constructor(name, node) {
        this.name = name;
        this.type = "custom";
        this.node = node;
        this.hitAreas = {};
        this._value = { images: [] };
        this.selected = [];
    }

    clickWasWithinBounds(pos, bounds) {
        return pos[0] >= bounds[0] &&
            pos[0] <= bounds[0] + bounds[2] &&
            pos[1] >= bounds[1] &&
            pos[1] <= bounds[1] + bounds[3];
    }

    get value() {
        return this._value;
    }

    set value(v) {
        const raw = Array.isArray(v) ? v : v?.images || [];
        let cleaned = raw
            .filter((d) => d && (d.url || d.filename))
            .map((d, i) => {
                const group = inferGroup(d, i);
                const url = d.url || imageDataToUrl(d);
                return cloneImageData({ ...d, url }, group, i, d.selected !== false);
            });

        const hasA = cleaned.some((d) => d.group === "A");
        const hasB = cleaned.some((d) => d.group === "B");
        if (cleaned.length > 1 && hasA !== hasB) {
            const originals = cleaned;
            cleaned = [];
            originals.forEach((d, i) => {
                cleaned.push(cloneImageData({ ...d, name: `A${i + 1}` }, "A", i, i === 0));
            });
            originals.forEach((d, i) => {
                cleaned.push(cloneImageData({ ...d, name: `B${i + 1}` }, "B", i, i === 1));
            });
        }

        if (cleaned.length > 2) {
            const hasGroupA = cleaned.some((d) => d.group === "A");
            const hasGroupB = cleaned.some((d) => d.group === "B");
            if (!hasGroupA || !hasGroupB) cleaned.splice(2);
        }

        this._value.images = cleaned;
        this.setSelected(this.getDefaultSelection(cleaned));
    }

    getDefaultSelection(items) {
        if (!items.length) return [];

        const groupA = items.filter((d) => d.group === "A");
        const groupB = items.filter((d) => d.group === "B");
        const selectedA = groupA.find((d) => d.selected) || groupA[0];
        const selectedB = groupB.find((d) => d.selected) || groupB[0];

        if (selectedA || selectedB) {
            if (!selectedA) return [selectedB];
            if (!selectedB) return [selectedA];
            return [selectedA, selectedB];
        }

        const selected = items.filter((d) => d.selected).slice(0, 2);
        if (selected.length) return selected;
        return items.slice(0, 2);
    }

    setSelected(selected) {
        this._value.images.forEach((d) => (d.selected = false));
        const next = selected.filter(Boolean).slice(0, 2);
        for (const sel of next) {
            if (!sel.img) {
                sel.img = new Image();
                sel.img.addEventListener("load", () => {
                    this.node.setDirtyCanvas?.(true, false);
                }, { once: true });
                sel.img.addEventListener("error", () => {
                    this.node.setDirtyCanvas?.(true, false);
                }, { once: true });
                sel.img.src = sel.url;
            }
            sel.selected = true;
        }

        this.selected = next;
        this.node.imageIndex = this.node.isPointerDown && this.selected[1] ? 1 : 0;
        this.node.setDirtyCanvas?.(true, false);
    }

    computeSize(width) {
        return [width, 20];
    }

    serializeValue() {
        return this._value.images.map((d) => {
            const c = { ...d };
            delete c.img;
            return c;
        });
    }

    deserializeValue(v) {
        const images = Array.isArray(v) ? v : v?.images;
        if (!Array.isArray(images)) {
            this._value = { images: [] };
            this.selected = [];
            return;
        }
        this.value = { images };
    }

    onSelectionDown(event, pos, node, bounds) {
        if (!bounds?.data) return;
        const selected = [...this.selected];
        const group = bounds.data.group || inferGroup(bounds.data, 0);
        if (group === "A") selected[0] = bounds.data;
        else if (group === "B") selected[1] = bounds.data;
        this.setSelected(selected);
        return true;
    }

    mouse(event, pos, node) {
        if (event.type !== "pointerdown" && event.type !== "mousedown") return false;

        for (const area of Object.values(this.hitAreas || {})) {
            if (this.clickWasWithinBounds(pos, area.bounds)) {
                area.onDown?.(event, pos, node, area);
                node.setDirtyCanvas?.(true, false);
                return true;
            }
        }

        return false;
    }

    draw(ctx, node, width, y) {
        this.hitAreas = {};
        if (!this._value.images.length) return;

        if (y == null) y = this.last_y ?? 0;

        const imageY = this.drawLabels(ctx, node, y);
        const mode = node.properties?.comparer_mode || "Slide";

        if (mode === "Click") {
            this.drawImage(ctx, this.selected[node.isPointerDown && this.selected[1] ? 1 : 0], imageY);
            return;
        }

        if (this.selected[0]) this.drawImage(ctx, this.selected[0], imageY);
        if (this.selected[1] && node.isPointerOver) {
            const cropX = node.pointerOverPos?.[0];
            if (cropX != null) this.drawImage(ctx, this.selected[1], imageY, cropX);
        }
    }

    drawLabels(ctx, node, y) {
        if (this._value.images.length <= 2) return y;

        ctx.textAlign = "left";
        ctx.textBaseline = "top";
        ctx.font = "14px Arial";

        const widths = this._value.images.map((d) => measureText(ctx, d.name));
        const totalWidth = widths.reduce((s, w) => s + w, 0) +
            LABEL_SPACING * (this._value.images.length - 1);
        const nodeWidth = node.size[0];
        const wrap = totalWidth + LABEL_PADDING * 2 > nodeWidth;
        let x = wrap ? LABEL_PADDING : (nodeWidth - totalWidth) / 2;
        let rowY = y;

        for (let i = 0; i < this._value.images.length; i++) {
            const item = this._value.images[i];
            const labelWidth = widths[i];
            if (wrap && x + labelWidth > nodeWidth - LABEL_PADDING && x > LABEL_PADDING) {
                x = LABEL_PADDING;
                rowY += LABEL_ROW_HEIGHT;
            }

            ctx.fillStyle = item.selected ? "rgba(210,210,210,1)" : "rgba(170,170,170,0.55)";
            ctx.fillText(item.name, x, rowY);
            this.hitAreas[`${item.group}:${item.name}:${i}`] = {
                bounds: [
                    x - LABEL_PADDING,
                    rowY - 2,
                    labelWidth + LABEL_PADDING * 2,
                    LABEL_ROW_HEIGHT,
                ],
                data: item,
                onDown: this.onSelectionDown.bind(this),
            };
            x += labelWidth + LABEL_SPACING;
        }

        return rowY + LABEL_ROW_HEIGHT + 2;
    }

    getContentRect(y) {
        const [nodeWidth, nodeHeight] = this.node.size;
        return {
            x: 0,
            y,
            width: nodeWidth,
            height: Math.max(1, nodeHeight - y - IMAGE_MARGIN_BOTTOM),
        };
    }

    getDisplayRect(image, y) {
        const img = image?.img;
        if (!img?.naturalWidth || !img?.naturalHeight) return null;

        const content = this.getContentRect(y);
        const aspect = img.naturalWidth / img.naturalHeight;
        let targetWidth;
        let targetHeight;

        if (aspect * content.height > content.width) {
            targetWidth = content.width;
            targetHeight = content.width / aspect;
        } else {
            targetHeight = content.height;
            targetWidth = content.height * aspect;
        }

        return {
            x: content.x + (content.width - targetWidth) / 2,
            y: content.y + (content.height - targetHeight) / 2,
            width: targetWidth,
            height: targetHeight,
        };
    }

    drawImage(ctx, image, y, cropX) {
        const img = image?.img;
        if (!img?.naturalWidth || !img?.naturalHeight) return;

        const rect = this.getDisplayRect(image, y);
        if (!rect) return;

        if (cropX != null) {
            const localCropX = Math.max(rect.x, Math.min(cropX, rect.x + rect.width));
            const destWidth = localCropX - rect.x;
            const sourceWidth = destWidth * (img.naturalWidth / rect.width);

            if (destWidth > 0 && sourceWidth > 0) {
                ctx.save();
                ctx.beginPath();
                ctx.rect(rect.x, rect.y, destWidth, rect.height);
                ctx.clip();
                ctx.drawImage(
                    img,
                    0,
                    0,
                    Math.min(sourceWidth, img.naturalWidth),
                    img.naturalHeight,
                    rect.x,
                    rect.y,
                    destWidth,
                    rect.height
                );
                ctx.restore();
            }

            if (cropX >= rect.x && cropX <= rect.x + rect.width) {
                ctx.save();
                ctx.globalCompositeOperation = "difference";
                ctx.strokeStyle = "rgba(255,255,255,1)";
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.moveTo(cropX, rect.y);
                ctx.lineTo(cropX, rect.y + rect.height);
                ctx.stroke();
                ctx.restore();
            }
            return;
        }

        ctx.drawImage(img, rect.x, rect.y, rect.width, rect.height);
    }
}

app.registerExtension({
    name: "LX.ImageCompare",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        nodeType["@comparer_mode"] = {
            type: "combo",
            values: ["Slide", "Click"],
        };

        const origOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            origOnNodeCreated?.apply(this, arguments);
            this.properties = this.properties || {};
            if (!this.properties.comparer_mode) this.properties.comparer_mode = "Slide";
            this.serialize_widgets = true;
            this.imgs = [];
            this.imageIndex = 0;
            this.isPointerOver = false;
            this.isPointerDown = false;
            this.pointerOverPos = [0, 0];

            if (!this.canvasWidget) {
                this.canvasWidget = this.addCustomWidget(
                    new LXImageCompareWidget(WIDGET_NAME, this)
                );
            }
            if (typeof this.setSize === "function") {
                const width = Math.max(MIN_WIDTH, this.size?.[0] || MIN_WIDTH);
                const height = Math.max(MIN_HEIGHT, this.size?.[1] || 150);
                this.setSize([width, height]);
            }
            this.setDirtyCanvas?.(true, true);
        };

        nodeType.prototype.onExecuted = function (output) {
            if (!this.canvasWidget) return;

            this.imgs = [];
            const previousSelected = [...(this.canvasWidget.selected || [])];
            const images = keepSelectionByName(buildItemsFromOutput(output || {}), previousSelected);
            this.canvasWidget.value = { images };
            this.setDirtyCanvas?.(true, false);
        };

        const origOnSerialize = nodeType.prototype.onSerialize;
        nodeType.prototype.onSerialize = function (serialised) {
            origOnSerialize?.apply(this, arguments);
            for (const [index] of (serialised.widgets_values || []).entries()) {
                if (this.widgets?.[index]?.name !== WIDGET_NAME) continue;
                const images = this.widgets[index].value?.images || [];
                serialised.widgets_values[index] = images.map((d) => {
                    const c = { ...d };
                    delete c.img;
                    return c;
                });
            }
        };

        const origOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            origOnConfigure?.apply(this, arguments);
            const index = this.widgets?.findIndex((widget) => widget.name === WIDGET_NAME) ?? -1;
            const value = index >= 0 ? info?.widgets_values?.[index] : null;
            if (value != null && this.canvasWidget) {
                this.canvasWidget.deserializeValue(value);
                this.setDirtyCanvas?.(true, false);
            }
        };

        const origComputeSize = nodeType.prototype.computeSize;
        nodeType.prototype.computeSize = function () {
            const size = origComputeSize?.apply(this, arguments);
            const minHeight = Math.max(MIN_HEIGHT, size?.[1] || MIN_HEIGHT);
            return [Math.max(MIN_WIDTH, size?.[0] || MIN_WIDTH), minHeight];
        };

        nodeType.prototype._getLabelHeight = function (width) {
            if (!this.canvasWidget || this.canvasWidget._value.images.length <= 2) return 0;
            const tempCtx = document.createElement("canvas").getContext("2d");
            tempCtx.font = "14px Arial";
            return getLabelRows(tempCtx, this.canvasWidget._value.images, width) * LABEL_ROW_HEIGHT + 2;
        };

        nodeType.prototype._queueCompareRedraw = function () {
            if (this._lxCompareRedrawPending) return;
            this._lxCompareRedrawPending = true;
            requestAnimationFrame(() => {
                this._lxCompareRedrawPending = false;
                this.setDirtyCanvas?.(true, false);
            });
        };

        nodeType.prototype._setPointerDown = function (down = this.isPointerDown, force = false) {
            const canvasPointerStateKnown = typeof app.canvas?.pointer_is_down === "boolean";
            const next = !!down && (force || !canvasPointerStateKnown || !!app.canvas?.pointer_is_down);
            if (this.isPointerDown !== next) {
                this.isPointerDown = next;
                this.setDirtyCanvas?.(true, false);
            }
            this.imageIndex = next && this.canvasWidget?.selected?.[1] ? 1 : 0;
            if (next) requestAnimationFrame(() => this._setPointerDown());
        };

        nodeType.prototype._installPointerUpFallback = function () {
            if (this._lxPointerUpFallback) return;
            const clear = () => {
                this._lxPointerUpFallback = null;
                window.removeEventListener("pointerup", clear, true);
                window.removeEventListener("mouseup", clear, true);
                window.removeEventListener("blur", clear, true);
                this._setPointerDown?.(false, true);
            };
            this._lxPointerUpFallback = clear;
            window.addEventListener("pointerup", clear, true);
            window.addEventListener("mouseup", clear, true);
            window.addEventListener("blur", clear, true);
        };

        nodeType.prototype._handleCompareLabelHit = function (event, pos) {
            if (!this.canvasWidget || !Array.isArray(pos)) return false;
            const areas = this.canvasWidget.hitAreas || {};
            for (const area of Object.values(areas)) {
                if (this.canvasWidget.clickWasWithinBounds(pos, area.bounds)) {
                    area.onDown?.(event, pos, this, area);
                    this.setDirtyCanvas?.(true, false);
                    return true;
                }
            }
            return false;
        };

        const origOnResize = nodeType.prototype.onResize;
        nodeType.prototype.onResize = function (size) {
            origOnResize?.apply(this, arguments);
            this.setDirtyCanvas?.(true, false);
        };

        const origOnMouseEnter = nodeType.prototype.onMouseEnter;
        nodeType.prototype.onMouseEnter = function (event) {
            origOnMouseEnter?.apply(this, arguments);
            this.isPointerOver = true;
            this._setPointerDown?.(!!app.canvas?.pointer_is_down);
            this.setDirtyCanvas?.(true, false);
        };

        const origOnMouseLeave = nodeType.prototype.onMouseLeave;
        nodeType.prototype.onMouseLeave = function (event) {
            origOnMouseLeave?.apply(this, arguments);
            this.isPointerOver = false;
            this._setPointerDown?.(false, true);
            this.setDirtyCanvas?.(true, false);
        };

        const origOnMouseMove = nodeType.prototype.onMouseMove;
        nodeType.prototype.onMouseMove = function (event, pos) {
            origOnMouseMove?.apply(this, arguments);
            if (Array.isArray(pos)) {
                this.pointerOverPos = [...pos];
                this.imageIndex = pos[0] > this.size[0] / 2 && this.canvasWidget?.selected?.[1] ? 1 : 0;
                this._queueCompareRedraw?.();
            }
        };

        const origOnMouseDown = nodeType.prototype.onMouseDown;
        nodeType.prototype.onMouseDown = function (event, pos) {
            if (this._handleCompareLabelHit?.(event, pos)) return true;

            origOnMouseDown?.apply(this, arguments);
            this._setPointerDown?.(true, true);
            this._installPointerUpFallback?.();

            this.setDirtyCanvas?.(true, false);
            return false;
        };

        const origOnMouseUp = nodeType.prototype.onMouseUp;
        nodeType.prototype.onMouseUp = function (event) {
            origOnMouseUp?.apply(this, arguments);
            this._setPointerDown?.(false, true);
            this.setDirtyCanvas?.(true, false);
        };
    },
});
