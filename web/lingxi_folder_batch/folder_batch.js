import { app } from "../../../../scripts/app.js";
import { api } from "../../../../scripts/api.js";
import {
    GPT_IMAGE2_SIZES,
    IMAGE_RATIOS_BASE,
    IMAGE_RATIOS_BY_PLATFORM,
    getLinkedOriginNode,
    hideWidget,
    isWidgetHidden,
    showWidget,
} from "../lingxi_bridge/shared.js";

const EXEC_NODE = "LingxiFolderBatchExecuteSave";
const SINGLE_NODE = "LingxiSingleFolderBatchGenerate";
const MULTI_NODE = "LingxiMultiFolderBatchGenerate";
const GENERATOR_NODES = new Set([SINGLE_NODE, MULTI_NODE]);
const API_POOL_INPUT_NAMES = ["API池", "api_pool"];
const PROGRESS_WIDGET = "__lx_folder_batch_progress";
const BOTTOM_SPACER_WIDGET = "__lx_folder_batch_bottom_spacer";
const PANEL_HEIGHT = 386;
const COMPACT_PANEL_HEIGHT = 218;
const PROGRESS_WIDE_BREAKPOINT = 520;
const BOTTOM_SPACER_HEIGHT = 5;
const MINI_ICON_SIZE = 16;
const SHOW_PROGRESS_WIDGET = "显示实时进度";
const PROGRESS_ACCENT = "#55e6b5";
const PROGRESS_COLORS = {
    panel: "#061827",
    panelStroke: "rgba(79, 214, 204, 0.14)",
    pillBg: "rgba(79, 214, 204, 0.08)",
    metricBg: "rgba(19, 57, 78, 0.58)",
    text: "#e9fbfa",
    muted: "#91b7be",
    dim: "#6f929a",
    barBg: "#102b3e",
    idle: PROGRESS_ACCENT,
    running: PROGRESS_ACCENT,
    success: PROGRESS_ACCENT,
    failed: "#ff8a70",
    skipped: "#f2c96b",
    cancelled: "#ff8a70",
    api: "#9bd0d5",
};
const OUTPUT_SPECS = {
    [SINGLE_NODE]: [
        ["批量任务", "LX_FOLDER_BATCH_TASKS"],
        ["预览文本", "STRING"],
        ["状态JSON", "STRING"],
        ["预览图像", "IMAGE", "扫描输入文件夹后输出源图预览；最多预览前 64 个任务，不影响实际任务数量。"],
    ],
    [MULTI_NODE]: [
        ["批量任务", "LX_FOLDER_BATCH_TASKS"],
        ["匹配预览图像", "IMAGE"],
        ["配对预览文本", "STRING"],
        ["状态JSON", "STRING"],
    ],
    [EXEC_NODE]: [
        ["预览图像", "IMAGE", "自动输出预览图：任务数 64 以内会尽量全部预览；超过 64 时只预览前 64 张，不影响实际保存数量。"],
        ["状态文本", "STRING"],
        ["状态JSON", "STRING"],
    ],
};

function roundRect(ctx, x, y, w, h, r) {
    const radius = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.lineTo(x + w - radius, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + radius);
    ctx.lineTo(x + w, y + h - radius);
    ctx.quadraticCurveTo(x + w, y + h, x + w - radius, y + h);
    ctx.lineTo(x + radius, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - radius);
    ctx.lineTo(x, y + radius);
    ctx.quadraticCurveTo(x, y, x + radius, y);
    ctx.closePath();
}

function fitText(ctx, text, maxWidth) {
    const value = String(text || "");
    if (maxWidth <= 0) return "";
    if (ctx.measureText(value).width <= maxWidth) return value;
    let out = value;
    while (out.length > 1 && ctx.measureText(out + "...").width > maxWidth) {
        out = out.slice(0, -1);
    }
    return out + "...";
}

function formatDuration(seconds) {
    const total = Math.max(0, Math.round(Number(seconds) || 0));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    return [hours, minutes, secs].map((value) => String(value).padStart(2, "0")).join(":");
}

function currentElapsedSeconds(data) {
    if (data?.state === "running" && Number(data?.started_at) > 0) {
        return Math.max(0, Date.now() / 1000 - Number(data.started_at));
    }
    return Math.max(0, Number(data?.elapsed_seconds || data?.summary?.elapsed_seconds || 0));
}

function formatSecondsPerImage(seconds) {
    const value = Math.max(0, Number(seconds) || 0);
    return `${value.toFixed(1)} 秒/张`;
}

function progressAverageText(data, done, total) {
    const existing = data?.average_text || data?.batch_average_text;
    if (existing && data?.state === "done") return existing;
    const elapsed = currentElapsedSeconds(data);
    const completed = Math.max(0, Number(done) || 0);
    const totalCount = Math.max(0, Number(total) || 0);
    if (completed > 0) return formatSecondsPerImage(elapsed / completed);
    if (data?.state === "done" && totalCount > 0) return formatSecondsPerImage(elapsed / totalCount);
    return "待统计";
}

function progressTimeText(data, done, total) {
    const elapsed = currentElapsedSeconds(data);
    const completed = Math.max(0, Number(done) || 0);
    const totalCount = Math.max(0, Number(total) || 0);
    const elapsedText = data?.state === "running" ? formatDuration(elapsed) : (data?.elapsed_text || formatDuration(elapsed));
    const averageText = progressAverageText(data, done, total);
    if (data?.state === "done") {
        return totalCount > 0
            ? `总耗时 ${elapsedText} · 平均 ${averageText}`
            : `总耗时 ${elapsedText}`;
    }
    if (data?.state === "cancelled") {
        return `已取消 · 已用 ${elapsedText}`;
    }
    if (completed > 0 && totalCount > 0) {
        const secondsPerImage = elapsed / completed;
        const remainingText = formatDuration(secondsPerImage * Math.max(0, totalCount - completed));
        return `已用 ${elapsedText} · 剩余约 ${remainingText} · 平均 ${formatSecondsPerImage(secondsPerImage)}`;
    }
    if (completed <= 0 && totalCount > 0) {
        return `已用 ${elapsedText} · 剩余约 开始后估算 · 平均 开始后统计`;
    }
    return `已用 ${elapsedText} · 剩余约 开始后估算 · 平均 ${averageText}`;
}

