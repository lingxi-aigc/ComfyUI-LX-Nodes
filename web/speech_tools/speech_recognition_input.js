import { app } from "../../../../scripts/app.js";
import { api } from "../../../../scripts/api.js";

const NODE_NAME = "LX_SpeechRecognitionInput";
const TEXT_WIDGET_NAME = "文本";
const CONTROL_WIDGET_NAME = "__speech_recognition_controls";
const NODE_TITLE = "语音识别输入";
const STATE_KEY = Symbol("speech_recognition_input_state");
const ACTIVE_NODE_KEY = "__lxSpeechRecognitionActiveNode";

const TARGET_SAMPLE_RATE = 16000;
const MIN_SEGMENT_MS = 1200;
const MAX_SEGMENT_MS = 5000;
const SILENCE_MS = 850;
const VOICE_THRESHOLD = 0.012;
const ANIMATION_MS = 80;
const TYPEWRITER_MS = 0;

function findWidget(node, name) {
    return (node.widgets || []).find((widget) => widget?.name === name);
}

function getTextWidget(node) {
    return findWidget(node, TEXT_WIDGET_NAME);
}

function setActiveNode(node) {
    globalThis[ACTIVE_NODE_KEY] = node || null;
}

function getActiveNode() {
    return globalThis[ACTIVE_NODE_KEY] || null;
}

function setNodeDirty(node) {
    node.setDirtyCanvas?.(true, true);
    app.graph?.setDirtyCanvas(true, true);
}

function getState(node) {
    if (!node[STATE_KEY]) {
        node[STATE_KEY] = {
            status: "READY",
            message: "READY",
            error: "",
            listening: false,
            starting: false,
            stopping: false,
            volume: 0,
            committedText: "",
            typeQueue: "",
            typeTimer: null,
            chunkBuffers: [],
            chunkSamples: 0,
            chunkHasSpeech: false,
            lastVoiceAt: 0,
            stream: null,
            audioContext: null,
            source: null,
            processor: null,
            animationTimer: null,
            downloadPollTimer: null,
            segmentQueue: Promise.resolve(),
            pendingSegments: 0,
            buttonBounds: [0, 0, 0, 0],
        };
    }
    return node[STATE_KEY];
}

function getTextValue(node) {
    const widget = getTextWidget(node);
    return String(widget?.value ?? widget?.inputEl?.value ?? "");
}

function setTextValue(node, value) {
    const widget = getTextWidget(node);
    if (!widget) return;

    const text = String(value ?? "");
    widget.value = text;

    if (widget.inputEl) {
        widget.inputEl.value = text;
        widget.inputEl.dispatchEvent(new Event("input", { bubbles: true }));
    }

    if (typeof widget.callback === "function") {
        try {
            widget.callback(text);
        } catch (_) {
            /* ignored */
        }
    }
}

function normalizeText(text) {
    return String(text || "")
        .replace(/[\u3000\t\r\n]+/g, " ")
        .replace(/\s+/g, " ")
        .trim();
}

function hasLatinTail(text) {
    return /[A-Za-z0-9]$/.test(String(text || "").trim());
}

function hasLatinHead(text) {
    return /^[A-Za-z0-9]/.test(String(text || "").trim());
}

function appendText(left, right) {
    const base = normalizeText(left);
    const addition = normalizeText(right);
    if (!base) return addition;
    if (!addition) return base;
    if (hasLatinTail(base) && hasLatinHead(addition)) return `${base} ${addition}`;
    if (/[，。！？!?、；;：:,\s]$/.test(base) || /^[，。！？!?、；;：:,\s]/.test(addition)) {
        return `${base}${addition}`;
    }
    return `${base}，${addition}`;
}

function updateNodeTitle(node) {
    node.title = NODE_TITLE;
}

function setStatus(node, status, message = status) {
    const state = getState(node);
    state.status = status;
    state.message = message;
    if (status !== "ERROR") state.error = "";
    updateNodeTitle(node);
    setNodeDirty(node);
}

function setError(node, error) {
    const state = getState(node);
    state.status = "ERROR";
    state.message = "ERROR";
    state.error = String(error?.message || error || "Unknown error");
    updateNodeTitle(node);
    setNodeDirty(node);
}

async function fetchJson(path, options = {}) {
    const response = await api.fetchApi(path, options);
    let data = null;
    try {
        data = await response.json();
    } catch (_) {
        data = {};
    }
    if (!response.ok || data?.status === "error") {
        throw new Error(data?.message || response.statusText || "Request failed");
    }
    return data;
}

