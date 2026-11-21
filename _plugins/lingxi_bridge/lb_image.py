import json
import time
import base64
from concurrent.futures import TimeoutError as FutureTimeoutError
from io import BytesIO
from urllib.parse import urlsplit, urlunsplit
from PIL import Image
from requests.exceptions import ConnectionError, SSLError, Timeout

import comfy.utils  # type: ignore[reportMissingImports]
import comfy.model_management  # type: ignore[reportMissingImports]
from comfy_execution.graph_utils import ExecutionBlocker  # type: ignore[reportMissingImports]
from ..categories import LX_RELAY_CATEGORY
from .lb_utils import tensor2pil, pil2tensor
from .lb_config import get_current_base_url, API_PATHS
from .lb_aipaiai import (
    AIPAI_IMAGE_QUALITIES,
    AIPAI_ADOBE_FORMAT,
    AIPAI_ADOBE_SIZES,
    AIPAI_IMAGE_SIZES,
    is_aipaiai_adobe,
    aipaiai_image_size,
    is_aipaiai_base_url,
    normalize_aipaiai_base_url,
)
from . import lb_http as http_client


# Platform-specific ratio lists.
IMAGE_RATIOS_BASE = ["auto", "1:1", "2:3", "3:2", "4:3", "3:4", "9:16", "16:9", "9:21", "21:9"]
IMAGE_RATIOS_EXTREME = ["1:4", "4:1", "1:8", "8:1"]
GPT_IMAGE2_EXTRA_RATIOS = ["1:3", "3:1", "5:4", "4:5", "1:2", "2:1"]
BANANA2_RATIOS = IMAGE_RATIOS_BASE + IMAGE_RATIOS_EXTREME
GPT_IMAGE2_RATIOS = IMAGE_RATIOS_BASE + GPT_IMAGE2_EXTRA_RATIOS
IMAGE_RATIOS = IMAGE_RATIOS_BASE + IMAGE_RATIOS_EXTREME + GPT_IMAGE2_EXTRA_RATIOS
IMAGE_RATIOS_BY_PLATFORM = {
    "banana-pro": IMAGE_RATIOS_BASE,
    "banana-2": BANANA2_RATIOS,
    "gpt-image2": GPT_IMAGE2_RATIOS,
    "gpt-image2.5": GPT_IMAGE2_RATIOS,
}

# gpt-image2 尺寸规则：最大边 <= 3840，宽高都是 16 的倍数，总像素 <= 8294400。
GPT_IMAGE2_RATIO_VALUES = {
    "1:1":  1 / 1,
    "3:2":  3 / 2,
    "2:3":  2 / 3,
    "4:3":  4 / 3,
    "3:4":  3 / 4,
    "16:9": 16 / 9,
    "9:16": 9 / 16,
    "21:9": 21 / 9,
    "9:21": 9 / 21,
    "1:3":  1 / 3,
    "3:1":  3 / 1,
    "5:4": 5 / 4, "4:5": 4 / 5, "1:2": 1 / 2, "2:1": 2 / 1,
}
GPT_IMAGE2_1K_RATIO_SIZES = {
    "1:1":  "1248x1248",
    "3:2":  "1536x1024",
    "2:3":  "1024x1536",
    "4:3":  "1440x1072",
    "3:4":  "1072x1440",
    "16:9": "1664x944",
    "9:16": "944x1664",
    "21:9": "1904x816",
    "9:21": "816x1904",
    "1:3":  "720x2160",
    "3:1":  "2160x720",
    "5:4": "1408x1120",
    "4:5": "1120x1408",
    "1:2": "880x1760",
    "2:1": "1760x880",
}
GPT_IMAGE2_SIZE_TARGET_PIXELS = {
    "2K": 4194304,
    "4K": 8294400,
}
IMAGE_SIZES = ["1K", "2K", "4K"]
GPT_IMAGE2_QUALITIES = ["low", "medium", "high", "auto"]
GPT_IMAGE2_FORMATS = ["jpeg", "png", "webp"]
GPT_IMAGE2_MODERATIONS = ["auto", "low"]
GPT_IMAGE2_MAX_EDGE = 3840
GPT_IMAGE2_MAX_PIXELS = 8294400
GPT_IMAGE2_TIMEOUTS = {
    "1K": 180,
    "2K": 300,
    "4K": 300,
}
BANANA_IMAGE_TIMEOUTS = {
    "1K": 180,
    "2K": 300,
    "4K": 300,
}
IMAGE_TOTAL_BUDGETS = {
    "1K": 180,
    "2K": 300,
    "4K": 300,
}
IMAGE_DOWNLOAD_TIMEOUTS = {
    "1K": 60,
    "2K": 75,
    "4K": 90,
}


def _redact_url_for_log(url):
    text = "" if url is None else str(url)
    try:
        parts = urlsplit(text)
        if not parts.query and not parts.fragment:
            return text
        query = "<redacted>" if parts.query else ""
        fragment = "<redacted>" if parts.fragment else ""
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, fragment))
    except Exception:
        if "?" in text:
            return text.split("?", 1)[0] + "?<redacted>"
        return text

PRO_MAX_IMAGES = 14
FLASH_MAX_IMAGES = 14
GPT_IMAGE2_MAX_IMAGES = 16
ALL_MAX_IMAGES = max(PRO_MAX_IMAGES, FLASH_MAX_IMAGES, GPT_IMAGE2_MAX_IMAGES)


