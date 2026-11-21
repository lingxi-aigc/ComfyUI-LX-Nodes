# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from typing import Any

from ..categories import LX_RELAY_CATEGORY
from ..lingxi_bridge.lb_image import (
    GPT_IMAGE2_MODERATIONS,
    GPT_IMAGE2_QUALITIES,
    IMAGE_RATIOS,
    IMAGE_SIZES,
)
from .shared import (
    FOLDER_BATCH_TASKS_TYPE,
    PAIR_MODES,
    PAIR_MODE_PRODUCT,
    PAIR_MODE_SEQUENCE,
    SAVE_FORMATS,
    build_matched_groups,
    build_sequence_groups,
    clean_str,
    image_batch,
    iter_product_groups,
    make_task,
    make_collage,
    make_single_task_preview,
    normalize_dir,
    normalize_pair_mode,
    scan_images,
    task_payload,
)


def _clamp_limit(value: object) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return 0
    return max(0, number)


def _settings(
    prompt: str,
    save_format: str,
    ratio: str,
    size: str,
    quality: str,
    moderation: str,
) -> dict[str, str]:
    return {
        "prompt": clean_str(prompt),
        "save_format": save_format if save_format in SAVE_FORMATS else "PNG",
        "ratio": clean_str(ratio) or "auto",
        "size": clean_str(size) or "2K",
        "quality": clean_str(quality) or "medium",
        "moderation": clean_str(moderation) or "low",
    }


