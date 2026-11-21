import { app } from "../../../../scripts/app.js";
import { ComfyWidgets } from "../../../../scripts/widgets.js";

const NODE_TYPE = "备注";
const NODE_TITLE = "备注";
const NODE_CATEGORY = "🅻🆇 灵犀/实用工具";
const SEARCH_ALIASES = ["lx", "LX", "灵犀", "备注", "便签", "note"];
const TEXT_WIDGET_NAME = "text";
const DEFAULT_THEME = "Comfy 原生";
const CUSTOM_THEME = "自定义颜色";
const DEFAULT_FONT_SIZE = 16;
const MIN_FONT_SIZE = 14;
const MAX_FONT_SIZE = 500;
const FONT_SIZE_PRESETS = [14, 16, 18, 20, 24, 28, 32, 40, 48, 64, 96];

const FALLBACK_NATIVE_YELLOW = {
    color: "#432",
    bgcolor: "#653",
    groupcolor: "#b58b2a",
};

const THEMES = {
    "Comfy 原生": {
        native: true,
    },
    "暗灰极简": {
        color: "#2e3138",
        bgcolor: "#3a3f47",
        groupcolor: "#5f6774",
        field: "#202329",
        text: "#e7ebf0",
    },
    "蓝灰提示": {
        color: "#26394e",
        bgcolor: "#51687d",
        groupcolor: "#7fa1bf",
        field: "#202a34",
        text: "#edf5ff",
    },
    "暖黄注释": {
        color: "#614724",
        bgcolor: "#9b7b36",
        groupcolor: "#d5b05d",
        field: "#2a2418",
        text: "#fff0c8",
    },
    "墨绿备注": {
        color: "#253d32",
        bgcolor: "#426954",
        groupcolor: "#74ad89",
        field: "#1e2a24",
        text: "#e4f5ec",
    },
    "粉棕提醒": {
        color: "#563544",
        bgcolor: "#7b5263",
        groupcolor: "#c5869e",
        field: "#2b2026",
        text: "#ffeaf2",
    },
};

function getNativeYellow() {
    const canvasClass = globalThis.LGraphCanvas || globalThis.LiteGraph?.LGraphCanvas;
    return canvasClass?.node_colors?.yellow || FALLBACK_NATIVE_YELLOW;
}

function normalizeFontSize(value) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return DEFAULT_FONT_SIZE;
    return Math.max(MIN_FONT_SIZE, Math.min(MAX_FONT_SIZE, parsed));
}

function normalizeTheme(value) {
    const name = String(value || DEFAULT_THEME);
    if (name === CUSTOM_THEME) return CUSTOM_THEME;
    return THEMES[name] ? name : DEFAULT_THEME;
}