function clearDownloadPoller(state) {
    if (state.downloadPollTimer) {
        window.clearInterval(state.downloadPollTimer);
        state.downloadPollTimer = null;
    }
}

function wait(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function ensureModelReady(node) {
    let status = await fetchJson("/lx/speech/status");
    const missing = status?.missing_dependencies || [];
    if (missing.length) {
        throw new Error(`Missing dependency: ${missing.join(", ")}`);
    }

    if (status.model_exists) return;

    setStatus(node, "DOWNLOADING", status.message || "DOWNLOADING");
    await fetchJson("/lx/speech/download", { method: "POST" });

    for (;;) {
        await wait(1000);
        status = await fetchJson("/lx/speech/status");
        const progress = Number(status.progress || 0);
        const message = status.error
            ? status.error
            : `DOWNLOADING ${Math.max(0, Math.min(100, progress))}%`;
        setStatus(node, status.error ? "ERROR" : "DOWNLOADING", message);
        if (status.error) throw new Error(status.error);
        if (status.model_exists) break;
    }
}

function rms(buffer) {
    if (!buffer?.length) return 0;
    let sum = 0;
    for (let index = 0; index < buffer.length; index += 1) {
        const sample = buffer[index];
        sum += sample * sample;
    }
    return Math.sqrt(sum / buffer.length);
}

function downsampleBuffer(buffer, inputRate, outputRate) {
    if (outputRate === inputRate) return new Float32Array(buffer);
    if (outputRate > inputRate) return new Float32Array(buffer);

    const ratio = inputRate / outputRate;
    const newLength = Math.max(1, Math.round(buffer.length / ratio));
    const result = new Float32Array(newLength);

    let offsetResult = 0;
    let offsetBuffer = 0;
    while (offsetResult < result.length) {
        const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
        let accum = 0;
        let count = 0;
        for (let index = offsetBuffer; index < nextOffsetBuffer && index < buffer.length; index += 1) {
            accum += buffer[index];
            count += 1;
        }
        result[offsetResult] = count ? accum / count : 0;
        offsetResult += 1;
        offsetBuffer = nextOffsetBuffer;
    }

    return result;
}

function mergeFloatBuffers(buffers, totalSamples) {
    const merged = new Float32Array(totalSamples);
    let offset = 0;
    for (const buffer of buffers) {
        merged.set(buffer, offset);
        offset += buffer.length;
    }
    return merged;
}

function floatToInt16(buffer) {
    const output = new Int16Array(buffer.length);
    for (let index = 0; index < buffer.length; index += 1) {
        const sample = Math.max(-1, Math.min(1, buffer[index]));
        output[index] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
    }
    return output;
}

function int16ToBase64(samples) {
    const bytes = new Uint8Array(samples.buffer);
    const chunkSize = 0x8000;
    let binary = "";
    for (let index = 0; index < bytes.length; index += chunkSize) {
        const chunk = bytes.subarray(index, index + chunkSize);
        binary += String.fromCharCode.apply(null, chunk);
    }
    return btoa(binary);
}

function resetChunk(state) {
    state.chunkBuffers = [];
    state.chunkSamples = 0;
    state.chunkHasSpeech = false;
    state.lastVoiceAt = 0;
}

function clearTypeTimer(state) {
    if (state.typeTimer) {
        window.clearInterval(state.typeTimer);
        state.typeTimer = null;
    }
}

function startTypewriter(node) {
    const state = getState(node);
    if (state.typeTimer || !state.typeQueue) return;

    state.typeTimer = window.setInterval(() => {
        const current = getState(node);
        if (!current.typeQueue) {
            clearTypeTimer(current);
            return;
        }

        const next = Array.from(current.typeQueue)[0] || "";
        current.typeQueue = current.typeQueue.slice(next.length);
        current.committedText += next;
        setTextValue(node, current.committedText);
        setNodeDirty(node);
    }, TYPEWRITER_MS);
}

function enqueueTypedText(node, text) {
    const state = getState(node);
    const value = normalizeText(text);
    if (!value) return;

    const futureText = state.committedText + state.typeQueue;
    const nextText = appendText(futureText, value);
    const addition = nextText.slice(futureText.length);
    if (!addition) return;

    if (TYPEWRITER_MS <= 0) {
        clearTypeTimer(state);
        state.typeQueue = "";
        state.committedText = nextText;
        setTextValue(node, state.committedText);
        setNodeDirty(node);
        return;
    }

    state.typeQueue += addition;
    startTypewriter(node);
}

function finishTypewriter(node) {
    const state = getState(node);
    clearTypeTimer(state);
    if (!state.typeQueue) return;

    state.committedText += state.typeQueue;
    state.typeQueue = "";
    setTextValue(node, state.committedText);
}

function waitForTypewriter(node) {
    if (TYPEWRITER_MS <= 0) return Promise.resolve();
    const state = getState(node);
    if (!state.typeQueue && !state.typeTimer) return Promise.resolve();

    return new Promise((resolve) => {
        const timer = window.setInterval(() => {
            const current = getState(node);
            if (!current.typeQueue && !current.typeTimer) {
                window.clearInterval(timer);
                resolve();
            }
        }, Math.max(40, TYPEWRITER_MS));
    });
}

function appendChunk(state, buffer, inputVolume) {
    state.chunkBuffers.push(buffer);
    state.chunkSamples += buffer.length;
    state.volume = state.volume * 0.65 + Math.min(1, inputVolume * 12) * 0.35;
    if (inputVolume >= VOICE_THRESHOLD) {
        state.chunkHasSpeech = true;
        state.lastVoiceAt = performance.now();
    }
}

function queueSegmentUpload(node, audioBuffer) {
    const state = getState(node);
    state.pendingSegments += 1;
    setStatus(node, state.listening ? "RECOGNIZING" : "STOPPING", state.listening ? "RECOGNIZING" : "STOPPING");

    state.segmentQueue = state.segmentQueue
        .then(async () => {
            const pcm = floatToInt16(audioBuffer);
            const result = await fetchJson("/lx/speech/transcribe", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    sample_rate: TARGET_SAMPLE_RATE,
                    channels: 1,
                    audio: int16ToBase64(pcm),
                }),
            });

            const text = normalizeText(result?.text || "");
            if (text) {
                enqueueTypedText(node, text);
            }
        })
        .catch((error) => {
            setError(node, error);
        })
        .finally(() => {
            state.pendingSegments = Math.max(0, state.pendingSegments - 1);
            if (state.listening) {
                setStatus(node, "LISTENING", "LISTENING");
            } else if (!state.stopping && state.status !== "ERROR") {
                setStatus(node, "READY", "READY");
            }
        });

    return state.segmentQueue;
}

