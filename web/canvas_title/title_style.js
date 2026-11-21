export const TITLE_FONT_FAMILY =
    '"Microsoft YaHei UI", "PingFang SC", "Noto Sans CJK SC", "Source Han Sans SC", system-ui, sans-serif';

export const TITLE_PRESETS = Object.freeze({
    headline: Object.freeze({ label: "超大号", fontSize: 200 }),
    section: Object.freeze({ label: "大号", fontSize: 128 }),
    callout: Object.freeze({ label: "中号", fontSize: 80 }),
});

export const TITLE_DIRECTIONS = Object.freeze({
    up: Object.freeze({ label: "向上", glyph: "↑" }),
    down: Object.freeze({ label: "向下", glyph: "↓" }),
    left: Object.freeze({ label: "向左", glyph: "←" }),
    right: Object.freeze({ label: "向右", glyph: "→" }),
});

export const DEFAULT_STYLE = Object.freeze({
    text: "工作流标题",
    fontSize: 56,
    color: "#f5f3ea",
    bold: false,
    alignment: "left",
    marker: "none",
    direction: "right",
});

const MIN_FONT_SIZE = 12;
const MAX_FONT_SIZE = 240;
const MAX_TEXT_LENGTH = 160;
const MAX_LINES = 12;
const alignments = new Set(["left", "center", "right"]);
const markers = new Set(["none", "triangle", "arrow", "dot"]);
const directionVectors = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] };

function normalizeText(value) {
    const source = String(value ?? DEFAULT_STYLE.text).slice(0, MAX_TEXT_LENGTH * 2)
        .replace(/\r\n?/g, "\n")
        .replace(/\t/g, "    ");
    return Array.from(source).slice(0, MAX_TEXT_LENGTH).join("").split("\n", MAX_LINES).join("\n");
}

function normalizeColor(value) {
    const text = String(value ?? "").trim().toLowerCase();
    if (/^#[0-9a-f]{6}$/.test(text)) return text;
    if (/^#[0-9a-f]{3}$/.test(text)) {
        return "#" + Array.from(text.slice(1), (digit) => digit + digit).join("");
    }
    return DEFAULT_STYLE.color;
}

export function normalizeStyle(raw = {}) {
    const value = raw ?? {};
    const size = value.fontSize === "" || value.fontSize == null ? NaN : Number(value.fontSize);
    return {
        text: normalizeText(value.text),
        fontSize: Number.isFinite(size)
            ? Math.max(MIN_FONT_SIZE, Math.min(MAX_FONT_SIZE, Math.round(size)))
            : DEFAULT_STYLE.fontSize,
        color: normalizeColor(value.color),
        bold: typeof value.bold === "boolean" ? value.bold : DEFAULT_STYLE.bold,
        alignment: alignments.has(value.alignment) ? value.alignment : DEFAULT_STYLE.alignment,
        marker: markers.has(value.marker) ? value.marker : DEFAULT_STYLE.marker,
        direction: typeof value.direction === "string" && Object.hasOwn(TITLE_DIRECTIONS, value.direction)
            ? value.direction
            : DEFAULT_STYLE.direction,
    };
}

function font(style) {
    return `${style.bold ? 700 : 400} ${style.fontSize}px ${TITLE_FONT_FAMILY}`;
}

function estimateWidth(text, fontSize) {
    // Canvas measurement replaces this estimate as soon as a drawing context exists.
    let units = 0;
    for (const character of text) {
        units += character.codePointAt(0) < 128 ? 0.59 : 1;
    }
    return units * fontSize;
}

function titleLayout(style, context) {
    const { fontSize, marker } = style;
    const padX = Math.max(8, Math.round(fontSize * 0.2));
    const padY = Math.max(5, Math.round(fontSize * 0.14));
    const markerWidth = marker === "none" ? 0 : Math.round(fontSize * 0.68);
    const markerSpace = markerWidth && markerWidth + Math.max(4, Math.round(fontSize * 0.24));
    let ascent = fontSize * 0.8;
    let descent = fontSize * 0.2;
    if (context) {
        context.save();
        context.font = font(style);
        context.textAlign = "left";
        context.textBaseline = "alphabetic";
    }
    const lines = style.text.split("\n").map((text) => {
        if (!context) return { text, width: estimateWidth(text, fontSize) };
        const metrics = context.measureText(text);
        ascent = Math.max(ascent, metrics.actualBoundingBoxAscent || 0);
        descent = Math.max(descent, metrics.actualBoundingBoxDescent || 0);
        return { text, width: Math.max(metrics.width, metrics.actualBoundingBoxRight || 0) };
    });
    context?.restore();

    const lineHeight = Math.ceil(Math.max(fontSize * 1.22, ascent + descent + fontSize * 0.14));
    const textWidth = Math.max(...lines.map((line) => line.width));
    const width = Math.max(32, Math.ceil(textWidth + markerSpace + padX * 2));
    const height = lines.length * lineHeight + padY * 2;
    const baseline = padY + (lineHeight - ascent - descent) / 2 + ascent;
    return { lines, textWidth, width, height, lineHeight, baseline, padX, markerWidth, markerSpace, ascent, descent };
}

export function measureTitle(raw, context) {
    const { width, height } = titleLayout(normalizeStyle(raw), context);
    return [width, height];
}

function drawMarker(context, marker, direction, x, y, width) {
    const half = width / 2;
    const centerX = x + half;
    context.beginPath();
    if (marker === "dot") {
        context.arc(centerX, y, width * 0.23, 0, 2 * Math.PI);
    } else {
        const [dx, dy] = directionVectors[direction];
        const point = (forward, across) => [
            centerX + forward * dx - across * dy,
            y + forward * dy + across * dx,
        ];
        if (marker === "triangle") {
            context.moveTo(...point(-half, -half));
            context.lineTo(...point(half, 0));
            context.lineTo(...point(-half, half));
        } else {
            const shoulder = half - width * 0.43;
            const shaft = width * 0.14;
            context.moveTo(...point(-half, -shaft));
            context.lineTo(...point(shoulder, -shaft));
            context.lineTo(...point(shoulder, -half));
            context.lineTo(...point(half, 0));
            context.lineTo(...point(shoulder, half));
            context.lineTo(...point(shoulder, shaft));
            context.lineTo(...point(-half, shaft));
        }
        context.closePath();
    }
    context.fill();
}

export function drawTitle(context, raw, size) {
    const style = normalizeStyle(raw);
    const layout = titleLayout(style, context);
    const width = Number(size?.[0]) || layout.width;
    const height = Number(size?.[1]) || layout.height;
    const extraWidth = Math.max(0, width - layout.width);
    const extraHeight = Math.max(0, height - layout.height);
    const align = style.alignment === "right" ? 1 : style.alignment === "center" ? 0.5 : 0;
    const left = layout.padX + extraWidth * align;
    const baseline = layout.baseline + extraHeight * 0.5;

    context.save();
    // A heading is an annotation. It should not inherit execution-mode dimming.
    context.globalAlpha = 1;
    context.font = font(style);
    context.fillStyle = style.color;
    context.textAlign = "left";
    context.textBaseline = "alphabetic";
    if (layout.markerWidth) {
        const center = baseline - (layout.ascent - layout.descent) * 0.5;
        drawMarker(context, style.marker, style.direction, left, center, layout.markerWidth);
    }
    for (let index = 0; index < layout.lines.length; index++) {
        const { text, width: textWidth } = layout.lines[index];
        const x = left + layout.markerSpace + (layout.textWidth - textWidth) * align;
        context.fillText(text, x, baseline + index * layout.lineHeight);
    }
    context.restore();
}