class LingxiBridgeImage:
    SEARCH_ALIASES = ("lx", "LX", "灵犀", "灵犀生图", "中转站生图", "API生图", "image generation")

    @classmethod
    def INPUT_TYPES(cls):
        optional = {
            "info": ("STRING", {"default": "", "forceInput": True}),
        }
        for i in range(1, ALL_MAX_IMAGES + 1):
            optional[f"image{i}"] = ("IMAGE",)

        return {
            "required": {
                "prompt": ("STRING", {"multiline": True}),
                "ratio": (IMAGE_RATIOS, {"default": "auto"}),
                "size": (IMAGE_SIZES, {"default": "2K"}),
                "quality": (GPT_IMAGE2_QUALITIES, {"default": "medium"}),
                "format": (GPT_IMAGE2_FORMATS, {"default": "jpeg"}),
                "moderation": (GPT_IMAGE2_MODERATIONS, {"default": "low"}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True}),
            },
            "optional": optional,
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("image", "response", "image_url", "explanation")
    FUNCTION = "generate_image"
    CATEGORY = f"{LX_RELAY_CATEGORY}/单图生成"

    def __init__(self):
        self.timeout = 300

    def _total_budget(self, size):
        return IMAGE_TOTAL_BUDGETS.get(size, self.timeout)

    def _download_timeout(self, size, remaining=None):
        base_timeout = IMAGE_DOWNLOAD_TIMEOUTS.get(size, 60)
        if remaining is None:
            return base_timeout
        return max(5, min(base_timeout, int(remaining)))

    def _remaining_budget(self, deadline):
        if deadline is None:
            return None
        return deadline - time.time()

    def _check_interrupt(self):
        cancel_event = getattr(self, "_cancel_event", None)
        if cancel_event is not None and cancel_event.is_set():
            raise comfy.model_management.InterruptProcessingException()
        comfy.model_management.throw_exception_if_processing_interrupted()

    def _sleep_interruptible(self, seconds, stage, deadline=None):
        end = time.time() + max(0, seconds)
        while True:
            self._check_interrupt()
            self._ensure_budget(deadline, stage)
            remaining_sleep = end - time.time()
            if remaining_sleep <= 0:
                return
            time.sleep(min(0.25, remaining_sleep))

    def _close_http_session_on_interrupt(self):
        try:
            http_client.close_all_sessions()
        except Exception:
            pass

    def _wait_future_interruptible(self, future, stage, deadline=None):
        try:
            while True:
                self._check_interrupt()
                remaining = self._ensure_budget(deadline, stage)
                wait_for = 0.25
                if remaining is not None:
                    wait_for = max(0.05, min(wait_for, remaining))
                try:
                    return future.result(timeout=wait_for)
                except FutureTimeoutError:
                    continue
        except comfy.model_management.InterruptProcessingException:
            future.cancel()
            self._close_http_session_on_interrupt()
            raise
        except Exception:
            future.cancel()
            raise

    def _ensure_budget(self, deadline, stage):
        remaining = self._remaining_budget(deadline)
        if remaining is not None and remaining <= 0:
            self._err(f"{stage} 超时：已超过总预算 {self._total_budget(getattr(self, '_current_size', '2K'))} 秒。")
        return remaining

    # ─── 通用报错诊断 ───────────────────────────────────────────────────────────────
    def _diagnose(self, status_code, body_text, api_format, model, base_url):
        """把原始错误翻译成大白话+建议。返回 (简化原因, 建议, 原始信息)。"""
        try:
            err_body = json.loads(body_text)
        except Exception:
            err_body = {}

        if not isinstance(err_body, dict):
            err_msg = str(err_body)[:300]
            err_type = code = ""
        elif not isinstance(err_body.get("error"), dict):
            err_msg = err_body.get("error") or err_body.get("message") or str(err_body)[:300]
            code = err_body.get("code") or ""
            err_type = err_body.get("type") or ""
        else:
            error_field = err_body.get("error", {})
            err_msg = error_field.get("message", "") or err_body.get("message", "") or body_text[:300]
            code = error_field.get("code", "") or err_body.get("code", "")
            err_type = error_field.get("type", "") or err_body.get("type", "")
        status = status_code

        # ── Python / aiohttp 异常（优先判断，不受状态码限制）─────────────────────────
        if any(k in err_msg for k in (
            "ClientSession", "unexpected keyword argument",
            "name '", "NameError", "TypeError:", "Traceback",
            "_request()", "aiohttp", "asyncio",
        )):
            return (
                "中转站服务端代码报错（不是你的问题）。",
                "换一个 API 地址试试，或者稍后重试。",
                err_msg,
            )

        # ── 内容违规 / 安全过滤 ───────────────────────────────────────────────────
        if any(k in err_msg.lower() for k in (
            "violation", "prohibited", "forbidden",
            "safety", "nsfw", "nsfw_content",
            "politically", "sensitive", "restricted",
            "content_policy_violation", "moderation",
        )):
            if "apikey" in err_msg.lower():
                return (
                    "API Key 无效。",
                    "请确认 API Key 与中转站地址是否配套："
                    "grsaiapi.com 的 key 配 grsaiapi.com，yunwu 的 key 配 yunwu.ai，切勿混用。",
                    err_msg,
                )
            return (
                "内容违规，当前提示词触发了模型的内容安全策略。",
                "请修改提示词，移除可能的敏感词或换用更安全的描述方式。",
                err_msg,
            )

        # ── Grsai v1/api/generate 专用格式 ────────────────────────────────────────
        if api_format == "v1/api/generate" and isinstance(err_body, dict):
            grsai_status = err_body.get("status", "")
            task_id = err_body.get("id", "")
            progress = err_body.get("progress")

            if task_id and progress is not None:
                if progress == 100:
                    return (
                        "Grsai 返回了任务 ID（异步任务），但代码未完成轮询逻辑。",
                        "暂不支持 Grsai 异步任务自动轮询，建议换用 v1/images / v1/chat/completions 等同步接口。",
                        task_id,
                    )
                else:
                    return (
                        f"Grsai 返回了任务 ID（进度 {progress}%），异步任务尚未完成。",
                        "暂不支持 Grsai 异步任务自动轮询，建议换用 v1/images / v1/chat/completions 等同步接口。",
                        task_id,
                    )

            if grsai_status == "failed":
                err_reason = err_body.get("error", "")
                if "apikey" in str(err_reason).lower() or "api key" in str(err_reason).lower():
                    return (
                        "API Key 无效（Grsai 返回 apikey error）。",
                        "请确认 API Key 与中转站地址是否配套："
                        "grsaiapi.com 的 key 配 grsaiapi.com，yunwu 的 key 配 yunwu.ai，切勿混用。",
                        err_reason,
                    )
                return (
                    f"Grsai 接口返回失败：{err_reason}",
                    "可能是模型不支持、接口返回额度/账户池限制，或 Key 与中转站不匹配。",
                    err_reason,
                )

        # ── 图片解析失败 ─────────────────────────────────────────────────────────
        if any(k in err_msg for k in (
            "base64 解出的内容不是图片", "不是图片",
            "invalid image", "corrupt image",
            "Image' is not defined",
        )):
            return (
                "接口返回了响应，但无法从中解析出图片数据（可能是响应格式差异）。",
                "尝试换用 v1/images / v1/chat/completions 等接口，或换一个 API 地址。",
                err_msg,
            )

        # ── 上游饱和 / 额度类拒绝 ────────────────────────────────────────────────
        if status == 402 or any(k in err_msg.lower() for k in (
            "insufficient_quota", "insufficient credits", "balance",
            "quota exhausted", "out of quota", "no quota",
            "credit limit", "payment required",
            "out of credit", "insufficient balance", "billing hard limit",
        )):
            return (
                "接口返回余额/额度类拒绝。",
                "如果后台余额正常，通常是高并发预扣、账户池、上游路由额度或风控限制；请先降低并发后重试。",
                err_msg,
            )

        # ── 模型下架 / 停用 / 不存在 ─────────────────────────────────────────────
        if any(k in err_msg.lower() for k in (
            "model is deprecated", "model disabled",
            "model not found", "model unavailable",
            "model has been", "model does not exist",
            "model id", "model_name",
        )):
            return (
                f"当前模型（{model}）已停用或该中转站不支持此模型。",
                "换一个仍在支持的模型试试，或咨询中转站客服。",
                err_msg,
            )

        # ── 提示词 / 图片超限 ────────────────────────────────────────────────────
        if any(k in err_msg.lower() for k in (
            "prompt too long", "context length", "token limit",
            "exceeds maximum", "image too large", "size too big",
            "too many tokens", "input too long", "max tokens",
            "content too long", "request too large",
            "unsupported image dimensions", "invalid image size",
            "aspect ratio", "resolution is not supported",
        )):
            return (
                "输入超出模型限制（提示词太长或图片太大）。",
                "缩短提示词、减少参考图片数量，或降低图片分辨率。",
                err_msg,
            )

        # ── 本地网络 / SSL 问题 ──────────────────────────────────────────────────
        if any(k in err_msg for k in (
            "Connection refused", "Connection reset",
            "Name or service not known", "Could not resolve",
            "SSLCertVerificationError", "SSL: CERTIFICATE_",
            "ConnectionTimeout", "Network is unreachable",
            "CERTIFICATE_VERIFY_FAILED", "Max retries exceeded",
            "Network error", "NewConnectionError", "ProxyError",
            "ReadTimeout", "ConnectTimeout",
        )):
            return (
                "本地网络无法访问该 API 地址。",
                "检查网络连接、代理设置，或尝试换一个 API 地址。",
                err_msg,
            )

        # ── 并发冲突 ─────────────────────────────────────────────────────────────
        if any(k in err_msg.lower() for k in (
            "concurrent", "another request is in progress",
            "only one request", "parallel",
            "request in flight", "already running",
        )):
            return (
                "当前 API Key 不允许并发请求，有其他任务正在使用。",
                "等待当前任务完成后重试，或换用支持并发的 API Key。",
                err_msg,
            )

        # ── API Key 为空 ─────────────────────────────────────────────────────────
        if (any(k in err_msg.lower() for k in (
            "missing api key", "api key is required",
            "no api key", "api key missing",
            "authorization header",
        )) or (err_msg == "" and status in (401, 403))):
            return (
                "API Key 为空或未填写。",
                "在设置节点里填写有效的 API Key。",
                err_msg,
            )

        # ── 404 ──────────────────────────────────────────────────────────────────
        if status == 404:
            if api_format == "v1/api/generate" or "Invalid URL" in err_msg:
                return (
                    "当前中转站不支持 /v1/api/generate 接口。",
                    "换一个中转站试试（grsaiapi.com / yunwu.ai 支持此接口），"
                    "或者把 api_format 切换到 v1/chat/completions / v1beta/models。",
                    err_msg,
                )
            if "POST" in err_msg or "Post" in err_msg or "method" in err_msg.lower():
                return (
                    "接口地址不对，这个平台不支持这个接口格式。",
                    "试试切换到其他接口（如 v1/images 或 v1/chat/completions），"
                    "或者换一个支持的 API 地址。",
                    err_msg,
                )
            return (
                "请求的资源不存在，可能是接口地址写错了。",
                "检查 API 地址和接口格式是否正确。",
                err_msg,
            )

        # ── 401 / 403 ───────────────────────────────────────────────────────────
        if status in (401, 403) or any(k in err_msg.lower() for k in (
            "auth", "unauthorized", "invalid api key", "incorrect api key",
            "permission denied", "forbidden", "invalid_api_key",
        )):
            return (
                "API 密钥无效或权限不足。",
                "去设置里检查 API 密钥是否正确，确认这个密钥有调用图片生成的权限。",
                err_msg,
            )

        # ── 429 限流 ────────────────────────────────────────────────────────────
        if status == 429 or any(k in err_msg.lower() for k in (
            "rate limit", "rate_limit", "too many requests", "requests per minute",
        )):
            return (
                "请求太频繁，平台限流了。",
                "稍等几秒再试，或者降低并发数。",
                err_msg,
            )

        # ── 400 参数错误 ─────────────────────────────────────────────────────────
        if status == 400:
            if api_format == "v1/api/generate" and isinstance(err_body, dict) and err_body.get("status") == "failed":
                err_reason = err_body.get("error", "") or str(err_body)
                if "apikey" in str(err_reason).lower():
                    return (
                        "API Key 无效（Grsai 返回 apikey error）。",
                        "请确认 API Key 与中转站地址是否配套："
                        "grsaiapi.com 的 key 配 grsaiapi.com，yunwu 的 key 配 yunwu.ai，切勿混用。",
                        err_reason,
                    )
                return (
                    f"Grsai 返回失败：{err_reason}",
                    "可能是模型不支持、接口返回额度/账户池限制，或 Key 与中转站不匹配。",
                    err_reason,
                )
            if "model" in err_msg.lower():
                return (
                    f"当前模型（{model}）这个接口不支持。",
                    f"换一个当前接口支持的模型试试，或者换到 v1/images / v1/chat/completions 等其他接口。",
                    err_msg,
                )
            if "malformed" in err_msg.lower() or "invalid" in err_msg.lower():
                return (
                    "请求格式不对，接口无法解析参数。",
                    "可能是模型不支持这个尺寸/比例，或者 prompt 格式有问题。尝试换小一点的图片尺寸。",
                    err_msg,
                )
            if "contents is required" in err_msg:
                return (
                    "缺少必要参数 contents，当前接口需要同时传 messages 和 contents。",
                    "这是接口兼容性问题，可以尝试换一个 API 地址，或换到 v1/images 接口。",
                    err_msg,
                )
            return (
                "参数错误，接口无法处理这个请求。",
                f"提示信息：{err_msg}",
                err_msg,
            )

        # ── 500/502/503 服务端错误 ───────────────────────────────────────────────
        if status >= 500:
            if "not supported" in err_msg.lower() or "not available" in err_msg.lower():
                return (
                    f"这个接口不支持模型 {model}，或者模型后端暂时不可用。",
                    f"换一个支持的模型试试，或者换一个 API 地址（如云雾/runninghub/grsai）。",
                    err_msg,
                )
            if "distributor" in err_msg:
                return (
                    "模型后端暂时不可用（ distributor 不可用）。",
                    "这是平台服务端问题，稍后再试，或者换一个 API 地址。",
                    err_msg,
                )
            return (
                "API 服务端出错了（不是你的问题）。",
                "稍等几秒再试，如果持续报错可以换一个新的 API 地址。",
                err_msg,
            )

        # ── 超时 ─────────────────────────────────────────────────────────────────
        if "timeout" in err_msg.lower() or "timed out" in err_msg.lower():
            return (
                "请求超时，接口响应太慢或无法访问。",
                "检查 API 地址是否正确、网络是否通畅，或者换一个大一点的超时时间/换一个更快的 API 地址。",
                err_msg,
            )

        # ── 通用兜底 ─────────────────────────────────────────────────────────────
        if status <= 0:
            return (
                "节点执行时遇到了本地或接口返回格式异常。",
                "检查 API 地址、接口格式、模型名称和 API Key；如果刚才取消过任务，可以稍后重试一次。",
                err_msg,
            )
        return (
            f"接口返回了错误（HTTP {status}）。",
            "请检查 API 地址、接口格式、模型名称是否配置正确。",
            err_msg,
        )

    def _err(self, msg, status_code=0, body_text="", api_format="", model="", base_url=""):
        self._raw_err_body = body_text
        if status_code and body_text:
            reason, suggestion, original = self._diagnose(
                status_code, body_text, api_format, model, base_url
            )
            self._error_status_code = status_code
            self._error_reason = reason
            self._error_suggestion = suggestion
            self._error_original = original
            self._formatted_err = (
                f"[LingxiBridge]\n"
                f"  接口     {api_format}\n"
                f"  模型     {model}\n"
                f"  地址     {base_url}\n"
                f"\n"
                f"  原因\n"
                f"    {reason}\n"
                f"\n"
                f"  建议\n"
                f"    {suggestion}\n"
                f"\n"
                f"  原始\n"
                f"    {original}"
            )
            print(self._formatted_err)
            raise RuntimeError(self._formatted_err)
        else:
            reason, suggestion, original = self._diagnose(
                status_code, body_text or msg, api_format, model, base_url
            )
            self._error_status_code = status_code
            self._error_reason = reason
            self._error_suggestion = suggestion
            self._error_original = original or msg
            self._formatted_err = f"[LingxiBridge] {msg}"
            print(self._formatted_err)
            raise RuntimeError(self._formatted_err)

    def _clip_text(self, value, limit=800):
        text = "" if value is None else str(value)
        if len(text) <= limit:
            return text
        return text[:limit] + f"... <truncated {len(text) - limit} chars>"

    def _json_dump(self, payload):
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    def _compact_raw_message(self, raw):
        if not raw:
            return ""
        if isinstance(raw, dict):
            if isinstance(raw.get("error"), dict):
                err = raw["error"]
                return self._clip_text(err.get("message") or err.get("code") or err.get("type") or err)
            return self._clip_text(raw.get("message") or raw.get("error") or raw)
        return self._clip_text(raw)

    def _safe_json_response(self, resp, api_format="", model="", base_url=""):
        try:
            return resp.json()
        except Exception as e:
            body = getattr(resp, "text", "") or ""
            self._err(
                f"接口返回的不是 JSON，无法解析。原始内容：{body[:300]}",
                status_code=getattr(resp, "status_code", 0),
                body_text=body or str(e),
                api_format=api_format,
                model=model,
                base_url=base_url,
            )

    def _success_response(
        self,
        img_type,
        image_url,
        model,
        api_format,
        platform,
        size,
        ratio,
        requested_size_pixels="",
        original_output_size="",
        output_size_mismatch=False,
    ):
        payload = {
            "code": "success",
            "type": img_type,
            "model": model,
            "api_format": api_format,
            "platform": platform,
            "size": size,
            "ratio": ratio,
        }
        if image_url:
            payload["url"] = image_url
        if requested_size_pixels:
            payload["requested_size_pixels"] = requested_size_pixels
        if original_output_size:
            payload["original_output_size"] = original_output_size
        if output_size_mismatch:
            payload["output_size_mismatch"] = True
        return self._json_dump(payload)

    def _error_response(self, exc):
        raw = getattr(self, "_raw_err_body", "")
        status = int(getattr(self, "_error_status_code", 0) or 0)
        message = self._compact_raw_message(raw) or self._clip_text(str(exc))
        payload = {"code": "error", "message": message}
        if status:
            payload["status"] = status
        return self._json_dump(payload)

    def _friendly_error_text(self, exc):
        reason = getattr(self, "_error_reason", "") or "任务执行失败。"
        suggestion = getattr(self, "_error_suggestion", "") or "请检查 API 地址、接口格式、模型名称和 API Key 后再试。"
        return f"原因：{reason}\n建议：{suggestion}"

    def _banana_timeout(self, size):
        return BANANA_IMAGE_TIMEOUTS.get(size, self.timeout)

    def _image_result_timeout(self, platform, size):
        if platform in {"gpt-image2", "gpt-image2.5"}:
            return self._gpt_image2_timeout(size)
        return self._banana_timeout(size)

    def _normalize_choice(self, name, value, allowed, default):
        if value in allowed:
            return value
        print(f"[LingxiBridge] normalize {name}: {value!r} -> {default!r}")
        return default

    def _http_post(self, url, headers=None, json=None, data=None, files=None, timeout=300, deadline=None):
        """同步 POST，直接请求，返回 requests.Response。"""
        remaining = self._ensure_budget(deadline, "请求阶段")
        if remaining is not None:
            timeout = max(5, min(timeout, int(remaining)))
        t0 = time.time()

        def _do_request():
            session = http_client._get_session()
            if files:
                return session.post(url, headers=headers, data=data, files=files, timeout=timeout)
            return session.post(url, headers=headers, json=json, timeout=timeout)

        future = http_client._get_executor().submit(_do_request)
        resp = self._wait_future_interruptible(future, "请求阶段", deadline=deadline)
        elapsed = (time.time() - t0) * 1000

        print(f"[LingxiBridge] POST {url} -> {resp.status_code} ({elapsed/1000:.1f}s)")
        return resp

    # ─── 辅助方法 ────────────────────────────────────────────────────────────────

    def _get_api_key(self, api_key):
        if api_key and api_key.strip() and api_key.strip().lower() not in ("none", "null", ""):
            return api_key.strip()
        return ""

    def _image_to_base64(self, image_tensor):
        self._check_interrupt()
        pil_image = tensor2pil(image_tensor)[0]
        buffered = BytesIO()
        pil_image.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode('utf-8')

    def _image_to_bytes(self, image_tensor):
        self._check_interrupt()
        pil_image = tensor2pil(image_tensor)[0]
        buffered = BytesIO()
        pil_image.save(buffered, format="PNG")
        return buffered.getvalue()

    # ─── Grsai v1/api/generate ───────────────────────────────────────────────────
    def _grsai_generate(self, base_url, api_key, model, prompt, ratio, size, images, pbar, deadline=None):
        url = f"{base_url}/v1/api/generate"
        timeout = self._banana_timeout(size)

        ratio_map = {
            "auto": "auto",
            "1:1": "1:1", "2:3": "2:3", "3:2": "3:2",
            "4:3": "4:3", "3:4": "3:4", "9:16": "9:16", "16:9": "16:9",
            "9:21": "9:21", "21:9": "21:9",
            "1:4": "1:4", "4:1": "4:1", "1:8": "1:8", "8:1": "8:1",
        }
        api_ratio = ratio_map.get(ratio, "1:1")

        size_map = {"1K": "1K", "2K": "2K", "4K": "4K"}
        api_size = size_map.get(size, "2K")

        img_payloads = []
        for i, img in enumerate(images):
            self._check_interrupt()
            pbar.update_absolute(15 + i * 2)
            b64 = self._image_to_base64(img)
            img_payloads.append(b64)

        payload = {
            "model": model,
            "prompt": prompt,
            "images": img_payloads,
            "aspectRatio": api_ratio,
            "imageSize": api_size,
            "replyType": "json",
        }

        pbar.update_absolute(40)
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        resp = self._http_post(url, headers=headers, json=payload, timeout=timeout, deadline=deadline)
        pbar.update_absolute(75)

        if resp.status_code != 200:
            body = resp.text
            try:
                body_json = json.loads(body)
                if isinstance(body_json, dict) and body_json.get("status") == "failed":
                    err_reason = body_json.get("error", "") or str(body_json)
                    self._err(
                        f"Grsai 返回失败：{err_reason}",
                        status_code=resp.status_code, body_text=body,
                        api_format="v1/api/generate", model=model, base_url=base_url,
                    )
                    raise RuntimeError(f"Grsai status=failed: {err_reason}")
            except (json.JSONDecodeError, RuntimeError):
                pass
            self._err(f"Grsai error: {resp.status_code} - {body[:500]}",
                status_code=resp.status_code, body_text=body,
                api_format="v1/api/generate", model=model, base_url=base_url)
            raise RuntimeError(f"Grsai HTTP {resp.status_code}")

        result = self._safe_json_response(resp, "v1/api/generate", model, base_url)
        if result.get("status") == "failed":
            err_reason = result.get("error", "") or str(result)
            if "apikey" in str(err_reason).lower() or "api key" in str(err_reason).lower():
                self._err(
                    f"API Key 无效（Grsai: {err_reason}）。请确认 Key 与中转站是否配套。",
                    status_code=0, body_text=resp.text,
                    api_format="v1/api/generate", model=model, base_url=base_url,
                )
            else:
                self._err(
                    f"Grsai 返回失败：{err_reason}",
                    status_code=0, body_text=resp.text,
                    api_format="v1/api/generate", model=model, base_url=base_url,
                )
            raise RuntimeError(f"Grsai status=failed: {err_reason}")
        return result

    # ─── Gemini native ────────────────────────────────────────────────────────────
    def _gemini_generate(self, base_url, api_key, model, prompt, ratio, size,
                         images, seed, pbar, deadline=None):
        paths = API_PATHS.get("image_v1beta/models", {})
        path_tpl = paths.get("generate", "/v1beta/models/{model}:generateContent")
        url = f"{base_url}{path_tpl.format(model=model)}"
        timeout = self._banana_timeout(size)

        parts = [{"text": prompt}]
        for i, img in enumerate(images):
            self._check_interrupt()
            pbar.update_absolute(15 + i * 2)
            b64 = self._image_to_base64(img)
            parts.append({
                "inline_data": {
                    "mime_type": "image/png",
                    "data": b64,
                }
            })

        image_config = {}
        if ratio and ratio != "auto":
            image_config["aspectRatio"] = ratio
        if size and size != "auto":
            image_config["imageSize"] = size

        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
                "imageConfig": image_config,
            },
        }

        pbar.update_absolute(40)
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = self._http_post(url, headers=headers, json=payload, timeout=timeout, deadline=deadline)
        pbar.update_absolute(75)

        if resp.status_code != 200:
            self._err(f"Gemini error: {resp.status_code} - {resp.text[:500]}",
                status_code=resp.status_code, body_text=resp.text,
                api_format="v1beta/models", model=model, base_url=base_url)
            raise RuntimeError(f"Gemini HTTP {resp.status_code}")
        return self._safe_json_response(resp, "v1beta/models", model, base_url)

    # ─── gpt-image2 size calculator ─────────────────────────────────────────────
    def _multiple_of_16(self, value):
        return max(16, int(value) // 16 * 16)

    def _multiple_of_16_ceil(self, value):
        return max(16, ((int(value) + 15) // 16) * 16)

    def _multiple_of_16_nearest(self, value):
        return max(16, int(round(value / 16)) * 16)

    def _gpt_image2_size_from_ratio(self, ratio_key, size):
        ratio_value = GPT_IMAGE2_RATIO_VALUES.get(ratio_key)
        if not ratio_value:
            return "auto"

        if size == "1K":
            return GPT_IMAGE2_1K_RATIO_SIZES.get(ratio_key, "auto")

        target_pixels = min(
            GPT_IMAGE2_SIZE_TARGET_PIXELS.get(size, GPT_IMAGE2_SIZE_TARGET_PIXELS["2K"]),
            GPT_IMAGE2_MAX_PIXELS,
        )
        width = (target_pixels * ratio_value) ** 0.5
        height = (target_pixels / ratio_value) ** 0.5

        scale = min(GPT_IMAGE2_MAX_EDGE / max(width, height), 1.0)
        if scale < 1.0:
            width *= scale
            height *= scale

        base_w = self._multiple_of_16_nearest(width)
        base_h = self._multiple_of_16_nearest(height)
        best = None
        for dw in range(-16, 17):
            for dh in range(-16, 17):
                w = base_w + dw * 16
                h = base_h + dh * 16
                if w < 16 or h < 16:
                    continue
                if w > GPT_IMAGE2_MAX_EDGE or h > GPT_IMAGE2_MAX_EDGE:
                    continue
                area = w * h
                if area > target_pixels or area > GPT_IMAGE2_MAX_PIXELS:
                    continue
                area_gap = (target_pixels - area) / target_pixels
                ratio_gap = abs((w / h) - ratio_value) / ratio_value
                score = area_gap + ratio_gap
                if best is None or score < best[0]:
                    best = (score, w, h)

        if best is not None:
            return f"{best[1]}x{best[2]}"

        w = self._multiple_of_16(width)
        h = self._multiple_of_16(height)
        while w * h > target_pixels or w * h > GPT_IMAGE2_MAX_PIXELS:
            if w >= h:
                w -= 16
            else:
                h -= 16
        return f"{w}x{h}"

    def _gpt_image2_size(self, ratio, size, images, base_url="", adobe=False):
        if is_aipaiai_base_url(base_url):
            if ratio == "auto" and images:
                img = tensor2pil(images[0])[0]
                target = img.width / max(1, img.height)
                ratios = AIPAI_ADOBE_SIZES if adobe else AIPAI_IMAGE_SIZES
                ratio = min(ratios, key=lambda key: abs(float(key.split(":")[0]) / float(key.split(":")[1]) - target))
            return aipaiai_image_size(ratio, size, adobe=adobe)

        if ratio in GPT_IMAGE2_RATIO_VALUES:
            return self._gpt_image2_size_from_ratio(ratio, size)

        if ratio == "auto" and images:
            img = tensor2pil(images[0])[0]
            w, h = img.size
            if h <= 0:
                return self._gpt_image2_size_from_ratio("1:1", size)
            target = w / h
            best_key = min(
                GPT_IMAGE2_RATIO_VALUES.keys(),
                key=lambda k: abs(GPT_IMAGE2_RATIO_VALUES[k] - target),
            )
            return self._gpt_image2_size_from_ratio(best_key, size)

        return "auto"

    def _parse_size_pair(self, value):
        text = "" if value is None else str(value).strip().lower().replace("×", "x")
        if "x" not in text:
            return None
        left, right = text.split("x", 1)
        try:
            width = int(float(left.strip()))
            height = int(float(right.strip()))
        except ValueError:
            return None
        if width <= 0 or height <= 0:
            return None
        return width, height

    def _corner_fill(self, image):
        rgb = image.convert("RGB")
        width, height = rgb.size
        pixels = rgb.load()
        points = [
            pixels[0, 0],
            pixels[max(0, width - 1), 0],
            pixels[0, max(0, height - 1)],
            pixels[max(0, width - 1), max(0, height - 1)],
        ]
        return tuple(int(sum(pixel[index] for pixel in points) / len(points)) for index in range(3))

    def _fit_on_canvas(self, image, canvas_size):
        canvas_width, canvas_height = canvas_size
        source = image.convert("RGB")
        source_width, source_height = source.size
        if source_width <= 0 or source_height <= 0:
            return Image.new("RGB", canvas_size, (255, 255, 255))

        scale = min(canvas_width / source_width, canvas_height / source_height)
        resized_width = max(1, int(round(source_width * scale)))
        resized_height = max(1, int(round(source_height * scale)))
        resized = source.resize((resized_width, resized_height), Image.LANCZOS)

        canvas = Image.new("RGB", canvas_size, self._corner_fill(source))
        offset = ((canvas_width - resized_width) // 2, (canvas_height - resized_height) // 2)
        canvas.paste(resized, offset)
        return canvas

    def _prepare_gpt_image2_reference_canvas(self, images, ratio, target_size):
        if ratio == "auto" or not images:
            return images, False
        canvas_size = self._parse_size_pair(target_size)
        if canvas_size is None:
            return images, False

        prepared = []
        changed = False
        for image in images:
            try:
                pil_image = tensor2pil(image)[0]
            except Exception:
                prepared.append(image)
                continue
            if pil_image.size == canvas_size:
                prepared.append(image)
                continue
            prepared.append(pil2tensor(self._fit_on_canvas(pil_image, canvas_size)))
            changed = True
        return prepared, changed

    def _prompt_with_ratio_hint(self, prompt, ratio, target_size, prepared):
        text = "" if prompt is None else str(prompt).strip()
        if not prepared or ratio == "auto":
            return text
        size_hint = f"，输出画布按 {target_size}" if target_size else ""
        return (
            f"请生成宽高比为 {ratio} 的完整图片{size_hint}，不要沿用参考图的原始画布比例。\n"
            f"{text}"
        ).strip()

    def _tensor_size_text(self, image_tensor):
        try:
            pil_image = tensor2pil(image_tensor)[0]
            return f"{pil_image.width}x{pil_image.height}"
        except Exception:
            return ""

    def _gpt_image2_timeout(self, size):
        return GPT_IMAGE2_TIMEOUTS.get(size, self.timeout)

    def _gpt_image2_generate(self, base_url, api_key, model, prompt, ratio, size,
                             quality, moderation, images, pbar, deadline=None, adobe=False):
        paths = API_PATHS.get("image_v1/images", {})
        is_aipaiai = is_aipaiai_base_url(base_url)
        image_size = self._gpt_image2_size(ratio, size, images, base_url=base_url, adobe=adobe)
        if not is_aipaiai:
            images, reference_canvas_prepared = self._prepare_gpt_image2_reference_canvas(images, ratio, image_size)
            prompt = self._prompt_with_ratio_hint(prompt, ratio, image_size, reference_canvas_prepared)
        timeout = self._gpt_image2_timeout(size)
        headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        if is_aipaiai:
            request_quality = str(size).upper()
            if request_quality not in AIPAI_IMAGE_QUALITIES:
                request_quality = "2K"

        if images:
            url = f"{base_url}{paths.get('gpt_image2_edit', '/v1/images/edits')}"
            data_dict = {
                "model": model,
                "prompt": prompt,
                "size": image_size,
                "n": "1",
            }
            if is_aipaiai:
                data_dict.update({
                    "quality": quality if adobe else request_quality,
                    "response_format": "url",
                    **({"resolution": request_quality} if adobe else {}),
                })
            else:
                data_dict.update({
                    "quality": quality,
                    "moderation": moderation,
                })
            files_list = []
            for i, img in enumerate(images if is_aipaiai else images[:GPT_IMAGE2_MAX_IMAGES]):
                self._check_interrupt()
                pbar.update_absolute(15 + i * 2)
                img_bytes = self._image_to_bytes(img)
                files_list.append(
                    ("image[]", (f"image_{i+1}.png", BytesIO(img_bytes), "image/png"))
                )

            pbar.update_absolute(40)
            resp = self._http_post(url, headers=headers, data=data_dict, files=files_list, timeout=timeout, deadline=deadline)
        else:
            url = f"{base_url}{paths.get('gpt_image2_generate', '/v1/images/generations')}"
            payload = {
                "model": model,
                "prompt": prompt,
                "size": image_size,
                "n": 1,
            }
            if is_aipaiai:
                payload.update({
                    "quality": quality if adobe else request_quality,
                    "response_format": "url",
                    **({"resolution": request_quality} if adobe else {}),
                })
            else:
                payload.update({
                    "quality": quality,
                    "moderation": moderation,
                })

            pbar.update_absolute(40)
            resp = self._http_post(url, headers=headers, json=payload, timeout=timeout, deadline=deadline)

        pbar.update_absolute(75)

        if resp.status_code != 200:
            self._err(f"gpt-image2 error: {resp.status_code} - {resp.text[:500]}",
                status_code=resp.status_code, body_text=resp.text,
                api_format="v1/images", model=model, base_url=base_url)
            raise RuntimeError(f"gpt-image2 HTTP {resp.status_code}")
        return self._safe_json_response(resp, "v1/images", model, base_url)

    # ─── OpenAI text2img ────────────────────────────────────────────────────────
    def _openai_text2img(self, base_url, api_key, model, prompt, ratio, size, seed, pbar, deadline=None):
        paths = API_PATHS.get("image_v1/images", {})
        url = f"{base_url}{paths.get('generate', '/v1/images/generations')}"
        timeout = self._banana_timeout(size)

        payload = {
            "model": model,
            "prompt": prompt,
            "response_format": "url",
            "image_size": size,
            "n": 1,
        }
        if ratio and ratio != "auto":
            payload["aspect_ratio"] = ratio
        pbar.update_absolute(40)
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = self._http_post(url, headers=headers, json=payload, timeout=timeout, deadline=deadline)
        pbar.update_absolute(75)

        if resp.status_code != 200:
            self._err(f"Image create error: {resp.status_code} - {resp.text[:500]}",
                status_code=resp.status_code, body_text=resp.text,
                api_format="v1/images", model=model, base_url=base_url)
            raise RuntimeError(f"Image create HTTP {resp.status_code}")
        return self._safe_json_response(resp, "v1/images", model, base_url)

    # ─── OpenAI chat image ──────────────────────────────────────────────────────
    def _openai_chat_image(self, base_url, api_key, model, prompt, ratio, size,
                           images, seed, pbar, deadline=None):
        paths = API_PATHS.get("image_v1/chat/completions", {})
        url = f"{base_url}{paths.get('chat', '/v1/chat/completions')}"
        timeout = self._banana_timeout(size)

        chat_prompt = prompt
        if ratio and ratio != "auto":
            chat_prompt = (
                f"请生成宽高比为 {ratio} 的图片，严格保持这个画面比例。\n"
                + prompt.lstrip()
            )

        content = [{"type": "text", "text": chat_prompt}]
        parts = [{"text": chat_prompt}]
        for i, img in enumerate(images):
            self._check_interrupt()
            pbar.update_absolute(15 + i * 2)
            b64 = self._image_to_base64(img)
            uri = f"data:image/png;base64,{b64}" if b64 else ""
            if not uri:
                self._err(f"Failed to convert image {i + 1}.")
            content.append({"type": "image_url", "image_url": {"url": uri}})
            parts.append({"inline_data": {"mime_type": "image/png", "data": b64}})

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
            "max_tokens": 4096,
            "n": 1,
        }
        pbar.update_absolute(40)
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        resp = self._http_post(url, headers=headers, json=payload, timeout=timeout, deadline=deadline)
        pbar.update_absolute(75)

        if resp.status_code != 200:
            self._err(f"Image chat error: {resp.status_code} - {resp.text[:500]}",
                status_code=resp.status_code, body_text=resp.text,
                api_format="v1/chat/completions", model=model, base_url=base_url)
            raise RuntimeError(f"Image chat HTTP {resp.status_code}")
        return self._safe_json_response(resp, "v1/chat/completions", model, base_url)

    # ─── OpenAI edit ─────────────────────────────────────────────────────────────
    def _openai_edit(self, base_url, api_key, model, prompt, ratio, size,
                     images, seed, pbar, deadline=None):
        paths = API_PATHS.get("image_v1/images", {})
        url = f"{base_url}{paths.get('edit', '/v1/images/edits')}"
        timeout = self._banana_timeout(size)

        data_dict = {
            "model": model,
            "prompt": prompt,
            "response_format": "url",
            "image_size": size,
            "n": "1",
        }
        if ratio and ratio != "auto":
            data_dict["aspect_ratio"] = ratio
        files_list = []
        for i, img in enumerate(images):
            self._check_interrupt()
            pbar.update_absolute(15 + i * 2)
            img_bytes = self._image_to_bytes(img)
            files_list.append(
                ("image", (f"image_{i+1}.png", BytesIO(img_bytes), "image/png"))
            )

        pbar.update_absolute(40)
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = self._http_post(url, headers=headers, data=data_dict, files=files_list, timeout=timeout, deadline=deadline)
        pbar.update_absolute(75)

        if resp.status_code != 200:
            self._err(f"Image edit error: {resp.status_code} - {resp.text[:500]}",
                status_code=resp.status_code, body_text=resp.text,
                api_format="v1/images", model=model, base_url=base_url)
            raise RuntimeError(f"Image edit HTTP {resp.status_code}")
        return self._safe_json_response(resp, "v1/images", model, base_url)

    # ─── 提取图片 ────────────────────────────────────────────────────────────────
    def _extract_image(self, result, b64_only=False):
        data_list = result.get("data", [])
        if data_list:
            item = data_list[0]
            b64 = item.get("b64_json", "")
            if b64:
                return "base64", b64

            if not b64_only:
                img_url = (item.get("url")
                           or (item.get("image_url") or {}).get("url", "")
                           or item.get("output_url")
                           or item.get("download_url"))
                if img_url:
                    return "url", img_url

        candidates = result.get("candidates", [])
        for c in candidates:
            parts = (c.get("content") or {}).get("parts", [])
            for p in parts:
                inline = p.get("inlineData") or p.get("inline_data") or {}
                if inline.get("data"):
                    return "base64", inline["data"]

        results = result.get("results", [])
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict):
                    img_url = item.get("url") or item.get("b64_json") or item.get("download_url")
                    if img_url:
                        if "base64" in str(item) and item.get("b64_json"):
                            return "base64", img_url
                        return "url", img_url
                elif isinstance(item, str) and item.startswith("http"):
                    return "url", item

        choices = result.get("choices", [])
        for c in choices:
            msg = c.get("message") or {}
            content = msg.get("content", "")

            if isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    inline = item.get("inlineData") or item.get("inline_data") or {}
                    if inline.get("data"):
                        return "base64", inline["data"]
                    img_url = item.get("image_url")
                    if isinstance(img_url, dict) and isinstance(img_url.get("url"), str):
                        return "url", img_url["url"]
                    elif isinstance(img_url, str):
                        return "url", img_url
                continue

            if not isinstance(content, str) or not content:
                continue
            import re
            m = re.search(r"data:image/[a-zA-Z0-9.+-]+;base64,([A-Za-z0-9+/=\s]+)", content)
            if m:
                return "base64", m.group(1).strip()
            if b64_only:
                continue
            m = re.search(r"!\[[^\]]*\]\((https?://[^\s)]+)\)", content)
            if m:
                return "url", m.group(1)
            m = re.search(r"https?://\S+?\.(?:png|jpg|jpeg|webp|gif)(?:\?\S*)?", content, re.I)
            if m:
                return "url", m.group(0)

        if b64_only:
            self._err(f"gpt-image2 响应里没有 b64_json 字段：{json.dumps(result)[:500]}")
        self._err(f"No image in response: {json.dumps(result)[:500]}")

    def _download_image(self, url, timeout=60, deadline=None):
        remaining = self._ensure_budget(deadline, "下载图片阶段")
        if remaining is not None:
            timeout = self._download_timeout(getattr(self, '_current_size', '2K'), remaining)
        t0 = time.time()
        future = http_client._get_executor().submit(
            http_client.http_download_stream,
            url,
            timeout=timeout,
        )
        data, dl_t = self._wait_future_interruptible(future, "下载图片阶段", deadline=deadline)
        content = data
        safe_url = _redact_url_for_log(url)
        print(f"[LingxiBridge] download {len(content)/1024:.1f}KB in {dl_t:.1f}s | {safe_url}")
        try:
            img = Image.open(BytesIO(content)).convert("RGB")
        except Exception as e:
            self._err(
                f"下载到的内容不是图片 (url={safe_url}, size={len(content)}B)\n"
                f"前 200 字节：{content[:200].decode('utf-8', errors='replace')}\n原始错误：{e}"
            )
        return pil2tensor(img)

    def _base64_to_tensor(self, b64_data):
        self._check_interrupt()
        s = b64_data.strip()
        if s.startswith("data:"):
            comma = s.find(",")
            if comma != -1:
                s = s[comma + 1:]
        s = "".join(s.split())

        try:
            img_bytes = base64.b64decode(s, validate=False)
        except Exception as e:
            self._err(f"base64 解码失败：{e}\n原始前 200 字符：{b64_data[:200]!r}")

        try:
            img = Image.open(BytesIO(img_bytes)).convert("RGB")
        except Exception as e:
            head_hex = img_bytes[:16].hex(" ")
            head_txt = img_bytes[:200].decode("utf-8", errors="replace")
            self._err(
                f"base64 解出的内容不是图片 (bytes={len(img_bytes)})\n"
                f"前 16 字节 hex：{head_hex}\n"
                f"前 200 字节文本：{head_txt}\n原始错误：{e}"
            )
        return pil2tensor(img)

    # ─── RunningHub /openapi/v2 ─────────────────────────────────────────────────
    def _rh_poll(self, base_url, api_key, task_id, timeout=600, deadline=None):
        query_url = f"{base_url}/openapi/v2/query"
        start = time.time()
        interval = 2
        while time.time() - start < timeout:
            remaining = self._ensure_budget(deadline, "RunningHub 轮询阶段")
            sleep_for = min(interval, max(0, remaining - 1)) if remaining is not None else interval
            if sleep_for > 0:
                self._sleep_interruptible(sleep_for, "RunningHub 轮询阶段", deadline=deadline)
            interval = min(interval + 1, 6)
            try:
                query_timeout = 30
                if remaining is not None:
                    query_timeout = max(5, min(30, int(remaining)))

                def _do_query():
                    session = http_client._get_session()
                    return session.post(
                        query_url,
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json={"taskId": task_id},
                        timeout=query_timeout,
                    )

                future = http_client._get_executor().submit(_do_query)
                resp = self._wait_future_interruptible(future, "RunningHub 轮询阶段", deadline=deadline)
                if resp.status_code != 200:
                    if resp.status_code in (400, 401, 403, 404):
                        self._err(
                            f"RH query HTTP {resp.status_code}: {resp.text[:500]}",
                            status_code=resp.status_code,
                            body_text=resp.text,
                            api_format="runninghub-/openapi/v2",
                            base_url=base_url,
                        )
                    print(f"[LingxiBridge] RH query HTTP {resp.status_code}")
                    continue
                data = self._safe_json_response(resp, "runninghub-/openapi/v2", "", base_url)
                status = (data.get("status") or (data.get("data") or {}).get("status") or "").upper()
                if status == "FAILED":
                    reason = data.get("errorMessage") or json.dumps(data.get("failedReason") or {})
                    self._err(f"RH task failed: {reason}")
                if status in ("SUCCESS", "COMPLETED", "DONE"):
                    return data
            except Timeout:
                continue
            except RuntimeError:
                raise
            except Exception as e:
                print(f"[LingxiBridge] RH poll error: {e}")
                continue
        self._err(f"RH polling timeout after {round(time.time() - start, 1)}s")

    def _rh_image_generate(self, base_url, api_key, model, prompt, ratio, size, quality,
                           images, pbar, deadline=None):
        paths = API_PATHS.get("image_runninghub-/openapi/v2", {})
        has_images = len(images) > 0

        image_urls = []
        if has_images:
            pbar.update_absolute(10)
            t_up0 = time.time()
            upload_url = f"{base_url}/openapi/v2/media/upload/binary"
            tasks = []
            for i, img in enumerate(images):
                self._check_interrupt()
                img_bytes = self._image_to_bytes(img)
                tasks.append({
                    "url": upload_url,
                    "headers": {"Authorization": f"Bearer {api_key}"},
                    "files": {"file": (f"image_{i+1}.png", BytesIO(img_bytes), "image/png")},
                    "timeout": 60,
                })

            executor = http_client._get_executor()
            futures = []
            for task in tasks:
                def _upload_one(upload_task=task):
                    session = http_client._get_session()
                    url = upload_task.get("url")
                    timeout = upload_task.get("timeout", 300)
                    task_kwargs = {k: v for k, v in upload_task.items() if k not in ("url", "timeout")}
                    try:
                        resp = session.post(url, timeout=timeout, **task_kwargs)
                        resp.raise_for_status()
                        return {"success": True, "response": resp, "error": None}
                    except Exception as e:
                        return {"success": False, "response": None, "error": e}

                futures.append(executor.submit(_upload_one))

            results = [
                self._wait_future_interruptible(f, "RunningHub 上传图片阶段", deadline=deadline)
                for f in futures
            ]
            for i, r in enumerate(results):
                pbar.update_absolute(15 + i * 3)
                if not r["success"]:
                    self._err(f"RH upload image {i+1} failed: {r['error']}",
                        api_format="runninghub-/openapi/v2", model=model, base_url=base_url)
                resp = r["response"]
                if resp.status_code != 200:
                    self._err(
                        f"RH upload image {i+1} HTTP {resp.status_code}: {resp.text[:200]}",
                        status_code=resp.status_code,
                        body_text=resp.text,
                        api_format="runninghub-/openapi/v2",
                        model=model,
                        base_url=base_url,
                    )
                    raise RuntimeError(f"RH upload image {i+1} HTTP {resp.status_code}")
                data = self._safe_json_response(resp, "runninghub-/openapi/v2", model, base_url)
                dl_url = (data.get("data") or {}).get("download_url") \
                    or (data.get("data") or {}).get("downloadUrl") \
                    or (data.get("data") or {}).get("url")
                if not dl_url:
                    self._err(f"RH upload image {i+1}: no download_url in {json.dumps(data)[:300]}")
                image_urls.append(dl_url)
            t_up = time.time() - t_up0
            print(f"[LingxiBridge] RH uploaded {len(images)} images concurrently in {t_up:.1f}s")

        size_map = {"1K": "1k", "2K": "2k", "4K": "4k"}
        resolution = size_map.get((size or "").upper(), "2k")
        aspect_ratio = ratio if ratio and ratio != "auto" else "1:1"

        payload = {
            "prompt": prompt,
            "aspectRatio": aspect_ratio,
            "resolution": resolution,
            "quality": quality or "medium",
        }
        if image_urls:
            payload["imageUrls"] = image_urls

        if has_images:
            endpoint = paths.get("edit", f"/openapi/v2/{model}/image-to-image")
        else:
            endpoint = paths.get("create", f"/openapi/v2/{model}/text-to-image")
        url = f"{base_url}{endpoint.format(model=model)}"

        pbar.update_absolute(40)
        resp = self._http_post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout,
            deadline=deadline,
        )
        pbar.update_absolute(50)

        if resp.status_code != 200:
            self._err(f"RH image submit error: {resp.status_code} - {resp.text[:500]}",
                status_code=resp.status_code, body_text=resp.text,
                api_format="runninghub-/openapi/v2", model=model, base_url=base_url)
            raise RuntimeError(f"RH submit HTTP {resp.status_code}")

        result = self._safe_json_response(resp, "runninghub-/openapi/v2", model, base_url)
        task_id = result.get("taskId") or result.get("task_id") or result.get("id")
        if not task_id:
            self._err(f"RH image: no taskId in {json.dumps(result)[:500]}")

        if result.get("status", "").upper() == "FAILED":
            self._err(f"RH image task failed immediately: {result.get('errorMessage', '')}")

        print(f"[LingxiBridge] RH image task created: {task_id}")
        pbar.update_absolute(55)

        poll_data = self._rh_poll(base_url, api_key, task_id, timeout=self._total_budget(size), deadline=deadline)
        pbar.update_absolute(85)
        return poll_data

    def _rh_extract_image(self, poll_data):
        for container in (poll_data, poll_data.get("data") or {}):
            if not isinstance(container, dict):
                continue
            for key in ("image_url", "output_url", "download_url", "file_url", "url"):
                val = container.get(key)
                if isinstance(val, dict):
                    inner = val.get("url") or val.get("download_url")
                    if isinstance(inner, str) and inner.startswith("http"):
                        return inner
                if isinstance(val, str) and val.startswith("http"):
                    return val
            output = container.get("output")
            if isinstance(output, dict):
                for k in ("url", "image_url", "download_url"):
                    v = output.get(k)
                    if isinstance(v, str) and v.startswith("http"):
                        return v
            results = container.get("results") or container.get("images") or []
            if isinstance(results, list):
                for item in results:
                    if isinstance(item, str) and item.startswith("http"):
                        return item
                    if isinstance(item, dict):
                        for k in ("url", "image_url", "download_url", "output_url"):
                            v = item.get(k)
                            if isinstance(v, str) and v.startswith("http"):
                                return v
        return None

    # ─── 主入口 ─────────────────────────────────────────────────────────────────
    def generate_image(self, prompt, ratio, size, quality, format, moderation, seed,
                       info="", **kwargs):
        parsed = {}
        if info and info.strip():
            try:
                parsed = json.loads(info)
            except Exception:
                pass

        try:
            api_key = self._get_api_key(parsed.get("apikey", ""))
            if not api_key:
                self._err(
                    "API key is empty or invalid. Please enter a valid API key in the Lingxi Bridge Settings node. "
                    "Note: 'None' or empty strings are not valid API keys."
                )

            raw_base = parsed.get("api_base", "")
            base_url = (raw_base.strip().rstrip('/') if raw_base.strip() else get_current_base_url()).rstrip('/')
            base_url = normalize_aipaiai_base_url(base_url)
            model = parsed.get("model", "")
            api_format = parsed.get("api_format", "v1/images")
            platform = parsed.get("platform", "banana-pro")
            adobe = is_aipaiai_base_url(base_url) and is_aipaiai_adobe(api_format, model)
            if api_format == AIPAI_ADOBE_FORMAT:
                if not adobe or platform not in {"gpt-image2", "gpt-image2.5"}:
                    self._err("AIPAI Adobe 接口请使用 aipaiai.cn 地址和 gpt-image2 / gpt-image2.5 平台。")
                api_format = "v1/images"
            if platform in {"gpt-image2", "gpt-image2.5"} and api_format not in {"v1/images", "runninghub-/openapi/v2"}:
                self._err("GPT Image only supports v1/images or runninghub-/openapi/v2.")
            if api_format not in {"v1beta/models", "v1/chat/completions", "v1/images", "v1/api/generate", "runninghub-/openapi/v2"}:
                self._err(f"Unsupported image api_format: {api_format}")
            allowed_ratios = IMAGE_RATIOS_BY_PLATFORM.get(platform, IMAGE_RATIOS_BASE)
            ratio = self._normalize_choice("ratio", ratio, allowed_ratios, "auto")
            size = self._normalize_choice("size", size, IMAGE_SIZES, "2K")
            quality = self._normalize_choice("quality", quality, GPT_IMAGE2_QUALITIES, "medium")
            moderation = self._normalize_choice("moderation", moderation, GPT_IMAGE2_MODERATIONS, "low")
            print(f"[LingxiBridge] image | {platform} | {api_format} | {base_url} | {model}")

            images = []
            for i in range(1, ALL_MAX_IMAGES + 1):
                img = kwargs.get(f"image{i}")
                if img is not None:
                    images.append(img)

            has_images = len(images) > 0

            pbar = comfy.utils.ProgressBar(100)
            pbar.update_absolute(10)
            self._check_interrupt()
            t_total_start = time.time()
            self._current_size = size
            total_budget = self._total_budget(size)
            deadline = t_total_start + total_budget

            if api_format == "runninghub-/openapi/v2":
                poll_data = self._rh_image_generate(
                    base_url, api_key, model, prompt, ratio, size, quality,
                    images, pbar, deadline=deadline,
                )
                img_url = self._rh_extract_image(poll_data)
                if not img_url:
                    self._err(f"RH image: no image URL in poll result: {json.dumps(poll_data)[:500]}")
                print(f"[LingxiBridge] RH image URL: {_redact_url_for_log(img_url)}")
                t_api = time.time() - t_total_start
                pbar.update_absolute(90)
                img_tensor = self._download_image(img_url, timeout=self._download_timeout(size), deadline=deadline)
                target_size = self._gpt_image2_size(ratio, size, images, base_url=base_url, adobe=adobe)
                original_output_size = self._tensor_size_text(img_tensor)
                size_mismatch = bool(target_size and original_output_size and target_size != original_output_size)
                if size_mismatch:
                    print(f"[LingxiBridge] output size mismatch: requested {target_size}, got {original_output_size}")
                pbar.update_absolute(100)
                resp_json = self._success_response(
                    "url",
                    img_url,
                    model,
                    api_format,
                    platform,
                    size,
                    ratio,
                    requested_size_pixels=target_size,
                    original_output_size=original_output_size,
                    output_size_mismatch=size_mismatch,
                )
                print(f"[LingxiBridge] TIMING total={time.time()-t_total_start:.1f}s api={t_api:.1f}s")
                return (img_tensor, resp_json, img_url, "")

            elif api_format == "v1/api/generate":
                result = self._grsai_generate(
                    base_url, api_key, model, prompt, ratio, size,
                    images, pbar, deadline=deadline,
                )

            elif platform in {"gpt-image2", "gpt-image2.5"}:
                result = self._gpt_image2_generate(
                    base_url, api_key, model, prompt, ratio, size, quality, moderation,
                    images, pbar, deadline=deadline, adobe=adobe,
                )
            elif api_format == "v1beta/models":
                result = self._gemini_generate(
                    base_url, api_key, model, prompt, ratio, size,
                    images, seed, pbar, deadline=deadline,
                )
            elif api_format == "v1/chat/completions":
                result = self._openai_chat_image(
                    base_url, api_key, model, prompt, ratio, size,
                    images, seed, pbar, deadline=deadline,
                )
            else:
                if has_images:
                    result = self._openai_edit(
                        base_url, api_key, model, prompt, ratio, size,
                        images, seed, pbar, deadline=deadline,
                    )
                else:
                    result = self._openai_text2img(
                        base_url, api_key, model, prompt, ratio, size, seed, pbar, deadline=deadline,
                    )

            t_api = time.time() - t_total_start
            pbar.update_absolute(80)
            img_type, img_data = self._extract_image(result)
            self._check_interrupt()

            if img_type == "url":
                print(f"[LingxiBridge] Downloading image: {_redact_url_for_log(img_data)}")
                t_dec0 = time.time()
                img_tensor = self._download_image(
                    img_data,
                    timeout=self._download_timeout(size),
                    deadline=deadline,
                )
                if platform in {"gpt-image2", "gpt-image2.5"}:
                    target_size = self._gpt_image2_size(ratio, size, images, base_url=base_url, adobe=adobe)
                    original_output_size = self._tensor_size_text(img_tensor)
                    size_mismatch = bool(target_size and original_output_size and target_size != original_output_size)
                    if size_mismatch:
                        print(f"[LingxiBridge] output size mismatch: requested {target_size}, got {original_output_size}")
                else:
                    target_size = ""
                    original_output_size = ""
                    size_mismatch = False
                t_dec = time.time() - t_dec0
                pbar.update_absolute(100)
                resp_json = self._success_response(
                    "url",
                    img_data,
                    model,
                    api_format,
                    platform,
                    size,
                    ratio,
                    requested_size_pixels=target_size,
                    original_output_size=original_output_size,
                    output_size_mismatch=size_mismatch,
                )
                print(f"[LingxiBridge] TIMING total={time.time()-t_total_start:.1f}s api={t_api:.1f}s decode(url)={t_dec:.1f}s")
                return (img_tensor, resp_json, img_data, "")
            else:
                t_dec0 = time.time()
                img_tensor = self._base64_to_tensor(img_data)
                if platform in {"gpt-image2", "gpt-image2.5"}:
                    target_size = self._gpt_image2_size(ratio, size, images, base_url=base_url, adobe=adobe)
                    original_output_size = self._tensor_size_text(img_tensor)
                    size_mismatch = bool(target_size and original_output_size and target_size != original_output_size)
                    if size_mismatch:
                        print(f"[LingxiBridge] output size mismatch: requested {target_size}, got {original_output_size}")
                else:
                    target_size = ""
                    original_output_size = ""
                    size_mismatch = False
                t_dec = time.time() - t_dec0
                pbar.update_absolute(100)
                resp_json = self._success_response(
                    "base64",
                    "",
                    model,
                    api_format,
                    platform,
                    size,
                    ratio,
                    requested_size_pixels=target_size,
                    original_output_size=original_output_size,
                    output_size_mismatch=size_mismatch,
                )
                print(f"[LingxiBridge] TIMING total={time.time()-t_total_start:.1f}s api={t_api:.1f}s decode(b64)={t_dec:.1f}s")
                return (img_tensor, resp_json, "", "")

        except comfy.model_management.InterruptProcessingException:
            print("[LingxiBridge] image generation interrupted by user")
            raise
        except (Timeout, ConnectionError, SSLError) as e:
            self._raw_err_body = str(e)
            reason, suggestion, original = self._diagnose(0, str(e), "", "", "")
            self._error_status_code = 0
            self._error_reason = reason
            self._error_suggestion = suggestion
            self._error_original = original
            return (ExecutionBlocker(None), self._error_response(e), "", self._friendly_error_text(e))
        except Exception as e:
            return (ExecutionBlocker(None), self._error_response(e), "", self._friendly_error_text(e))