function normalizeHexColor(value, fallback = getNativeYellow().bgcolor) {
    const text = String(value || "").trim();
    if (/^#[0-9a-f]{6}$/i.test(text)) return text.toLowerCase();
    if (/^#[0-9a-f]{3}$/i.test(text)) {
        return `#${text[1]}${text[1]}${text[2]}${text[2]}${text[3]}${text[3]}`.toLowerCase();
    }
    return normalizeHexColor(fallback, "#665533");
}

function hexToRgb(value) {
    const hex = normalizeHexColor(value).slice(1);
    return {
        r: parseInt(hex.slice(0, 2), 16),
        g: parseInt(hex.slice(2, 4), 16),
        b: parseInt(hex.slice(4, 6), 16),
    };
}

function rgbToHex({ r, g, b }) {
    return `#${[r, g, b]
        .map((channel) => Math.max(0, Math.min(255, Math.round(channel))).toString(16).padStart(2, "0"))
        .join("")}`;
}

function mixColor(color, target, amount) {
    const source = hexToRgb(color);
    const dest = hexToRgb(target);
    return rgbToHex({
        r: source.r + (dest.r - source.r) * amount,
        g: source.g + (dest.g - source.g) * amount,
        b: source.b + (dest.b - source.b) * amount,
    });
}

function isLightColor(color) {
    const { r, g, b } = hexToRgb(color);
    return (0.299 * r + 0.587 * g + 0.114 * b) > 150;
}

function customThemeFromColor(color) {
    const base = normalizeHexColor(color);
    const light = isLightColor(base);
    return {
        color: mixColor(base, light ? "#000000" : "#ffffff", light ? 0.22 : 0.08),
        bgcolor: base,
        groupcolor: mixColor(base, light ? "#000000" : "#ffffff", light ? 0.35 : 0.28),
        field: mixColor(base, light ? "#ffffff" : "#000000", light ? 0.72 : 0.55),
        text: light ? "#111111" : "#f5f5f5",
    };
}

function ensureProperties(node) {
    node.properties = {
        text: "",
        font_size: DEFAULT_FONT_SIZE,
        theme: DEFAULT_THEME,
        custom_color: getNativeYellow().bgcolor,
        ...(node.properties || {}),
    };
    node.properties.text = String(node.properties.text ?? node.properties.note ?? "");
    node.properties.font_size = normalizeFontSize(node.properties.font_size);
    node.properties.theme = normalizeTheme(node.properties.theme);
    node.properties.custom_color = normalizeHexColor(node.properties.custom_color);
    delete node.properties.note;
}

function getThemeColors(node) {
    const themeName = normalizeTheme(node.properties?.theme);
    if (themeName === CUSTOM_THEME) return customThemeFromColor(node.properties?.custom_color);

    const theme = THEMES[themeName];
    if (theme.native) return getNativeYellow();
    return theme;
}

function getTextWidget(node) {
    return node.__lx_note_widget || node.widgets?.find((widget) => widget?.name === TEXT_WIDGET_NAME);
}

function getTextValue(node) {
    const widget = getTextWidget(node);
    return String(widget?.element?.value ?? widget?.value ?? node.properties?.text ?? "");
}

function setTextValue(node, value) {
    const text = String(value ?? "");
    node.properties.text = text;

    const widget = getTextWidget(node);
    if (!widget) return;

    widget.value = text;
    if (widget.element) widget.element.value = text;
}

function applyWidgetStyle(node) {
    const widget = getTextWidget(node);
    const element = widget?.element || widget?.inputEl;
    if (!element?.style) return;

    const themeName = normalizeTheme(node.properties?.theme);
    const theme = themeName === CUSTOM_THEME ? customThemeFromColor(node.properties?.custom_color) : THEMES[themeName];
    const fontSize = normalizeFontSize(node.properties?.font_size);

    element.style.fontSize = `${fontSize}px`;
    element.style.lineHeight = "1.45";

    if (theme.native) {
        element.style.removeProperty("background");
        element.style.removeProperty("color");
        element.style.removeProperty("border-color");
        return;
    }

    element.style.background = theme.field;
    element.style.color = theme.text;
    element.style.borderColor = "rgba(255, 255, 255, 0.08)";
}

function applyTheme(node) {
    ensureProperties(node);

    const colors = getThemeColors(node);
    node.title = NODE_TITLE;
    node.color = colors.color;
    node.bgcolor = colors.bgcolor;
    node.groupcolor = colors.groupcolor || colors.color;

    applyWidgetStyle(node);
}

function dirty(node) {
    node.setDirtyCanvas?.(true, true);
    app.graph?.setDirtyCanvas(true, true);
}

function setProperty(node, key, value) {
    ensureProperties(node);
    if (key === "font_size") {
        const nextSize = Number(value);
        if (!Number.isFinite(nextSize)) return;
        node.properties.font_size = nextSize;
    } else if (key === "custom_color") {
        node.properties.custom_color = normalizeHexColor(value, node.properties.custom_color);
        node.properties.theme = CUSTOM_THEME;
    } else {
        node.properties[key] = value;
    }
    node.properties.theme = normalizeTheme(node.properties.theme);
    applyTheme(node);
    dirty(node);
}

function menuItem(label, checked, callback) {
    return {
        content: checked ? `✓ ${label}` : `　${label}`,
        callback,
    };
}

function themeMenuItem(node, name) {
    const theme = THEMES[name].native ? getNativeYellow() : THEMES[name];
    const swatch = `<span style="color:${theme.bgcolor}">●</span>`;
    return menuItem(`${swatch} ${name}`, name === normalizeTheme(node.properties?.theme), () =>
        setProperty(node, "theme", name),
    );
}

function openFontSizePrompt(node, event) {
    const currentSize = normalizeFontSize(node.properties?.font_size);
    const canvas = app.canvas;

    if (canvas?.prompt) {
        canvas.prompt(
            "字体大小",
            String(currentSize),
            (value) => {
                if (value === null) return;
                setProperty(node, "font_size", value);
            },
            event,
        );
        return;
    }

    const input = window.prompt("字体大小", String(currentSize));
    if (input !== null) setProperty(node, "font_size", input);
}

function openCustomColorPicker(node) {
    ensureProperties(node);

    const input = document.createElement("input");
    input.type = "color";
    input.value = normalizeHexColor(node.properties.custom_color, getThemeColors(node).bgcolor);
    Object.assign(input.style, {
        position: "fixed",
        left: "-1000px",
        top: "-1000px",
        width: "1px",
        height: "1px",
        opacity: "0",
    });

    let removed = false;
    const removeInput = () => {
        if (removed) return;
        removed = true;
        input.remove();
    };

    input.addEventListener("input", () => setProperty(node, "custom_color", input.value));
    input.addEventListener("change", () => {
        setProperty(node, "custom_color", input.value);
        removeInput();
    });
    input.addEventListener("blur", () => window.setTimeout(removeInput, 100));

    document.body.appendChild(input);
    input.click();
}

function addNoteMenu(node, options) {
    const currentSize = normalizeFontSize(node.properties?.font_size);
    const fontOptions = FONT_SIZE_PRESETS.map((size) =>
        menuItem(`${size}px`, size === currentSize, () => setProperty(node, "font_size", size)),
    );

    fontOptions.push(null, {
        content: "自定义...",
        callback: (_item, _options, event) => openFontSizePrompt(node, event),
    });

    const customColor = normalizeHexColor(node.properties?.custom_color);
    const themeOptions = Object.keys(THEMES).map((name) => themeMenuItem(node, name));
    themeOptions.push(null, {
        content: `${normalizeTheme(node.properties?.theme) === CUSTOM_THEME ? "✓" : "　"} <span style="color:${customColor}">●</span> 自定义颜色...`,
        callback: () => openCustomColorPicker(node),
    });

    options.unshift(
        {
            content: `备注字号：${currentSize}px`,
            has_submenu: true,
            submenu: {
                title: "备注字号",
                options: fontOptions,
            },
        },
        {
            content: "备注主题",
            has_submenu: true,
            submenu: {
                title: "备注主题",
                options: themeOptions,
            },
        },
    );
}

app.registerExtension({
    name: "LX.Utility.Note.NativeStyle",

    registerCustomNodes() {
        const LiteGraph = globalThis.LiteGraph;
        const LGraphNode = globalThis.LGraphNode || LiteGraph?.LGraphNode;
        if (!LiteGraph || !LGraphNode || !ComfyWidgets?.STRING) return;

        class LXNoteNode extends LGraphNode {
            static title = NODE_TITLE;
            static category = NODE_CATEGORY;
            static search_aliases = SEARCH_ALIASES;
            static collapsable = true;
            static title_mode = LiteGraph.NORMAL_TITLE;

            constructor(title) {
                super(title || NODE_TITLE);

                ensureProperties(this);

                const result = ComfyWidgets.STRING(
                    this,
                    TEXT_WIDGET_NAME,
                    ["STRING", { default: this.properties.text, multiline: true }],
                    app,
                );
                this.__lx_note_widget = result?.widget || getTextWidget(this);

                this.serialize_widgets = true;
                this.isVirtualNode = true;
                applyTheme(this);
            }

            onConfigure(info) {
                const values = info?.widgets_values || [];
                const properties = info?.properties || {};

                this.properties = {
                    text: values[0] ?? properties.text ?? properties.note ?? "",
                    font_size: normalizeFontSize(properties.font_size ?? values[1]),
                    theme: normalizeTheme(properties.theme ?? values[2]),
                    custom_color: normalizeHexColor(properties.custom_color),
                };

                setTextValue(this, this.properties.text);
                applyTheme(this);
            }

            onSerialize(info) {
                ensureProperties(this);
                this.properties.text = getTextValue(this);
                this.properties.font_size = normalizeFontSize(this.properties.font_size);
                this.properties.theme = normalizeTheme(this.properties.theme);
                this.properties.custom_color = normalizeHexColor(this.properties.custom_color);

                info.properties = {
                    text: this.properties.text,
                    font_size: this.properties.font_size,
                    theme: this.properties.theme,
                    custom_color: this.properties.custom_color,
                };
            }

            getExtraMenuOptions(_, options) {
                addNoteMenu(this, options);
            }
        }

        LiteGraph.registerNodeType(
            NODE_TYPE,
            Object.assign(LXNoteNode, {
                title_mode: LiteGraph.NORMAL_TITLE,
                title: NODE_TITLE,
                collapsable: true,
            }),
        );
        LXNoteNode.category = NODE_CATEGORY;
        LXNoteNode.search_aliases = SEARCH_ALIASES;
    },
});