function progressTimeParts(data, done, total) {
    const elapsed = currentElapsedSeconds(data);
    const completed = Math.max(0, Number(done) || 0);
    const totalCount = Math.max(0, Number(total) || 0);
    const elapsedText = data?.state === "running" ? formatDuration(elapsed) : (data?.elapsed_text || formatDuration(elapsed));
    const averageText = progressAverageText(data, done, total);
    if (data?.state === "done") {
        return {
            elapsedLabel: "总耗时",
            elapsedValue: elapsedText,
            remainingLabel: "",
            remainingValue: "",
            averageLabel: "平均",
            averageValue: averageText,
        };
    }
    if (completed > 0 && totalCount > 0) {
        const secondsPerImage = elapsed / completed;
        return {
            elapsedLabel: "已用",
            elapsedValue: elapsedText,
            remainingLabel: "剩余约",
            remainingValue: formatDuration(secondsPerImage * Math.max(0, totalCount - completed)),
            averageLabel: "平均",
            averageValue: formatSecondsPerImage(secondsPerImage),
        };
    }
    return {
        elapsedLabel: data?.state === "cancelled" ? "已用" : "已用",
        elapsedValue: elapsedText,
        remainingLabel: data?.state === "cancelled" ? "状态" : "剩余约",
        remainingValue: data?.state === "cancelled" ? "已取消" : "开始后估算",
        averageLabel: "平均",
        averageValue: data?.state === "cancelled" ? "待统计" : "开始后统计",
    };
}

function statusColor(state, failed) {
    if (state === "done") return failed > 0 ? PROGRESS_COLORS.failed : PROGRESS_COLORS.success;
    if (state === "cancelled") return PROGRESS_COLORS.cancelled;
    if (state === "running") return PROGRESS_COLORS.running;
    return PROGRESS_COLORS.idle;
}

function pillWidth(ctx, label, value) {
    ctx.font = "12px sans-serif";
    const text = value === "" || value === null || value === undefined ? String(label) : `${label} ${value}`;
    return Math.ceil(ctx.measureText(text).width) + 18;
}

function drawPill(ctx, x, y, label, value, color) {
    const text = value === "" || value === null || value === undefined ? String(label) : `${label} ${value}`;
    ctx.font = "12px sans-serif";
    const width = Math.ceil(ctx.measureText(text).width) + 18;
    roundRect(ctx, x, y, width, 24, 12);
    ctx.fillStyle = PROGRESS_COLORS.pillBg;
    ctx.fill();
    ctx.fillStyle = color;
    ctx.fillText(text, x + 9, y + 16);
    return width;
}

function progressStateLabel(data, failed) {
    if (data?.state === "done") return data?.state_label || (failed > 0 ? "部分失败" : "已完成");
    if (data?.state === "cancelled") return "已取消";
    if (data?.state === "running") return "执行中";
    return "等待";
}

function cleanProgressMessage(text) {
    return String(text || "").replace(/^提示：/, "").trim();
}

function progressSubText(state, done, total) {
    const remaining = Math.max(0, Number(total || 0) - Number(done || 0));
    if (state === "running" && done > 0 && remaining > 0) {
        return `总任务 ${total} · 剩余 ${remaining}`;
    }
    return `总任务 ${total} · 已处理 ${done}`;
}

function progressDetailText(data, state, done, total, stateLabel) {
    const remaining = Math.max(0, Number(total || 0) - Number(done || 0));
    if (state === "done") {
        return `结果：${cleanProgressMessage(data.message || stateLabel)}`;
    }
    if (state === "cancelled") {
        return `当前：已取消，已处理 ${done} / ${total}`;
    }
    if (state === "running") {
        return `当前：执行中，剩余 ${remaining} 个任务`;
    }
    return "当前：等待执行";
}