function flushSegment(node, { force = false } = {}) {
    const state = getState(node);
    const durationMs = (state.chunkSamples / TARGET_SAMPLE_RATE) * 1000;

    if (!state.chunkSamples) return Promise.resolve();
    if (!state.chunkHasSpeech || (!force && durationMs < MIN_SEGMENT_MS)) {
        resetChunk(state);
        return Promise.resolve();
    }

    const merged = mergeFloatBuffers(state.chunkBuffers, state.chunkSamples);
    resetChunk(state);
    return queueSegmentUpload(node, merged);
}

function maybeFlushSegment(node) {
    const state = getState(node);
    if (!state.listening || !state.chunkSamples) return;

    const now = performance.now();
    const durationMs = (state.chunkSamples / TARGET_SAMPLE_RATE) * 1000;
    const silenceMs = state.lastVoiceAt ? now - state.lastVoiceAt : 0;

    if (state.chunkHasSpeech && durationMs >= MIN_SEGMENT_MS && silenceMs >= SILENCE_MS) {
        flushSegment(node);
        return;
    }

    if (durationMs >= MAX_SEGMENT_MS) {
        flushSegment(node, { force: state.chunkHasSpeech });
    }
}

async function startAudio(node) {
    const state = getState(node);
    if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("Browser microphone API is unavailable");
    }

    const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
            channelCount: 1,
        },
    });

    const AudioContextCtor = globalThis.AudioContext || globalThis.webkitAudioContext;
    if (!AudioContextCtor) throw new Error("AudioContext is unavailable");

    const audioContext = new AudioContextCtor();
    await audioContext.resume?.();

    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(4096, 1, 1);

    processor.onaudioprocess = (event) => {
        const current = getState(node);
        const output = event.outputBuffer.getChannelData(0);
        output.fill(0);
        if (!current.listening) return;

        const input = event.inputBuffer.getChannelData(0);
        const inputVolume = rms(input);
        const downsampled = downsampleBuffer(input, audioContext.sampleRate, TARGET_SAMPLE_RATE);
        appendChunk(current, downsampled, inputVolume);
        maybeFlushSegment(node);
    };

    source.connect(processor);
    processor.connect(audioContext.destination);

    state.stream = stream;
    state.audioContext = audioContext;
    state.source = source;
    state.processor = processor;
    state.listening = true;
    state.stopping = false;
    clearTypeTimer(state);
    state.committedText = getTextValue(node);
    state.typeQueue = "";
    resetChunk(state);
    setStatus(node, "LISTENING", "LISTENING");

    clearAnimationTimer(state);
    state.animationTimer = window.setInterval(() => {
        const current = getState(node);
        current.volume *= 0.86;
        setNodeDirty(node);
    }, ANIMATION_MS);
}