class LingxiSingleFolderBatchGenerate:
    CATEGORY = f"{LX_RELAY_CATEGORY}/文件夹批量"
    RETURN_TYPES = (FOLDER_BATCH_TASKS_TYPE, "STRING", "STRING", "IMAGE")
    RETURN_NAMES = ("批量任务", "预览文本", "状态JSON", "预览图像")
    FUNCTION = "generate_tasks"
    SIZE = (440, 420)
    SEARCH_ALIASES = ("lx", "LX", "灵犀", "灵犀单图批量（文件夹）", "灵犀单图批量生成", "单图批量", "白底图批量")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "输入文件夹": ("STRING", {"default": "", "placeholder": "待处理图片文件夹", "tooltip": "扫描这个文件夹里的图片并为每张图生成一个任务。开启“包含子文件夹”后会递归扫描。"}),
                "包含子文件夹": ("BOOLEAN", {"default": True, "label_on": "包含", "label_off": "不含", "tooltip": "开启后会扫描所有子目录；单图批量会尽量保留原来的相对目录结构。"}),
                "输出文件夹": ("STRING", {"default": "", "placeholder": "留空则保存到 ComfyUI/output/lingxi_folder_batch", "tooltip": "生成结果保存到这里。留空时使用 ComfyUI/output/lingxi_folder_batch。"}),
                "提示词": ("STRING", {"default": "", "multiline": True, "tooltip": "所有扫描到的图片都会使用这段提示词生成。如需不同提示词，建议拆成多个批量节点。"}),
                "任务上限": ("INT", {"default": 0, "min": 0, "max": 20000, "step": 1, "tooltip": "0 表示不限制。大批量前可以先填 5 或 10 试跑，确认命名和效果。"}),
                "单张测试": ("INT", {"default": 0, "min": 0, "max": 20000, "step": 1, "tooltip": "0 表示正常批量；填写排序编号后只生成这一张的任务，例如 3 表示只跑第 3 张。"}),
                "保存格式": (SAVE_FORMATS, {"default": "PNG", "tooltip": "决定最终保存到硬盘的图片格式，不改变 API 的生成逻辑。"}),
                "ratio": (IMAGE_RATIOS, {"default": "auto", "tooltip": "输出画幅比例。auto 表示让 API 根据输入图和提示词自行判断。"}),
                "size": (IMAGE_SIZES, {"default": "2K", "tooltip": "输出尺寸档位。尺寸越高通常越慢，消耗也可能更高。"}),
                "quality": (GPT_IMAGE2_QUALITIES, {"default": "medium", "tooltip": "生成质量档位。质量越高通常越慢，消耗也可能更高。"}),
                "moderation": (GPT_IMAGE2_MODERATIONS, {"default": "low", "tooltip": "内容审核强度。默认 low 通常更宽松；如果接口报审核相关错误再调整。"}),
            },
            "optional": {
                "API池": ("STRING", {"default": "", "forceInput": True, "tooltip": "可选：连接灵犀 API 池，仅用于按平台刷新 ratio/size/quality/moderation；真正执行仍连接到批量执行节点。"}),
            },
        }

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def generate_tasks(
        self,
        输入文件夹="",
        包含子文件夹=True,
        输出文件夹="",
        提示词="",
        任务上限=0,
        单张测试=0,
        保存格式="PNG",
        ratio="auto",
        size="2K",
        quality="medium",
        moderation="low",
        **kwargs,
    ):
        if "处理上限" in kwargs:
            任务上限 = kwargs["处理上限"]

        output_root = normalize_dir(输出文件夹, default_output=True)
        input_root, records, scan_error = scan_images(输入文件夹, bool(包含子文件夹))
        limit = _clamp_limit(任务上限)
        test_index = _clamp_limit(单张测试)
        if test_index > 0:
            if test_index <= len(records):
                selected_pairs = [(test_index, records[test_index - 1])]
            else:
                selected_pairs = []
        else:
            selected = records[:limit] if limit > 0 else records
            selected_pairs = list(enumerate(selected, start=1))
        settings = _settings(提示词, 保存格式, ratio, size, quality, moderation)

        used_output_rel_paths: set[str] = set()

        tasks: list[dict[str, Any]] = []
        selected_task_indices: list[int] = []
        for original_index, record in selected_pairs:
            tasks.append(
                make_task(
                    prompt=settings["prompt"],
                    image_records=[record],
                    output_root=output_root,
                    output_rel_stem=record.get("rel_stem", "") or record.get("stem", "image"),
                    save_format=settings["save_format"],
                    ratio=settings["ratio"],
                    size=settings["size"],
                    quality=settings["quality"],
                    moderation=settings["moderation"],
                    task_name=record.get("rel_path", "") or record.get("name", "image"),
                    source_count=1,
                    used_output_rel_paths=used_output_rel_paths,
                )
            )
            selected_task_indices.append(original_index)

        lines: list[str] = []
        lines.append(f"任务预览：生成 {len(tasks)} 个任务")
        lines.append(f"输入：{input_root or '-'}，扫描 {len(records)} 张")
        lines.append(f"输出：{output_root}")
        lines.append(f"保存格式：{settings['save_format']}")
        if test_index > 0:
            if tasks:
                task = tasks[0]
                rel_path = (task.get("image_rel_paths") or [""])[0]
                lines.append(f"单张测试：第 {test_index} / {len(records)} 张：{rel_path}")
            else:
                lines.append(f"单张测试序号超出范围：{test_index}，当前共 {len(records)} 张。")
        elif limit > 0:
            lines.append(f"任务上限：最多生成 {limit} 个任务")
        if scan_error:
            lines.append(f"提醒：{scan_error}")
        lines.append("")
        if tasks:
            lines.append("任务列表（前 20 个）：")
        for original_index, task in zip(selected_task_indices[:20], tasks[:20]):
            lines.append(f"{original_index}. {task['image_rel_paths'][0]} -> {task['output_rel_path']}")
        if len(tasks) > 20:
            lines.append(f"... 还有 {len(tasks) - 20} 个任务")

        meta: dict[str, Any] = {
            "mode": "single",
            "input_root": input_root,
            "output_root": output_root,
            "scanned": len(records),
            "task_count": len(tasks),
            "limit": limit,
            "single_test": test_index,
            "scan_error": scan_error,
        }
        payload = task_payload(tasks, meta)
        status_json = json.dumps({"type": "lx_single_folder_batch_preview", **meta}, ensure_ascii=False, indent=2)
        label_digits = max(3, len(str(max(selected_task_indices or [len(tasks)]))))
        preview_images = [
            make_single_task_preview(
                (task.get("image_paths") or [""])[0],
                f"#{original_index:0{label_digits}d}",
                (task.get("image_rel_paths") or [""])[0],
            )
            for original_index, task in zip(selected_task_indices[:64], tasks[:64])
        ]
        return (payload, "\n".join(lines), status_json, image_batch(preview_images))