function shortPath(path) {
    const value = String(path || "");
    if (!value) return "";
    const normalized = value.replace(/\//g, "\\");
    const parts = normalized.split("\\").filter(Boolean);
    if (parts.length <= 2) return value;
    return `...\\${parts.slice(-2).join("\\")}`;
}

function drawGlowBar(ctx, x, y, w, color) {
    const inset = 4;
    const barH = 5;
    const barW = Math.max(0, w - inset * 2);
    if (barW <= 0) return;
    ctx.save();
    ctx.globalAlpha = 0.82;
    roundRect(ctx, x + inset, y, barW, barH, 3);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.restore();
}

function drawDivider(ctx, x1, y, x2) {
    ctx.strokeStyle = "rgba(151, 215, 222, 0.16)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x1, y);
    ctx.lineTo(x2, y);
    ctx.stroke();
}

function drawVerticalDivider(ctx, x, y1, y2) {
    ctx.strokeStyle = "rgba(151, 215, 222, 0.16)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, y1);
    ctx.lineTo(x, y2);
    ctx.stroke();
}

function drawValueCell(ctx, x, y, width, label, value, color) {
    const compact = width < 92;
    ctx.font = `${compact ? 12 : 14}px sans-serif`;
    ctx.fillStyle = PROGRESS_COLORS.muted;
    ctx.fillText(fitText(ctx, label, width), x, y);
    ctx.font = `bold ${compact ? 24 : 30}px sans-serif`;
    ctx.fillStyle = color;
    ctx.fillText(fitText(ctx, String(value ?? 0), width), x, y + (compact ? 30 : 34));
}

function drawTinyCell(ctx, x, y, width, label, value, color = PROGRESS_COLORS.text, icon = "") {
    const compact = width < 82;
    const iconW = icon ? 24 : 0;
    if (icon) drawMiniIcon(ctx, icon, x, y + 3, PROGRESS_ACCENT);
    const textX = x + iconW;
    const textW = Math.max(20, width - iconW);
    ctx.font = `${compact ? 11 : 12}px sans-serif`;
    ctx.fillStyle = PROGRESS_COLORS.muted;
    ctx.fillText(fitText(ctx, label, textW), textX, y);
    ctx.font = `bold ${compact ? 14 : 18}px sans-serif`;
    ctx.fillStyle = color;
    ctx.fillText(fitText(ctx, String(value || "--"), textW), textX, y + 26);
}

function drawInlineCell(ctx, x, y, width, text, icon = "", color = PROGRESS_COLORS.muted) {
    const iconW = icon ? 28 : 0;
    if (icon) drawMiniIcon(ctx, icon, x, y - MINI_ICON_SIZE + 2, PROGRESS_ACCENT, MINI_ICON_SIZE);
    ctx.font = "13px sans-serif";
    ctx.fillStyle = color;
    ctx.fillText(fitText(ctx, text, Math.max(20, width - iconW)), x + iconW, y);
}

function drawTimeCell(ctx, x, y, width, label, value, icon = "clock") {
    const iconW = icon ? 28 : 0;
    if (icon) drawMiniIcon(ctx, icon, x, y - MINI_ICON_SIZE + 3, PROGRESS_ACCENT, MINI_ICON_SIZE);
    const textX = x + iconW;
    const textW = Math.max(24, width - iconW);
    ctx.font = "12px sans-serif";
    ctx.fillStyle = PROGRESS_COLORS.muted;
    ctx.fillText(fitText(ctx, label, textW), textX, y);
    drawTimeValue(ctx, textX, y + 27, textW, value, width < 104 ? 16 : 18);
}

function drawTimeValue(ctx, x, y, width, value, size) {
    const text = String(value || "--");
    if (text.startsWith("开始后")) {
        ctx.font = "13px sans-serif";
        ctx.fillStyle = PROGRESS_COLORS.dim;
        ctx.fillText(fitText(ctx, text, width), x, y);
        return;
    }
    const unit = "秒/张";
    const unitIndex = text.lastIndexOf(unit);
    if (unitIndex <= 0) {
        ctx.font = `bold ${size}px sans-serif`;
        ctx.fillStyle = PROGRESS_COLORS.text;
        ctx.fillText(fitText(ctx, text, width), x, y);
        return;
    }

    const numberText = text.slice(0, unitIndex).trimEnd();
    const unitSize = Math.max(11, size - 5);
    ctx.font = `bold ${size}px sans-serif`;
    const numberW = ctx.measureText(numberText).width;
    ctx.font = `${unitSize}px sans-serif`;
    const unitW = ctx.measureText(unit).width;
    if (numberW + unitW + 4 > width) {
        ctx.font = `bold ${size}px sans-serif`;
        ctx.fillStyle = PROGRESS_COLORS.text;
        ctx.fillText(fitText(ctx, text, width), x, y);
        return;
    }

    ctx.font = `bold ${size}px sans-serif`;
    ctx.fillStyle = PROGRESS_COLORS.text;
    ctx.fillText(numberText, x, y);
    ctx.font = `${unitSize}px sans-serif`;
    ctx.fillStyle = PROGRESS_COLORS.muted;
    ctx.fillText(unit, x + numberW + 4, y);
}

function drawStatusIcon(ctx, x, y, color, failed = 0, size = 18, lineWidth = 2) {
    const cx = x + size / 2;
    const cy = y + size / 2;
    const r = size * 0.39;
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = lineWidth;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.stroke();
    if (failed > 0) {
        const d = size * 0.18;
        ctx.beginPath();
        ctx.moveTo(cx - d, cy - d);
        ctx.lineTo(cx + d, cy + d);
        ctx.moveTo(cx + d, cy - d);
        ctx.lineTo(cx - d, cy + d);
        ctx.stroke();
    } else {
        ctx.beginPath();
        ctx.moveTo(cx - size * 0.23, cy);
        ctx.lineTo(cx - size * 0.06, cy + size * 0.17);
        ctx.lineTo(cx + size * 0.28, cy - size * 0.23);
        ctx.stroke();
    }
    ctx.restore();
}

function drawFolderIcon(ctx, x, y, color) {
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x, y + 6);
    ctx.lineTo(x + 8, y + 6);
    ctx.lineTo(x + 11, y + 10);
    ctx.lineTo(x + 24, y + 10);
    ctx.quadraticCurveTo(x + 27, y + 10, x + 27, y + 13);
    ctx.lineTo(x + 27, y + 23);
    ctx.quadraticCurveTo(x + 27, y + 26, x + 24, y + 26);
    ctx.lineTo(x + 3, y + 26);
    ctx.quadraticCurveTo(x, y + 26, x, y + 23);
    ctx.closePath();
    ctx.stroke();
    ctx.restore();
}

function drawInfoRow(ctx, x, y, width, text, iconKind, iconColor, textColor = PROGRESS_COLORS.muted, failed = 0) {
    const iconX = x;
    const iconTop = y - MINI_ICON_SIZE + 2;
    const textX = x + 30;
    const textW = Math.max(24, width - 30);
    if (iconKind === "status") {
        drawStatusIcon(ctx, iconX, iconTop, iconColor, failed, MINI_ICON_SIZE, 1.7);
    } else if (iconKind === "output") {
        drawFolderMiniIcon(ctx, iconX, iconTop, iconColor, MINI_ICON_SIZE);
    } else if (iconKind === "folder") {
        drawFolderMiniIcon(ctx, iconX, iconTop, iconColor, MINI_ICON_SIZE);
    }
    ctx.font = "13px sans-serif";
    ctx.fillStyle = textColor;
    ctx.fillText(fitText(ctx, text, textW), textX, y);
}

function drawKeyIcon(ctx, x, y, color) {
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(x + 6, y + 8, 4, 0, Math.PI * 2);
    ctx.moveTo(x + 10, y + 8);
    ctx.lineTo(x + 20, y + 8);
    ctx.lineTo(x + 20, y + 12);
    ctx.moveTo(x + 15, y + 8);
    ctx.lineTo(x + 15, y + 11);
    ctx.stroke();
    ctx.restore();
}

function drawStackIcon(ctx, x, y, color) {
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    for (let i = 0; i < 3; i++) {
        const yy = y + 2 + i * 5;
        ctx.beginPath();
        ctx.moveTo(x + 12, yy);
        ctx.lineTo(x + 20, yy + 4);
        ctx.lineTo(x + 12, yy + 8);
        ctx.lineTo(x + 4, yy + 4);
        ctx.closePath();
        ctx.stroke();
    }
    ctx.restore();
}

function drawUsersIcon(ctx, x, y, color) {
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    ctx.moveTo(x + 12, y + 5);
    ctx.lineTo(x + 5, y + 16);
    ctx.moveTo(x + 12, y + 5);
    ctx.lineTo(x + 19, y + 16);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(x + 12, y + 5, 3.2, 0, Math.PI * 2);
    ctx.arc(x + 5, y + 16, 3.2, 0, Math.PI * 2);
    ctx.arc(x + 19, y + 16, 3.2, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
}

function drawClockIcon(ctx, x, y, color) {
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(x + 10, y + 10, 9, 0, Math.PI * 2);
    ctx.moveTo(x + 10, y + 5);
    ctx.lineTo(x + 10, y + 10);
    ctx.lineTo(x + 15, y + 13);
    ctx.stroke();
    ctx.restore();
}

function drawHourglassIcon(ctx, x, y, color) {
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    ctx.moveTo(x + 5, y + 3);
    ctx.lineTo(x + 15, y + 3);
    ctx.lineTo(x + 10, y + 10);
    ctx.lineTo(x + 15, y + 17);
    ctx.lineTo(x + 5, y + 17);
    ctx.lineTo(x + 10, y + 10);
    ctx.closePath();
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x + 8, y + 7);
    ctx.lineTo(x + 12, y + 7);
    ctx.moveTo(x + 8, y + 14);
    ctx.lineTo(x + 12, y + 14);
    ctx.stroke();
    ctx.restore();
}