function clearAnimationTimer(state) {
    if (state.animationTimer) {
        window.clearInterval(state.animationTimer);
        state.animationTimer = null;
    }
}

function teardownAudio(state) {
    try {
        state.processor?.disconnect();
    } catch (_) {
        /* ignored */
    }
    try {
        state.source?.disconnect();
    } catch (_) {
        /* ignored */
    }
    try {
        state.audioContext?.close?.();
    } catch (_) {
        /* ignored */
    }
    try {
        state.stream?.getTracks?.().forEach((track) => track.stop());
    } catch (_) {
        /* ignored */
    }

    state.processor = null;
    state.source = null;
    state.audioContext = null;
    state.stream = null;
    clearAnimationTimer(state);
}

async function startListening(node) {
    const state = getState(node);
    if (state.starting || state.listening) return;

    state.starting = true;
    setStatus(node, "LOADING", "LOADING");

    try {
        await ensureModelReady(node);
        setStatus(node, "LOADING", "LOADING");
        await startAudio(node);
    } catch (error) {
        teardownAudio(state);
        state.listening = false;
        setError(node, error);
    } finally {
        state.starting = false;
        setNodeDirty(node);
    }
}

async function stopListening(node) {
    const state = getState(node);
    if (state.stopping) return;

    state.stopping = true;
    state.listening = false;
    setStatus(node, "STOPPING", "STOPPING");
    teardownAudio(state);

    try {
        await flushSegment(node, { force: true });
        await state.segmentQueue;
        await waitForTypewriter(node);
        if (state.status !== "ERROR") setStatus(node, "READY", "READY");
    } catch (error) {
        setError(node, error);
    } finally {
        state.stopping = false;
        state.volume = 0;
        setNodeDirty(node);
    }
}

function toggleListening(node) {
    const state = getState(node);
    if (state.listening || state.starting) {
        stopListening(node);
    } else {
        startListening(node);
    }
}

function canToggleByHotkey(node) {
    if (!node || node.comfyClass !== NODE_NAME) return false;
    const state = getState(node);
    return !(state.starting || state.stopping || state.status === "DOWNLOADING" || state.status === "LOADING");
}

function isEditableTarget(target) {
    if (!target) return false;
    const tag = String(target.tagName || "").toUpperCase();
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || !!target.isContentEditable;
}

function installHotkeyHook() {
    if (globalThis.__speech_recognition_input_hotkey_hooked) return;
    globalThis.__speech_recognition_input_hotkey_hooked = true;

    window.addEventListener(
        "keydown",
        (event) => {
            if (event.code !== "Space" || event.repeat) return;
            if (isEditableTarget(event.target)) return;

            const node = getActiveNode();
            if (!canToggleByHotkey(node)) return;

            event.preventDefault();
            toggleListening(node);
            setNodeDirty(node);
        },
        true,
    );
}

function measureText(ctx, text) {
    if (typeof ctx?.measureText === "function") return ctx.measureText(String(text || "")).width;
    return String(text || "").length * 7;
}

function roundRect(ctx, x, y, width, height, radius) {
    const r = Math.max(0, Math.min(radius, Math.min(width, height) / 2));
    ctx.beginPath();
    if (typeof ctx.roundRect === "function") {
        ctx.roundRect(x, y, width, height, r);
        return;
    }
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + width - r, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + r);
    ctx.lineTo(x + width, y + height - r);
    ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
    ctx.lineTo(x + r, y + height);
    ctx.quadraticCurveTo(x, y + height, x, y + height - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
}