class LingxiMultiFolderBatchGenerate:
    CATEGORY = f"{LX_RELAY_CATEGORY}/文件夹批量"
    RETURN_TYPES = (FOLDER_BATCH_TASKS_TYPE, "IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("批量任务", "匹配预览图像", "配对预览文本", "状态JSON")
    FUNCTION = "generate_tasks"
    SIZE = (480, 560)
    SEARCH_ALIASES = ("lx", "LX", "灵犀", "灵犀多图批量（文件夹）", "灵犀多图批量生成", "多图批量", "换装批量")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "图1文件夹": ("STRING", {"default": "", "placeholder": "例如：模特文件夹", "tooltip": "第 1 个图源文件夹。多图批量至少需要填写 2 个图源。"}),
                "图2文件夹": ("STRING", {"default": "", "placeholder": "例如：服装文件夹", "tooltip": "第 2 个图源文件夹。会和图1按“配对方式”组合成任务。"}),
                "图3文件夹": ("STRING", {"default": "", "tooltip": "可选的第 3 个图源。填写后每个任务会同时带上图1、图2、图3。"}),
                "图4文件夹": ("STRING", {"default": "", "tooltip": "可选的第 4 个图源。留空则不参与配对。"}),
                "包含子文件夹": ("BOOLEAN", {"default": True, "label_on": "包含", "label_off": "不含", "tooltip": "开启后递归扫描子目录；同名匹配会使用相对路径，更适合多层目录一一对应。"}),
                "输出文件夹": ("STRING", {"default": "", "placeholder": "留空则保存到 ComfyUI/output/lingxi_folder_batch", "tooltip": "生成结果保存到这里。留空时使用 ComfyUI/output/lingxi_folder_batch。"}),
                "提示词": ("STRING", {"default": "", "multiline": True, "tooltip": "每一组配对图片都会使用这段提示词生成。如需不同提示词，建议拆成多个批量节点。"}),
                "配对方式": (PAIR_MODES, {"default": "同名匹配", "tooltip": "同名匹配：文件名/相对路径一致；末尾编号匹配：按结尾数字配对；去尾序号匹配：去掉末尾 _1/-1/ 1 后配对；顺序匹配：自然排序后第 N 张配第 N 张；全部组合：每张图都搭配其他图源每一张。"}),
                "任务上限": ("INT", {"default": 0, "min": 0, "max": 20000, "step": 1, "tooltip": "0 表示不限制。全部组合模式下任务可能很多，建议先填小数字试跑。"}),
                "保存格式": (SAVE_FORMATS, {"default": "PNG", "tooltip": "决定最终保存到硬盘的图片格式，不改变 API 的生成逻辑。"}),
                "ratio": (IMAGE_RATIOS, {"default": "auto", "tooltip": "输出画幅比例。auto 表示让 API 根据输入图和提示词自行判断。"}),
                "size": (IMAGE_SIZES, {"default": "2K", "tooltip": "输出尺寸档位。尺寸越高通常越慢，消耗也可能更高。"}),
                "quality": (GPT_IMAGE2_QUALITIES, {"default": "medium", "tooltip": "生成质量档位。质量越高通常越慢，消耗也可能更高。"}),
                "moderation": (GPT_IMAGE2_MODERATIONS, {"default": "low", "tooltip": "内容审核强度。默认 low 通常更宽松；如果接口报审核相关错误再调整。"}),
            },
            "optional": {
                "API池": ("STRING", {"default": "", "forceInput": True, "tooltip": "可选：连接灵犀 API 池，仅用于按平台刷新 ratio/size/quality/moderation；真正执行仍连接到批量执行节点。"}),
            },
        }

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def generate_tasks(
        self,
        图1文件夹="",
        图2文件夹="",
        图3文件夹="",
        图4文件夹="",
        包含子文件夹=True,
        输出文件夹="",
        提示词="",
        配对方式="同名匹配",
        任务上限=0,
        保存格式="PNG",
        ratio="auto",
        size="2K",
        quality="medium",
        moderation="low",
        **kwargs,
    ):
        if "处理上限" in kwargs:
            任务上限 = kwargs["处理上限"]

        include_subfolders = bool(包含子文件夹)
        pair_mode = normalize_pair_mode(配对方式)
        folders = [图1文件夹, 图2文件夹, 图3文件夹, 图4文件夹]
        output_root = normalize_dir(输出文件夹, default_output=True)
        limit = _clamp_limit(任务上限)
        settings = _settings(提示词, 保存格式, ratio, size, quality, moderation)

        sources: list[dict[str, Any]] = []
        scan_errors: list[str] = []
        for index, folder in enumerate(folders, start=1):
            if not clean_str(folder):
                continue
            root, records, scan_error = scan_images(folder, include_subfolders)
            if scan_error:
                scan_errors.append(f"图{index}: {scan_error}")
            sources.append({"index": index, "root": root, "records": records})

        tasks: list[dict[str, Any]] = []
        used_output_rel_paths: set[str] = set()
        pair_detail: dict[str, Any] = {}
        total_possible = 0
        capped = False

        if len(sources) < 2:
            pair_detail = {"error": "至少需要填写 2 个图源文件夹。"}
            groups: list[tuple[str, list[dict[str, str]]]] = []
        elif any(len(source["records"]) == 0 for source in sources):
            pair_detail = {"error": "有图源没有扫描到图片。"}
            groups = []
        elif pair_mode == PAIR_MODE_PRODUCT:
            groups, total_possible, capped = iter_product_groups(sources, limit)
            if limit > 0:
                groups = groups[:limit]
            pair_detail = {"total_possible": total_possible, "capped": capped}
        elif pair_mode == PAIR_MODE_SEQUENCE:
            groups, pair_detail = build_sequence_groups(sources)
            if limit > 0:
                groups = groups[:limit]
        else:
            groups, pair_detail = build_matched_groups(sources, pair_mode, include_subfolders)
            if limit > 0:
                groups = groups[:limit]

        for index, (key, records) in enumerate(groups, start=1):
            if pair_mode == PAIR_MODE_PRODUCT:
                rel_stem = key
            else:
                rel_stem = key
            task = make_task(
                prompt=settings["prompt"],
                image_records=records,
                output_root=output_root,
                output_rel_stem=rel_stem,
                save_format=settings["save_format"],
                ratio=settings["ratio"],
                size=settings["size"],
                quality=settings["quality"],
                moderation=settings["moderation"],
                task_name=f"任务{index}",
                source_count=len(records),
                used_output_rel_paths=used_output_rel_paths,
            )
            tasks.append(task)

        unmatched = pair_detail.get("unmatched", []) if isinstance(pair_detail, dict) else []
        duplicates = pair_detail.get("duplicates", []) if isinstance(pair_detail, dict) else []
        no_key = pair_detail.get("no_key", []) if isinstance(pair_detail, dict) else []
        unmatched_count = len(unmatched) + len(duplicates) + len(no_key)

        lines: list[str] = []
        source_summary = "，".join(f"图{source['index']} {len(source['records'])} 张" for source in sources) or "-"
        lines.append(f"配对完成：生成 {len(tasks)} 个任务")
        lines.append(f"图源：{source_summary}")
        lines.append(f"配对方式：{pair_mode}")
        if pair_mode == PAIR_MODE_SEQUENCE:
            lines.append(f"顺序配对：{len(tasks)} 组，未使用：{len(unmatched)}")
        elif no_key:
            lines.append(f"未匹配：{len(unmatched)}，重复：{len(duplicates)}，未提取编号：{len(no_key)}")
        else:
            lines.append(f"未匹配：{len(unmatched)}，重复：{len(duplicates)}")
        lines.append(f"输出格式：{settings['save_format']}")
        lines.append(f"输出：{output_root}")
        if limit > 0:
            lines.append(f"任务上限：最多生成 {limit} 个任务")
        if len(sources) < 2:
            lines.append("提醒：至少填写 2 个图源文件夹。")
        if pair_mode == PAIR_MODE_PRODUCT and len(sources) >= 2:
            lines.append(f"全部组合预计：{total_possible} 个任务")
            if capped:
                lines.append("提醒：任务数超过安全上限，已截断到 20000 个；建议设置任务上限先试跑。")
        for error in scan_errors:
            lines.append(f"提醒：{error}")
        if sources:
            lines.append("")
            lines.append("图源路径：")
            for source in sources:
                lines.append(f"- 图{source['index']}：{source['root'] or '-'}")
        lines.append("")
        if tasks:
            lines.append("配对预览（前 20 个）：")
            for index, task in enumerate(tasks[:20], start=1):
                refs = " + ".join(task.get("image_rel_paths", []))
                lines.append(f"{index}. {refs} -> {task['output_rel_path']}")
            if len(tasks) > 20:
                lines.append(f"... 还有 {len(tasks) - 20} 个任务")
        if unmatched_count:
            lines.append("")
            lines.append("未处理/需整理的图片：")
            for item in unmatched[:12]:
                label = "未使用" if pair_mode == PAIR_MODE_SEQUENCE else "key"
                lines.append(f"- {item.get('source')}: {item.get('rel_path')}（{label}: {item.get('key') or '-'}）")
            for item in duplicates[:8]:
                lines.append(f"- {item.get('source')}: key {item.get('key')} 有重复文件")
            for item in no_key[:8]:
                lines.append(f"- {item.get('source')}: {item.get('rel_path')} 未提取到编号")
            more = unmatched_count - min(len(unmatched), 12) - min(len(duplicates), 8) - min(len(no_key), 8)
            if more > 0:
                lines.append(f"... 还有 {more} 项")

        meta: dict[str, Any] = {
            "mode": "multi",
            "output_root": output_root,
            "source_count": len(sources),
            "source_sizes": [len(source["records"]) for source in sources],
            "pair_mode": pair_mode,
            "task_count": len(tasks),
            "unmatched_count": unmatched_count,
            "limit": limit,
            "pair_detail": pair_detail,
            "scan_errors": scan_errors,
        }
        payload = task_payload(tasks, meta)
        status_json = json.dumps({"type": "lx_multi_folder_batch_preview", **meta}, ensure_ascii=False, indent=2)
        preview_images = [
            make_collage(task.get("image_paths", []))
            for task in tasks[:64]
        ]
        return (payload, image_batch(preview_images), "\n".join(lines), status_json)