function drawGaugeIcon(ctx, x, y, color) {
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.arc(x + 10, y + 11, 8, Math.PI * 0.75, Math.PI * 2.2);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x + 10, y + 11);
    ctx.lineTo(x + 14, y + 8);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(x + 10, y + 11, 1.5, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
}

function drawScaledIcon(ctx, x, y, size, viewW, viewH, draw) {
    const scale = size / Math.max(viewW, viewH);
    ctx.save();
    ctx.translate(x + (size - viewW * scale) / 2, y + (size - viewH * scale) / 2);
    ctx.scale(scale, scale);
    draw();
    ctx.restore();
}

function drawFolderMiniIcon(ctx, x, y, color, size = MINI_ICON_SIZE) {
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.7;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    ctx.moveTo(x + size * 0.08, y + size * 0.36);
    ctx.lineTo(x + size * 0.36, y + size * 0.36);
    ctx.lineTo(x + size * 0.48, y + size * 0.5);
    ctx.lineTo(x + size * 0.9, y + size * 0.5);
    ctx.quadraticCurveTo(x + size * 0.96, y + size * 0.5, x + size * 0.96, y + size * 0.58);
    ctx.lineTo(x + size * 0.96, y + size * 0.86);
    ctx.quadraticCurveTo(x + size * 0.96, y + size * 0.94, x + size * 0.88, y + size * 0.94);
    ctx.lineTo(x + size * 0.12, y + size * 0.94);
    ctx.quadraticCurveTo(x + size * 0.04, y + size * 0.94, x + size * 0.04, y + size * 0.86);
    ctx.lineTo(x + size * 0.04, y + size * 0.46);
    ctx.quadraticCurveTo(x + size * 0.04, y + size * 0.36, x + size * 0.08, y + size * 0.36);
    ctx.stroke();
    ctx.restore();
}

function drawOutputIcon(ctx, x, y, color, size = MINI_ICON_SIZE) {
    const cx = x + size / 2;
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.7;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    ctx.moveTo(cx, y + size * 0.12);
    ctx.lineTo(cx, y + size * 0.58);
    ctx.moveTo(cx - size * 0.22, y + size * 0.38);
    ctx.lineTo(cx, y + size * 0.62);
    ctx.lineTo(cx + size * 0.22, y + size * 0.38);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x + size * 0.18, y + size * 0.72);
    ctx.lineTo(x + size * 0.18, y + size * 0.86);
    ctx.quadraticCurveTo(x + size * 0.18, y + size * 0.94, x + size * 0.28, y + size * 0.94);
    ctx.lineTo(x + size * 0.72, y + size * 0.94);
    ctx.quadraticCurveTo(x + size * 0.82, y + size * 0.94, x + size * 0.82, y + size * 0.86);
    ctx.lineTo(x + size * 0.82, y + size * 0.72);
    ctx.stroke();
    ctx.restore();
}

function drawMiniIcon(ctx, kind, x, y, color, size = MINI_ICON_SIZE) {
    const iconMap = {
        key: { w: 22, h: 18, draw: () => drawKeyIcon(ctx, 0, 1, color) },
        stack: { w: 24, h: 22, draw: () => drawStackIcon(ctx, 0, 0, color) },
        users: { w: 24, h: 21, draw: () => drawUsersIcon(ctx, 0, 0, color) },
        clock: { w: 20, h: 20, draw: () => drawClockIcon(ctx, 0, 0, color) },
        hourglass: { w: 20, h: 20, draw: () => drawHourglassIcon(ctx, 0, 0, color) },
        gauge: { w: 20, h: 20, draw: () => drawGaugeIcon(ctx, 0, 0, color) },
    };
    const icon = iconMap[kind];
    if (!icon) return null;
    return drawScaledIcon(ctx, x, y, size, icon.w, icon.h, icon.draw);
}

function drawMetric(ctx, x, y, width, label, value, color, labelColor = PROGRESS_COLORS.muted) {
    roundRect(ctx, x, y, width, 44, 6);
    ctx.fillStyle = PROGRESS_COLORS.metricBg;
    ctx.fill();
    ctx.font = "12px sans-serif";
    ctx.fillStyle = labelColor;
    ctx.fillText(label, x + 10, y + 16);
    ctx.font = "bold 22px sans-serif";
    ctx.fillStyle = color;
    ctx.fillText(String(value ?? 0), x + 10, y + 38);
}

function progressLayout(node, width) {
    const nodeW = Number(node?.size?.[0]);
    const drawW = Number(width);
    const availableW = Number.isFinite(nodeW) && nodeW > 0
        ? nodeW
        : Number.isFinite(drawW) && drawW > 0 ? drawW : 360;
    const panelW = Math.max(220, availableW - 20);
    const contentW = panelW - 28;
    const dashboardLayout = contentW >= PROGRESS_WIDE_BREAKPOINT;
    const panelH = dashboardLayout ? PANEL_HEIGHT : COMPACT_PANEL_HEIGHT;
    return { availableW, panelW, contentW, dashboardLayout, panelH };
}

function progressPanelHeight(node, width) {
    return progressLayout(node, width).panelH;
}

function queueProgressResize(node, minHeight = 0) {
    node._lxFolderBatchProgressMinHeight = Math.max(
        Number(node._lxFolderBatchProgressMinHeight) || 0,
        Number(minHeight) || 0,
    );
    if (node._lxFolderBatchProgressResizeQueued) return;
    node._lxFolderBatchProgressResizeQueued = true;
    window.setTimeout(() => {
        const requestedMinHeight = Number(node._lxFolderBatchProgressMinHeight) || 0;
        node._lxFolderBatchProgressMinHeight = 0;
        node._lxFolderBatchProgressResizeQueued = false;
        resizeNode(node, requestedMinHeight);
    }, 0);
}

