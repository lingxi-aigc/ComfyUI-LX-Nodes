import { app } from "../../../../scripts/app.js";
import { DEFAULT_STYLE, drawTitle, measureTitle, normalizeStyle, TITLE_PRESETS } from "./title_style.js";
import { editTitle, FONT_SIZES, loadTitleStyles, TITLE_COLORS } from "./title_editor.js";

const TYPE = "LXCanvasTitle";
const TITLE = "标题";
const CATEGORY = "🅻🆇 灵犀/实用工具";
const DESCRIPTION = "在工作流上添加透明文字，可用作标题、分区名或短提示。";
const SEARCH_ALIASES = ["lx", "LX", "灵犀", "标题", "文字标注", "短备注", "标题文字", "canvas title"];
const measurement = document.createElement("canvas").getContext("2d");

function setDirty(node) {
    node.setDirtyCanvas?.(true, true);
    app.canvas?.setDirty?.(true, true);
}

function makeMenu(node) {
    const style = normalizeStyle(node.properties);
    const set = (change) => node.applyTitleStyle({ ...style, ...change });
    return [
        { content: "编辑文字与样式", callback: () => node.openTitleEditor() },
        {
            content: `字号 · ${style.fontSize} px`,
            has_submenu: true,
            submenu: {
                options: [
                    ...FONT_SIZES.map((size) => ({
                        content: `${size === style.fontSize ? "✓ " : ""}${size} px`,
                        callback: () => set({ fontSize: size }),
                    })),
                    null,
                    { content: "自定义字号…", callback: () => node.openTitleEditor("fontSize") },
                ],
            },
        },
        {
            content: "文字颜色",
            has_submenu: true,
            submenu: {
                options: [
                    ...TITLE_COLORS.filter((_, index) => index % 2 === 0).map(([name, color]) => ({
                        content: `<span style="color:${color}">●</span> ${name}`,
                        callback: () => set({ color }),
                    })),
                    null,
                    { content: "完整色板与自定义取色…", callback: () => node.openTitleEditor("hex") },
                ],
            },
        },
        {
            content: "快捷字号",
            has_submenu: true,
            submenu: { options: Object.values(TITLE_PRESETS).map(({ label, fontSize }) => ({
                content: `${label} ${fontSize} px`,
                callback: () => set({ fontSize }),
            })) },
        },
        { content: "贴合文字大小", callback: () => node.applyTitleStyle(style, true) },
        null,
    ];
}