function drawPanel(ctx, x, y, width, height, radius, fill, stroke) {
    roundRect(ctx, x + 0.5, y + 0.5, width - 1, height - 1, radius);
    ctx.fillStyle = fill;
    ctx.fill();
    if (stroke) {
        ctx.strokeStyle = stroke;
        ctx.lineWidth = 1;
        ctx.stroke();
    }
}

function drawMicIcon(ctx, x, y, color, glow = false) {
    ctx.save();
    if (glow) {
        ctx.shadowColor = "rgba(74, 222, 128, 0.58)";
        ctx.shadowBlur = 6;
    }

    ctx.strokeStyle = color;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.lineWidth = 2.2;

    roundRect(ctx, x + 7, y + 1, 10, 17, 5);
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(x + 3, y + 11);
    ctx.bezierCurveTo(x + 3, y + 19, x + 21, y + 19, x + 21, y + 11);
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(x + 12, y + 22);
    ctx.lineTo(x + 12, y + 27);
    ctx.moveTo(x + 6.5, y + 27);
    ctx.lineTo(x + 17.5, y + 27);
    ctx.stroke();

    ctx.restore();
}

function drawVolumeBars(ctx, x, y, volume, active, bars = 10) {
    const width = 3;
    const gap = 3;
    const maxHeight = 22;
    ctx.save();
    for (let index = 0; index < bars; index += 1) {
        const denominator = Math.max(1, (bars - 1) / 2);
        const centerBias = 1 - Math.abs(index - (bars - 1) / 2) / denominator;
        const phase = Math.sin(performance.now() / 115 + index * 0.72) * 0.22 + 0.78;
        const amount = active ? Math.max(0.14, Math.min(1, volume * 1.15 * phase + centerBias * 0.18)) : 0.16;
        const height = Math.max(4, maxHeight * amount);
        const left = x + index * (width + gap);
        const top = y + (maxHeight - height) / 2;
        drawPanel(ctx, left, top, width, height, 2, active ? "#78f39a" : "#747474", null);
    }
    ctx.restore();
}

function truncateStatus(ctx, text, maxWidth) {
    const value = String(text || "");
    if (measureText(ctx, value) <= maxWidth) return value;
    let clipped = value;
    while (clipped.length > 1 && measureText(ctx, `${clipped}...`) > maxWidth) {
        clipped = clipped.slice(0, -1);
    }
    return `${clipped}...`;
}

function volumeBarsWidth(bars) {
    if (bars <= 0) return 0;
    return bars * 3 + Math.max(0, bars - 1) * 3;
}

function getControlWidth(node, fallbackWidth) {
    const nodeWidth = Number(node?.size?.[0]);
    if (Number.isFinite(nodeWidth) && nodeWidth > 0) return nodeWidth;

    const widgetWidth = Number(fallbackWidth);
    if (Number.isFinite(widgetWidth) && widgetWidth > 0) return widgetWidth;

    return 2;
}

class SpeechControlWidget {
    constructor(node) {
        this.name = CONTROL_WIDGET_NAME;
        this.type = "custom";
        this.node = node;
        this.serialize = false;
    }

    computeSize(width) {
        return [getControlWidth(this.node, width), 62];
    }