function syncProgressPanelLayout(node, y, panelH) {
    const currentH = Number(node?.size?.[1]) || 0;
    const desiredBottom = Math.ceil((Number(y) || 0) + panelH + 8);
    const heightChanged = node._lxFolderBatchProgressPanelH !== panelH;
    const tooShort = currentH > 0 && currentH < desiredBottom;
    if (!heightChanged && !tooShort) return;
    node._lxFolderBatchProgressPanelH = panelH;
    queueProgressResize(node, tooShort ? desiredBottom : 0);
}

function drawProgressWidget(ctx, node, width, y) {
    if (!progressEnabled(node)) return;
    const data = node._lxFolderBatchProgress || {};
    const { availableW, panelW, contentW, dashboardLayout, panelH } = progressLayout(node, width);
    const x = 10;
    const total = Number(data.total || 0);
    const done = Number(data.done || 0);
    const success = Number(data.success || 0);
    const failed = Number(data.failed || 0);
    const skipped = Number(data.skipped || 0);
    const percent = total > 0 ? Math.max(0, Math.min(100, Math.round((done / total) * 100))) : 0;
    const state = data.state || "idle";
    const accent = statusColor(state, failed);
    const contentX = x + 14;
    const concurrency = data.actual_concurrency ?? data.concurrency ?? 0;
    const apiCount = Number(data.api_channel_count || 0);
    const apiKeyCount = Number(data.api_key_count || data.summary?.api_key_count || apiCount || 0);
    const resolvedPerKey = Number(data.resolved_per_key_concurrency || 0);
    const perKeyText = data.per_key_concurrency_auto
        ? "0=自动"
        : String(resolvedPerKey || data.requested_per_key_concurrency || 4);
    const concurrencyText = `Key ${apiKeyCount} · 每Key ${perKeyText} · 总并发 ${concurrency || 0}`;
    const timeParts = progressTimeParts(data, done, total);
    const stateLabel = progressStateLabel(data, failed);
    const summaryText = progressSubText(state, done, total);
    const detailText = progressDetailText(data, state, done, total, stateLabel);
    syncProgressPanelLayout(node, y, panelH);

    ctx.save();
    ctx.beginPath();
    ctx.rect(0, y, Math.max(1, availableW), panelH);
    ctx.clip();

    roundRect(ctx, x, y + 6, panelW, panelH - 12, 8);
    ctx.fillStyle = PROGRESS_COLORS.panel;
    ctx.fill();
    ctx.strokeStyle = PROGRESS_COLORS.panelStroke;
    ctx.lineWidth = 1;
    ctx.stroke();

    drawGlowBar(ctx, x, y + 6, panelW, accent);

    if (dashboardLayout) {
        const compact = contentW < 520;
        const leftInset = compact ? 8 : 22;
        const leftX = contentX + leftInset;
        const leftW = Math.min(compact ? 190 : 340, Math.max(compact ? 140 : 220, Math.floor(contentW * (compact ? 0.32 : 0.34))));
        const gap = compact ? 24 : 42;
        const rightX = leftX + leftW + gap;
        const rightW = Math.max(compact ? 170 : 260, contentX + contentW - rightX);
        const rightInset = compact ? 12 : 20;
        const rightContentX = rightX + rightInset;
        const rightContentW = Math.max(120, rightW - rightInset);
        const dividerX = leftX + leftW + Math.floor(gap / 2);
        const mainTop = y + (compact ? 96 : 106);
        const titleY = y + (compact ? 64 : 72);
        const pillY = y + (compact ? 80 : 90);

        ctx.font = `bold ${compact ? 22 : 26}px sans-serif`;
        ctx.fillStyle = PROGRESS_COLORS.text;
        ctx.fillText("批量执行进度", leftX, titleY);

        if (panelW >= 330) {
            drawPill(ctx, leftX, pillY, stateLabel, "", accent);
        }

        drawVerticalDivider(ctx, dividerX, y + 52, y + panelH - 42);

        ctx.font = `bold ${compact ? 54 : 78}px sans-serif`;
        ctx.fillStyle = accent;
        ctx.fillText(`${percent}%`, leftX, mainTop + (compact ? 72 : 92));

        const barX = leftX;
        const barY = mainTop + (compact ? 88 : 112);
        const barW = leftW;
        const barH = 12;
        roundRect(ctx, barX, barY, barW, barH, 6);
        ctx.fillStyle = PROGRESS_COLORS.barBg;
        ctx.fill();
        if (percent > 0) {
            roundRect(ctx, barX, barY, Math.max(8, Math.round(barW * percent / 100)), barH, 6);
            ctx.fillStyle = accent;
            ctx.fill();
        }

        ctx.font = `bold ${compact ? 24 : 26}px sans-serif`;
        ctx.fillStyle = PROGRESS_COLORS.text;
        ctx.fillText(fitText(ctx, `${done} / ${total}`, leftW), leftX, mainTop + (compact ? 136 : 164));
        ctx.font = `${compact ? 12 : 13}px sans-serif`;
        ctx.fillStyle = PROGRESS_COLORS.muted;
        ctx.fillText(fitText(ctx, summaryText, leftW), leftX, mainTop + (compact ? 160 : 188));

        const statY = y + (compact ? 78 : 76);
        const statCellW = rightContentW / 3;
        drawValueCell(ctx, rightContentX, statY, statCellW - 14, "完成", success, PROGRESS_COLORS.success);
        drawVerticalDivider(ctx, rightContentX + statCellW, statY - 4, statY + 52);
        drawValueCell(ctx, rightContentX + statCellW + 20, statY, statCellW - 28, "失败", failed, failed > 0 ? PROGRESS_COLORS.failed : PROGRESS_COLORS.muted);
        drawVerticalDivider(ctx, rightContentX + statCellW * 2, statY - 4, statY + 52);
        drawValueCell(ctx, rightContentX + statCellW * 2 + 20, statY, statCellW - 20, "跳过", skipped, PROGRESS_COLORS.skipped);

        drawDivider(ctx, rightX, y + (compact ? 148 : 146), rightX + rightW);

        const runY = y + (compact ? 188 : 186);
        if (state === "idle") {
            drawInlineCell(ctx, rightContentX, runY, rightContentW, "等待任务开始后解析 API 通道", "key", PROGRESS_COLORS.dim);
        } else {
            const runCellW = rightContentW / 3;
            drawInlineCell(ctx, rightContentX, runY, runCellW - 12, `Key ${apiKeyCount || "待定"}`, "key");
            drawVerticalDivider(ctx, rightContentX + runCellW, runY - 24, runY + 14);
            drawInlineCell(ctx, rightContentX + runCellW + 18, runY, runCellW - 26, `每Key ${perKeyText || "待定"}`, "stack");
            drawVerticalDivider(ctx, rightContentX + runCellW * 2, runY - 24, runY + 14);
            drawInlineCell(ctx, rightContentX + runCellW * 2 + 18, runY, runCellW - 18, `总并发 ${concurrency || "待定"}`, "users");
        }

        drawDivider(ctx, rightX, y + (compact ? 226 : 224), rightX + rightW);

        const timeY = y + (compact ? 256 : 254);
        if (state === "done") {
            const timeCellW = rightContentW / 2;
            drawTimeCell(ctx, rightContentX, timeY, timeCellW - 14, timeParts.elapsedLabel, timeParts.elapsedValue, "clock");
            drawVerticalDivider(ctx, rightContentX + timeCellW, timeY - 20, timeY + 35);
            drawTimeCell(ctx, rightContentX + timeCellW + 20, timeY, timeCellW - 20, timeParts.averageLabel, timeParts.averageValue, "gauge");
        } else {
            const timeCellW = rightContentW / 3;
            drawTimeCell(ctx, rightContentX, timeY, timeCellW - 12, timeParts.elapsedLabel, timeParts.elapsedValue, "clock");
            drawVerticalDivider(ctx, rightContentX + timeCellW, timeY - 20, timeY + 35);
            drawTimeCell(ctx, rightContentX + timeCellW + 18, timeY, timeCellW - 26, timeParts.remainingLabel, timeParts.remainingValue, "hourglass");
            drawVerticalDivider(ctx, rightContentX + timeCellW * 2, timeY - 20, timeY + 35);
            drawTimeCell(ctx, rightContentX + timeCellW * 2 + 18, timeY, timeCellW - 18, timeParts.averageLabel, timeParts.averageValue, "gauge");
        }

        if (state !== "idle") {
            drawDivider(ctx, rightX, y + (compact ? 306 : 304), rightX + rightW);

            const detailY = y + (compact ? 334 : 332);
            drawInfoRow(ctx, rightContentX, detailY, rightContentW, detailText, "status", accent, PROGRESS_COLORS.muted, failed);
            if (data.output_root) {
                const outputY = y + (compact ? 360 : 358);
                drawInfoRow(ctx, rightContentX, outputY, rightContentW, `输出：${data.output_root}`, "output", accent, PROGRESS_COLORS.dim);
            }
        }
        ctx.restore();
        return;
    }

    const titleText = contentW < 260 ? "批量执行" : "批量执行进度";
    const statePillW = pillWidth(ctx, stateLabel, "");
    const showStatePill = contentW >= 190;
    const titleMaxW = showStatePill ? Math.max(70, contentW - statePillW - 12) : contentW;

    ctx.font = `bold ${contentW < 260 ? 18 : 20}px sans-serif`;
    ctx.fillStyle = PROGRESS_COLORS.text;
    ctx.fillText(fitText(ctx, titleText, titleMaxW), contentX, y + 42);

    if (showStatePill) {
        drawPill(ctx, contentX + contentW - statePillW, y + 24, stateLabel, "", accent);
    }

    const percentSize = contentW < 300 ? 38 : 50;
    const percentY = y + (contentW < 300 ? 88 : 92);
    ctx.font = `bold ${percentSize}px sans-serif`;
    ctx.fillStyle = accent;
    ctx.fillText(`${percent}%`, contentX, percentY);

    const sideW = Math.max(78, Math.min(190, contentW - (contentW < 300 ? 112 : 140)));
    const sideX = contentX + contentW - sideW;
    ctx.font = `bold ${contentW < 300 ? 19 : 22}px sans-serif`;
    ctx.fillStyle = PROGRESS_COLORS.text;
    ctx.fillText(fitText(ctx, `${done} / ${total}`, sideW), sideX, y + 76);
    ctx.font = "12px sans-serif";
    ctx.fillStyle = PROGRESS_COLORS.muted;
    ctx.fillText(fitText(ctx, summaryText, sideW), sideX, y + 98);

    const barX = contentX;
    const barY = y + 112;
    const barW = contentW;
    const barH = 12;
    roundRect(ctx, barX, barY, barW, barH, 6);
    ctx.fillStyle = PROGRESS_COLORS.barBg;
    ctx.fill();
    if (percent > 0) {
        roundRect(ctx, barX, barY, Math.max(8, Math.round(barW * percent / 100)), barH, 6);
        ctx.fillStyle = accent;
        ctx.fill();
    }

    const statLineY = y + 146;
    ctx.font = `bold ${contentW < 300 ? 13 : 14}px sans-serif`;
    if (contentW < 360) {
        ctx.fillStyle = PROGRESS_COLORS.text;
        ctx.fillText(fitText(ctx, `完成 ${success} · 失败 ${failed} · 跳过 ${skipped}`, contentW), contentX, statLineY);
    } else {
        const statCellW = contentW / 3;
        ctx.fillStyle = PROGRESS_COLORS.success;
        ctx.fillText(fitText(ctx, `完成 ${success}`, statCellW - 8), contentX, statLineY);
        ctx.fillStyle = failed > 0 ? PROGRESS_COLORS.failed : PROGRESS_COLORS.muted;
        ctx.fillText(fitText(ctx, `失败 ${failed}`, statCellW - 8), contentX + statCellW, statLineY);
        ctx.fillStyle = PROGRESS_COLORS.skipped;
        ctx.fillText(fitText(ctx, `跳过 ${skipped}`, statCellW - 8), contentX + statCellW * 2, statLineY);
    }

    const elapsedLabel = state === "done" ? "耗时" : timeParts.elapsedLabel;
    const compactTimeText = `${elapsedLabel} ${timeParts.elapsedValue} · ${timeParts.averageLabel} ${timeParts.averageValue}`;
    ctx.font = "13px sans-serif";
    ctx.fillStyle = PROGRESS_COLORS.text;
    ctx.fillText(fitText(ctx, compactTimeText, contentW), contentX, y + 174);

    ctx.font = "13px sans-serif";
    ctx.fillStyle = PROGRESS_COLORS.muted;
    ctx.fillText(fitText(ctx, detailText, contentW), contentX, y + 199);
    ctx.restore();
}