app.registerExtension({
    name: "LX.CanvasTitle",
    beforeRegisterVueAppNodeDefs(nodeDefs) {
        const def = nodeDefs?.find((entry) => entry?.name === TYPE);
        if (!def) return;
        Object.assign(def, {
            display_name: TITLE,
            description: DESCRIPTION,
            category: CATEGORY,
            search_aliases: SEARCH_ALIASES,
        });
    },
    registerCustomNodes() {
        const liteGraph = globalThis.LiteGraph;
        const Node = globalThis.LGraphNode ?? liteGraph?.LGraphNode;
        if (!Node || !liteGraph || liteGraph.registered_node_types?.[TYPE]) return;
        loadTitleStyles();

        class TitleNode extends Node {
            static title = TITLE;
            static display_name = TITLE;
            static title_mode = liteGraph.NO_TITLE;
            static category = CATEGORY;
            static comfyClass = TYPE;
            static search_aliases = SEARCH_ALIASES;
            static collapsable = false;
            static nodeData = {
                name: TYPE,
                display_name: TITLE,
                description: DESCRIPTION,
                category: CATEGORY,
                search_aliases: SEARCH_ALIASES,
                input: { required: {}, optional: {}, hidden: {} },
                output: [],
                output_name: [],
                output_is_list: [],
                output_node: false,
            };

            constructor(title) {
                super(title || TITLE);
                Object.assign(this.properties, DEFAULT_STYLE);
                this.isVirtualNode = true;
                this.serialize_widgets = false;
                this.resizable = true;
                this.color = this.bgcolor = "#00000000";
                this.naturalTitleSize = measureTitle(this.properties, measurement);
                this.size = [...this.naturalTitleSize];
                this.widgets_start_y = 0;
                if (typeof this.addDOMWidget === "function") {
                    const element = document.createElement("canvas");
                    element.className = "lx-title-render";
                    element.setAttribute("role", "img");
                    this.titleElement = element;
                    this.addDOMWidget("titlePresentation", "lx-canvas-title-display", element, {
                        margin: 0,
                        hideOnZoom: false,
                        selectOn: [],
                        serialize: false,
                        surfaces: { canvas: "never", vueNode: "shown", panel: "never" },
                        getMinHeight: () => this.naturalTitleSize[1],
                    });
                }
                this.refreshTitle();
            }

            get renderingColor() { return "transparent"; }
            get renderingBgColor() { return "transparent"; }

            // This node's visible content is the lettering itself.
            drawBadges() {}

            computeSize() {
                return this.naturalTitleSize ? [...this.naturalTitleSize] : [100, 34];
            }

            onDrawForeground(context) {
                if (!liteGraph.vueNodesMode || !this.titleElement) drawTitle(context, this.properties, this.size);
            }

            onDblClick(event) {
                if (event.button === 0) this.openTitleEditor();
            }

            onResize(size) {
                if (!this.naturalTitleSize || !size) return;
                size[0] = Math.max(size[0], this.naturalTitleSize[0]);
                size[1] = Math.max(size[1], this.naturalTitleSize[1]);
                this.refreshTitle(size);
            }

            onConfigure() {
                Object.assign(this.properties, normalizeStyle(this.properties));
                this.color = this.bgcolor = "#00000000";
                this.naturalTitleSize = measureTitle(this.properties, measurement);
                this.setSize(this.size.map((value, index) => Math.max(value, this.naturalTitleSize[index])));
                this.refreshTitle();
            }

            refreshTitle(size = this.size) {
                const element = this.titleElement;
                if (element) {
                    const style = normalizeStyle(this.properties);
                    const width = Math.max(this.naturalTitleSize[0], size[0]);
                    const height = Math.max(this.naturalTitleSize[1], size[1]);
                    const scale = Math.min(window.devicePixelRatio || 1, 2, 8192 / width, 8192 / height, Math.sqrt(4e6 / (width * height)));
                    element.width = Math.max(1, Math.ceil(width * scale));
                    element.height = Math.max(1, Math.ceil(height * scale));
                    element.style.width = `${width}px`;
                    element.style.height = `${height}px`;
                    element.setAttribute("aria-label", style.text);
                    const ctx = element.getContext("2d");
                    if (ctx) {
                        ctx.setTransform(scale, 0, 0, scale, 0, 0);
                        drawTitle(ctx, style, [width, height]);
                    }
                }
                setDirty(this);
            }

            openTitleEditor(focus = "text") {
                if (this.graph !== app.canvas?.graph || app.canvas?.read_only) return;
                const extraWidth = Math.max(0, this.size[0] - this.naturalTitleSize[0]);
                editTitle(this.properties, (style) => this.applyTitleStyle(style), { focus, extraWidth });
            }

            applyTitleStyle(style, fit = false) {
                const graph = this.graph;
                const canvas = app.canvas;
                if (!graph || canvas?.graph !== graph || canvas.read_only) return;
                const value = normalizeStyle(style);
                const sameStyle = Object.keys(value).every((key) => value[key] === this.properties[key]);
                if (sameStyle && (!fit || this.naturalTitleSize.every((value, index) => value === this.size[index]))) return;
                const extra = this.naturalTitleSize.map((value, index) => fit ? 0 : Math.max(0, this.size[index] - value));
                graph.beforeChange?.();
                canvas.emitBeforeChange?.();
                try {
                    Object.assign(this.properties, value);
                    this.naturalTitleSize = measureTitle(value, measurement);
                    this.setSize(this.naturalTitleSize.map((value, index) => value + extra[index]));
                    this.refreshTitle();
                    this.updateArea?.(canvas.ctx);
                } finally {
                    graph.afterChange?.();
                    canvas.emitAfterChange?.();
                    graph.change?.();
                }
            }
        }

        liteGraph.registerNodeType(TYPE, TitleNode);
        TitleNode.category = CATEGORY;
    },
    setup() {
        document.addEventListener("dblclick", (event) => {
            if (!globalThis.LiteGraph?.vueNodesMode || event.button !== 0) return;
            const shell = event.target.closest?.(".lg-node[data-node-id]");
            if (!shell) return;
            const node = app.canvas?.graph?.getNodeById(shell.dataset.nodeId);
            if (node?.type === TYPE) node.openTitleEditor();
        }, true);
    },
    getNodeMenuItems(node) {
        return node.type === TYPE ? makeMenu(node) : [];
    },
});