    draw(ctx, node, width, y) {
        const state = getState(node);
        const busy = state.starting || state.stopping || state.status === "DOWNLOADING" || state.status === "LOADING";
        const active = !!state.listening;
        const recognizing = state.pendingSegments > 0 || state.status === "RECOGNIZING";
        const controlWidth = getControlWidth(node, width);

        const sidePadding = 14;
        const buttonHeight = 44;
        const buttonWidth = Math.max(2, controlWidth - sidePadding * 2);
        const x = Math.round((controlWidth - buttonWidth) / 2);
        const top = y + 10;
        const centerX = x + buttonWidth / 2;
        const iconSize = 24;
        const iconX = x + Math.max(14, Math.min(28, Math.round(buttonWidth * 0.1)));
        const iconY = top + Math.round((buttonHeight - 28) / 2);
        const waveBars = buttonWidth >= 210 ? 10 : buttonWidth >= 170 ? 8 : buttonWidth >= 135 ? 6 : 0;
        const waveWidth = volumeBarsWidth(waveBars);
        const waveX = x + buttonWidth - waveWidth - Math.max(14, Math.min(26, Math.round(buttonWidth * 0.08)));
        const waveY = top + Math.round((buttonHeight - 22) / 2);

        state.buttonBounds = [x, top, buttonWidth, buttonHeight];

        ctx.save();
        const pulse = active ? 0.34 + Math.sin(performance.now() / 260) * 0.12 : 0;
        ctx.shadowColor = active ? `rgba(74, 222, 128, ${pulse})` : "rgba(0, 0, 0, 0.12)";
        ctx.shadowBlur = active ? 7 : 3;
        drawPanel(
            ctx,
            x,
            top,
            buttonWidth,
            buttonHeight,
            14,
            active ? "#1f6f3a" : busy ? "#3d3d3d" : "#343434",
            active ? "#7df69a" : busy ? "#707070" : "#666666",
        );
        ctx.shadowBlur = 0;
        ctx.shadowColor = "transparent";

        ctx.save();
        roundRect(ctx, x + 0.5, top + 0.5, buttonWidth - 1, buttonHeight - 1, 14);
        ctx.clip();

        ctx.font = "bold 14px Arial";
        drawMicIcon(ctx, iconX, iconY, active ? "#c9ffd6" : "#f3f3f3", active);

        const label = busy ? state.message || state.status : active ? "STOP" : "START";
        const leftGuard = iconX + iconSize + 12;
        const rightGuard = waveBars > 0 ? waveX - 12 : x + buttonWidth - 14;
        const labelRoom = Math.max(20, Math.min(centerX - leftGuard, rightGuard - centerX) * 2);
        const displayLabel = truncateStatus(ctx, label, labelRoom);

        ctx.fillStyle = active ? "#effdf1" : "#f3f3f3";
        ctx.shadowBlur = 0;
        ctx.shadowColor = "transparent";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(displayLabel, centerX, top + buttonHeight / 2, labelRoom);

        if (waveBars > 0) {
            drawVolumeBars(ctx, waveX, waveY, state.volume, active || recognizing, waveBars);
        }
        ctx.restore();
        ctx.restore();
    }

    mouse(event, pos, node) {
        if (event.type !== "mousedown" && event.type !== "pointerdown") return false;
        setActiveNode(node);
        const state = getState(node);
        const [bx, by, bw, bh] = state.buttonBounds;

        const inButton = pos[0] >= bx && pos[0] <= bx + bw && pos[1] >= by && pos[1] <= by + bh;

        if (inButton) {
            if (state.starting || state.stopping || state.status === "DOWNLOADING" || state.status === "LOADING") {
                return true;
            }
            toggleListening(node);
            setNodeDirty(node);
            return true;
        }

        return false;
    }
}

function ensureControls(node) {
    if (!findWidget(node, CONTROL_WIDGET_NAME)) {
        node.addCustomWidget(new SpeechControlWidget(node));
    }

    const textWidget = getTextWidget(node);
    if (textWidget?.inputEl && !textWidget.__speechRecognitionInputBound) {
        textWidget.__speechRecognitionInputBound = true;
        textWidget.inputEl.spellcheck = false;
        textWidget.inputEl.addEventListener("focus", () => setActiveNode(node));
        textWidget.inputEl.addEventListener("mousedown", () => setActiveNode(node));
        textWidget.inputEl.addEventListener("input", () => {
            const state = getState(node);
            if (!state.listening) state.committedText = getTextValue(node);
        });
    }

    node.serialize_widgets = true;
    updateNodeTitle(node);
    setNodeDirty(node);
}

function cleanupNode(node) {
    const state = getState(node);
    clearDownloadPoller(state);
    clearTypeTimer(state);
    teardownAudio(state);
    state.listening = false;
    state.starting = false;
    state.stopping = false;
}

app.registerExtension({
    name: "LX.SpeechTools.SpeechRecognitionInput",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            ensureControls(this);
            return result;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = onConfigure?.apply(this, arguments);
            ensureControls(this);
            return result;
        };

        const onRemoved = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function () {
            if (getActiveNode() === this) setActiveNode(null);
            cleanupNode(this);
            return onRemoved?.apply(this, arguments);
        };

        const onMouseDown = nodeType.prototype.onMouseDown;
        nodeType.prototype.onMouseDown = function () {
            setActiveNode(this);
            return onMouseDown?.apply(this, arguments);
        };

        const onSelected = nodeType.prototype.onSelected;
        nodeType.prototype.onSelected = function () {
            setActiveNode(this);
            return onSelected?.apply(this, arguments);
        };
    },

    setup() {
        installHotkeyHook();
    },
});