function findWidget(node, name) {
    return (node.widgets || []).find((widget) => widget.name === name);
}

function linkedNode(node, inputName) {
    const input = node.inputs?.find((item) => item.name === inputName);
    return getLinkedOriginNode(node, input);
}

function linkedInputNodes(node) {
    const result = [];
    for (const input of node?.inputs || []) {
        const linked = getLinkedOriginNode(node, input);
        if (linked) result.push(linked);
    }
    return result;
}

function platformFromNodeWidget(node) {
    return node?.widgets?.find((item) => item.name === "platform")?.value || null;
}

function uniqueValues(values) {
    return [...new Set(values.filter(Boolean))];
}

function platformsFromApiNode(node, seen = new Set()) {
    if (!node || seen.has(node.id)) return [];
    seen.add(node.id);

    const platform = platformFromNodeWidget(node);
    if (platform) return [platform];

    const platforms = [];
    for (const linked of linkedInputNodes(node)) {
        platforms.push(...platformsFromApiNode(linked, seen));
    }
    return uniqueValues(platforms);
}

function connectedPlatforms(node) {
    for (const inputName of API_POOL_INPUT_NAMES) {
        const apiNode = linkedNode(node, inputName);
        if (!apiNode) continue;
        const platforms = platformsFromApiNode(apiNode);
        if (platforms.length) return platforms;
    }
    return [];
}

