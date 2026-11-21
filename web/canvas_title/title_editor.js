import { drawTitle, measureTitle, normalizeStyle, TITLE_DIRECTIONS, TITLE_PRESETS } from "./title_style.js";

export const FONT_SIZES = [16, 20, 24, 32, 40, 48, 56, 64, 72, 80, 96, 112, 128, 160, 200, 240];
export const TITLE_COLORS = [
    ["白色", "#ffffff"], ["雾灰", "#cbd5e1"], ["银灰", "#94a3b8"], ["石墨", "#64748b"], ["近黑", "#18181b"], ["暖白", "#faf0dc"],
    ["珊瑚", "#ff897f"], ["番茄红", "#f65e64"], ["果粉", "#ed86ad"], ["蜜桃", "#ffb278"], ["柑橘", "#fb923c"], ["琥珀", "#f8bb4a"],
    ["亮黄", "#f7dc65"], ["青柠", "#b9df68"], ["薄荷", "#8fe8b2"], ["翡翠", "#48cc82"], ["湖绿", "#39c9af"], ["深绿", "#27956c"],
    ["冰蓝", "#a0e6f4"], ["青蓝", "#58d1ed"], ["天蓝", "#8dbcfb"], ["海蓝", "#638ff3"], ["薰衣草", "#b8adfb"], ["莓紫", "#d99aee"],
];

let activeEditor;

export function loadTitleStyles() {
    if (document.getElementById("lx-canvas-title-styles")) return;
    const link = document.createElement("link");
    link.id = "lx-canvas-title-styles";
    link.rel = "stylesheet";
    link.href = new URL("./title_editor.css", import.meta.url);
    document.head.append(link);
}

function choice(label, dataset, value, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.dataset[dataset] = value;
    button.addEventListener("click", onClick);
    return button;
}