function allRatios() {
    const seen = new Set();
    const result = [];
    for (const ratios of Object.values(IMAGE_RATIOS_BY_PLATFORM)) {
        for (const ratio of ratios || IMAGE_RATIOS_BASE) {
            if (!seen.has(ratio)) {
                seen.add(ratio);
                result.push(ratio);
            }
        }
    }
    return result.length ? result : IMAGE_RATIOS_BASE;
}

function unionRatios(platforms) {
    if (!platforms.length) return allRatios();
    const seen = new Set();
    const result = [];
    for (const platform of platforms) {
        const ratios = IMAGE_RATIOS_BY_PLATFORM[platform] || IMAGE_RATIOS_BASE;
        for (const ratio of ratios) {
            if (!seen.has(ratio)) {
                seen.add(ratio);
                result.push(ratio);
            }
        }
    }
    return result.length ? result : IMAGE_RATIOS_BASE;
}

function refreshComboWidget(node, widgetName) {
    const widget = findWidget(node, widgetName);
    const el = widget?.inputEl;
    if (!widget || !el || el.tagName !== "SELECT") return;
    const values = widget.options?.values || [];
    el.options.length = 0;
    for (const value of values) {
        const opt = document.createElement("option");
        opt.value = value;
        opt.textContent = value;
        el.appendChild(opt);
    }
    el.value = widget.value;
    node.setDirtyCanvas(true, true);
}

function syncGeneratorControls(node) {
    if (!GENERATOR_NODES.has(node?.comfyClass) || !node.widgets) return;
    const platforms = connectedPlatforms(node);
    const hasGptImage2 = platforms.length === 0 || platforms.some(platform => ["gpt-image2", "gpt-image2.5"].includes(platform));

    const ratio = findWidget(node, "ratio");
    if (ratio) {
        const values = unionRatios(platforms);
        ratio.options.values = values;
        if (!values.includes(ratio.value)) {
            ratio.value = values.includes("auto") ? "auto" : values[0];
        }
        refreshComboWidget(node, "ratio");
    }

    const size = findWidget(node, "size");
    if (size) {
        const values = hasGptImage2 ? GPT_IMAGE2_SIZES : ["1K", "2K", "4K"];
        size.options.values = values;
        if (!values.includes(size.value)) {
            size.value = values.includes("2K") ? "2K" : values[0];
        }
        refreshComboWidget(node, "size");
    }

    for (const name of ["quality", "moderation"]) {
        const widget = findWidget(node, name);
        if (!widget) continue;
        if (hasGptImage2) {
            showWidget(widget);
        } else if (!isWidgetHidden(widget)) {
            hideWidget(widget);
        }
    }

    resizeNode(node);
}

function installGeneratorWatcher(node) {
    if (!GENERATOR_NODES.has(node?.comfyClass) || node.__lxFolderBatchApiWatcher) return;
    node.__lxFolderBatchApiWatcher = window.setInterval(() => {
        if (!node.widgets) {
            window.clearInterval(node.__lxFolderBatchApiWatcher);
            node.__lxFolderBatchApiWatcher = null;
            return;
        }
        const key = connectedPlatforms(node).join("|");
        if (key !== node.__lxFolderBatchApiKey) {
            node.__lxFolderBatchApiKey = key;
            syncGeneratorControls(node);
        }
    }, 250);

    const originalOnRemoved = node.onRemoved;
    node.onRemoved = function () {
        if (node.__lxFolderBatchApiWatcher) {
            window.clearInterval(node.__lxFolderBatchApiWatcher);
            node.__lxFolderBatchApiWatcher = null;
        }
        if (originalOnRemoved) originalOnRemoved.call(this);
    };
}

function setupGeneratorNode(node) {
    ensureBottomSpacer(node);
    syncGeneratorControls(node);
    installGeneratorWatcher(node);
}

function ensureBottomSpacer(node) {
    if (!node?.widgets) return;
    let spacer = node.widgets.find((widget) => widget?.name === BOTTOM_SPACER_WIDGET);
    if (!spacer) {
        spacer = {
            name: BOTTOM_SPACER_WIDGET,
            type: "custom",
            value: "",
            serialize: false,
            options: { canvasOnly: true },
            computeSize: () => [0, BOTTOM_SPACER_HEIGHT],
            draw: () => {},
        };
        node.widgets.push(spacer);
    } else {
        spacer.hidden = false;
        spacer.type = "custom";
        spacer.value = "";
        spacer.serialize = false;
        spacer.options = { ...(spacer.options || {}), canvasOnly: true };
        spacer.computeSize = () => [0, BOTTOM_SPACER_HEIGHT];
        spacer.draw = () => {};
    }

    const index = node.widgets.indexOf(spacer);
    if (index !== node.widgets.length - 1) {
        node.widgets.splice(index, 1);
        node.widgets.push(spacer);
    }
}

function removeBottomSpacer(node) {
    if (!node?.widgets) return;
    const index = node.widgets.findIndex((widget) => widget?.name === BOTTOM_SPACER_WIDGET);
    if (index >= 0) {
        node.widgets.splice(index, 1);
    }
}

function progressEnabled(node) {
    return !!findWidget(node, SHOW_PROGRESS_WIDGET)?.value;
}

let progressTimer = null;

function hasRunningProgress() {
    const nodes = app.graph?._nodes || [];
    return nodes.some((node) => (
        node?.comfyClass === EXEC_NODE
        && progressEnabled(node)
        && node?._lxFolderBatchProgress?.state === "running"
    ));
}

function ensureProgressTimer() {
    if (progressTimer) return;
    progressTimer = window.setInterval(() => {
        if (!hasRunningProgress()) {
            window.clearInterval(progressTimer);
            progressTimer = null;
            return;
        }
        app.graph?.setDirtyCanvas(true, false);
    }, 1000);
}

function resizeNode(node, minHeight = 0) {
    window.setTimeout(() => {
        if (node.computeSize && node.setSize) {
            const computed = node.computeSize();
            const currentW = Number(node?.size?.[0]);
            const currentH = Number(node?.size?.[1]);
            const computedH = Number(computed?.[1]);
            const requestedMinH = Number(minHeight) || 0;
            const nextW = Number.isFinite(currentW) && currentW > 0 ? currentW : Number(computed?.[0]) || 440;
            const nextH = Math.max(
                requestedMinH,
                Number.isFinite(currentH) && currentH > 0 ? currentH : 0,
                Number.isFinite(computedH) && computedH > 0
                    ? computedH
                    : Number.isFinite(currentH) && currentH > 0 ? currentH : 320,
            );
            node.setSize([nextW, nextH]);
        }
        app.graph?.setDirtyCanvas(true, true);
    }, 0);
}

function syncOutputs(node) {
    const spec = OUTPUT_SPECS[node?.comfyClass];
    if (!spec || !node.outputs) return;
    while (node.outputs.length > spec.length) {
        node.removeOutput(node.outputs.length - 1);
    }
    while (node.outputs.length < spec.length) {
        const [name, type] = spec[node.outputs.length];
        node.addOutput(name, type);
    }
    for (let index = 0; index < spec.length; index += 1) {
        const [name, type, tooltip] = spec[index];
        node.outputs[index].name = name;
        node.outputs[index].type = type;
        node.outputs[index].tooltip = tooltip || "";
    }
    app.graph?.setDirtyCanvas(true, true);
}

function ensureProgressWidget(node) {
    if (!node.widgets) return;
    if (node.widgets.some((widget) => widget.name === PROGRESS_WIDGET)) return;
    node.widgets.push({
        name: PROGRESS_WIDGET,
        type: "custom",
        value: "",
        serialize: false,
        options: { canvasOnly: true },
        computeSize: (width) => [
            0,
            progressEnabled(node) ? progressPanelHeight(node, width) : 0,
        ],
        draw: (ctx, nodeArg, width, y) => drawProgressWidget(ctx, nodeArg, width, y),
    });
    resizeNode(node);
}

function installProgressToggle(node) {
    const widget = findWidget(node, SHOW_PROGRESS_WIDGET);
    if (!widget || widget.__lxFolderBatchToggle) return;
    const previous = widget.callback;
    widget.callback = function () {
        const result = previous?.apply(this, arguments);
        ensureProgressWidget(node);
        resizeNode(node);
        return result;
    };
    widget.__lxFolderBatchToggle = true;
}

function updateNodeProgress(data) {
    const nodeId = Number(data?.node);
    if (!Number.isFinite(nodeId)) return;
    const node = app.graph?.getNodeById(nodeId);
    if (!node || node.comfyClass !== EXEC_NODE) return;
    node._lxFolderBatchProgress = data;
    ensureProgressWidget(node);
    if (data?.state === "running") {
        ensureProgressTimer();
    }
    app.graph?.setDirtyCanvas(true, false);
}

function markProgressCancelled(node) {
    if (!node || node.comfyClass !== EXEC_NODE) return;
    const progress = node._lxFolderBatchProgress;
    if (!progress || progress.state !== "running") return;
    const elapsed = currentElapsedSeconds(progress);
    node._lxFolderBatchProgress = {
        ...progress,
        state: "cancelled",
        current: "已取消",
        elapsed_seconds: elapsed,
        elapsed_text: formatDuration(elapsed),
        remaining_seconds: 0,
        remaining_text: "00:00:00",
    };
    ensureProgressWidget(node);
    app.graph?.setDirtyCanvas(true, false);
}

api.addEventListener("lx_folder_batch_progress", ({ detail }) => {
    updateNodeProgress(detail);
});

api.addEventListener("execution_interrupted", ({ detail }) => {
    const nodeId = Number(detail?.node_id ?? detail?.node);
    if (Number.isFinite(nodeId)) {
        markProgressCancelled(app.graph?.getNodeById(nodeId));
        return;
    }
    for (const node of app.graph?._nodes || []) {
        markProgressCancelled(node);
    }
});

app.registerExtension({
    name: "Lingxi.FolderBatch",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!OUTPUT_SPECS[nodeData.name]) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            syncOutputs(this);
            if (nodeData.name !== EXEC_NODE) {
                setupGeneratorNode(this);
                return result;
            }
            this._lxFolderBatchProgress = this._lxFolderBatchProgress || {
                total: 0,
                done: 0,
                success: 0,
                failed: 0,
                skipped: 0,
                current: "等待执行",
                state: "idle",
            };
            ensureProgressWidget(this);
            removeBottomSpacer(this);
            installProgressToggle(this);
            resizeNode(this);
            return result;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            const result = onConfigure?.apply(this, arguments);
            syncOutputs(this);
            if (nodeData.name !== EXEC_NODE) {
                setupGeneratorNode(this);
                return result;
            }
            ensureProgressWidget(this);
            removeBottomSpacer(this);
            installProgressToggle(this);
            resizeNode(this);
            return result;
        };

        if (nodeData.name !== EXEC_NODE) return;

        const onWidgetChanged = nodeType.prototype.onWidgetChanged;
        nodeType.prototype.onWidgetChanged = function (name) {
            const result = onWidgetChanged?.apply(this, arguments);
            if (name === SHOW_PROGRESS_WIDGET) {
                ensureProgressWidget(this);
                resizeNode(this);
            }
            return result;
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            const result = onExecuted?.apply(this, arguments);
            const statusText = message?.text?.[0] || "";
            if (statusText && this._lxFolderBatchProgress) {
                this._lxFolderBatchProgress = {
                    ...this._lxFolderBatchProgress,
                    state: "done",
                };
                app.graph?.setDirtyCanvas(true, false);
            }
            return result;
        };
    },
});