export function editTitle(style, onApply, { focus = "text", extraWidth = 0 } = {}) {
    if (activeEditor?.open) activeEditor.close();
    loadTitleStyles();

    const dialog = document.createElement("dialog");
    dialog.dataset.lxCanvasTitleEditor = "";
    dialog.setAttribute("aria-labelledby", "lx-title-editor-heading");
    dialog.innerHTML = `
        <form>
            <header>
                <h2 id="lx-title-editor-heading">编辑标题</h2>
                <button type="button" data-close aria-label="关闭">×</button>
            </header>
            <div class="lx-title-preview"><canvas aria-hidden="true"></canvas></div>
            <label for="lx-title-text">文字</label>
            <textarea id="lx-title-text" data-field="text" rows="2" spellcheck="false" maxlength="160" placeholder="例如：这里上传参考图"></textarea>
            <div class="lx-title-presets"><span>快捷字号</span><div data-presets></div></div>
            <div class="lx-title-fields">
                <section aria-label="文字颜色">
                    <label for="lx-title-hex">文字颜色</label>
                    <div class="lx-title-colors" data-colors></div>
                    <div class="lx-title-custom-color">
                        <input type="color" data-field="color" aria-label="自定义取色">
                        <input id="lx-title-hex" data-field="hex" type="text" aria-label="十六进制颜色" maxlength="7" spellcheck="false">
                    </div>
                </section>
                <section aria-label="字号">
                    <label for="lx-title-size">字号</label>
                    <div class="lx-title-sizes" data-sizes></div>
                    <div class="lx-title-size-input">
                        <input id="lx-title-size" data-field="fontSize" type="number" min="12" max="240" step="1" required>
                        <span>px</span>
                    </div>
                </section>
            </div>
            <div class="lx-title-extras">
                <label>文字对齐 <select data-field="alignment"><option value="left">居左</option><option value="center">居中</option><option value="right">居右</option></select></label>
                <label>标记 <select data-field="marker"><option value="none">无</option><option value="arrow">箭头</option><option value="triangle">三角</option><option value="dot">圆点</option></select></label>
                <div data-directions role="group" aria-label="标记方向" hidden></div>
                <label class="lx-title-weight"><input data-field="bold" type="checkbox"> 加粗</label>
            </div>
            <small class="lx-title-align-hint">多行文字，或拉宽标题框后，对齐会更明显。</small>
            <footer><small>Ctrl + Enter 应用</small><button type="button" data-cancel>取消</button><button type="submit">应用</button></footer>
        </form>`;

    const form = dialog.querySelector("form");
    const preview = dialog.querySelector("canvas");
    const context = preview.getContext("2d");
    const field = (name) => dialog.querySelector(`[data-field="${name}"]`);
    const directions = dialog.querySelector("[data-directions]");
    let direction = normalizeStyle(style).direction;
    const validHex = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;
    const updateColor = (value) => {
        const hex = normalizeStyle({ color: value }).color;
        field("color").value = field("hex").value = hex;
        field("hex").setCustomValidity("");
    };
    const setFields = (value) => {
        for (const name of ["text", "fontSize", "alignment", "marker"]) field(name).value = value[name];
        field("bold").checked = value.bold;
        updateColor(value.color);
    };
    const read = () => normalizeStyle({
        text: field("text").value,
        fontSize: field("fontSize").value || style.fontSize,
        color: validHex.test(field("hex").value.trim()) ? field("hex").value.trim() : field("color").value,
        alignment: field("alignment").value,
        marker: field("marker").value,
        direction,
        bold: field("bold").checked,
    });
    const refreshPreview = () => {
        const value = read();
        for (const button of dialog.querySelectorAll("[data-color]")) {
            button.setAttribute("aria-pressed", String(button.dataset.color === value.color));
        }
        for (const button of dialog.querySelectorAll("[data-font-size]")) {
            button.setAttribute("aria-pressed", String(Number(button.dataset.fontSize) === value.fontSize));
        }
        directions.hidden = !["arrow", "triangle"].includes(value.marker);
        for (const button of directions.children) {
            button.setAttribute("aria-pressed", String(button.dataset.direction === value.direction));
        }
        if (!context) return;
        const [width, height] = measureTitle(value, context);
        const titleWidth = width + extraWidth;
        const previewWidth = preview.clientWidth || 540;
        const ratio = Math.min(1, previewWidth / titleWidth, 106 / height);
        const density = Math.min(2, window.devicePixelRatio || 1);
        preview.width = Math.max(1, Math.ceil(previewWidth * density));
        preview.height = Math.ceil(106 * density);
        context.setTransform(ratio * density, 0, 0, ratio * density, 0, 0);
        drawTitle(context, value, [titleWidth, 106 / ratio]);
    };
    setFields(normalizeStyle(style));
    const colors = dialog.querySelector("[data-colors]");
    for (const [name, value] of TITLE_COLORS) {
        const button = choice(name, "color", value, () => {
            updateColor(value);
            refreshPreview();
        });
        button.title = `${name} ${value}`;
        button.setAttribute("aria-label", name);
        button.style.setProperty("--swatch", value);
        colors.append(button);
    }
    const sizes = dialog.querySelector("[data-sizes]");
    for (const size of FONT_SIZES) {
        sizes.append(choice(String(size), "fontSize", size, () => {
            field("fontSize").value = size;
            refreshPreview();
        }));
    }
    const presets = dialog.querySelector("[data-presets]");
    for (const [key, preset] of Object.entries(TITLE_PRESETS)) {
        presets.append(choice(`${preset.label} ${preset.fontSize}`, "preset", key, () => {
            field("fontSize").value = preset.fontSize;
            refreshPreview();
        }));
    }
    for (const [key, { label, glyph }] of Object.entries(TITLE_DIRECTIONS)) {
        const button = choice(glyph, "direction", key, () => {
            direction = key;
            refreshPreview();
        });
        button.title = label;
        button.setAttribute("aria-label", label);
        directions.append(button);
    }
    field("color").addEventListener("input", () => updateColor(field("color").value));
    field("hex").addEventListener("input", () => {
        const hex = field("hex").value.trim();
        field("hex").setCustomValidity(validHex.test(hex) ? "" : "请输入 #RRGGBB 或 #RGB 格式的颜色。");
        if (validHex.test(hex)) field("color").value = normalizeStyle({ color: hex }).color;
    });
    form.addEventListener("input", refreshPreview);
    form.addEventListener("change", refreshPreview);
    form.addEventListener("submit", (event) => {
        event.preventDefault();
        onApply(read());
        dialog.close();
    });
    dialog.addEventListener("keydown", (event) => {
        event.stopPropagation();
        if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !event.isComposing) {
            event.preventDefault();
            form.requestSubmit();
        }
    });
    for (const button of dialog.querySelectorAll("[data-close], [data-cancel]")) {
        button.addEventListener("click", () => dialog.close());
    }
    dialog.addEventListener("close", () => {
        dialog.remove();
        if (activeEditor === dialog) activeEditor = null;
    });
    document.body.append(dialog);
    activeEditor = dialog;
    dialog.showModal();
    refreshPreview();
    const focusTarget = field(focus);
    focusTarget?.focus();
    focusTarget?.select?.();
}
