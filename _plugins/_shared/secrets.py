"""Shared secret reference helpers for LX nodes.

This module keeps the existing local config path for compatibility with
already-saved workflows and API keys.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import uuid


_CONFIG_DIR = os.path.dirname(os.path.realpath(__file__))
CONFIG_FILE = os.path.join(_CONFIG_DIR, "relay_config.local.json")
CONFIG_EXAMPLE_FILE = os.path.join(_CONFIG_DIR, "relay_config.example.json")
LEGACY_CONFIG_FILE = os.path.join(_CONFIG_DIR, "relay_config.json")
_config_lock = threading.RLock()

DEFAULT_API_BASES = [
    "https://grsaiapi.com",
    "https://yunwu.ai",
    "https://www.runninghub.cn",
]

SECRET_REF_PREFIX = "__LX_SECRET__:"
SECRET_KIND_API_KEY = "lingxi_api_key"
SECRET_KIND_API_POOL = "lingxi_api_pool"
SECRET_KIND_QWEN3VL = "qwen3vl_api_key"


def _default_config():
    return {
        "base_url": DEFAULT_API_BASES[0],
        "node_settings": {},
        "key_secrets": {},
        "custom_api_bases": [],
        "removed_defaults": [],
        "custom_api_formats": {},
        "custom_models": {},
        "concurrency": {},
    }


def _candidate_config_files():
    return [CONFIG_FILE, LEGACY_CONFIG_FILE, CONFIG_EXAMPLE_FILE]


def get_config():
    with _config_lock:
        for path in _candidate_config_files():
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                return config if isinstance(config, dict) else _default_config()
            except Exception as exc:
                if path == CONFIG_FILE:
                    try:
                        shutil.copy2(path, f"{path}.broken")
                    except Exception:
                        pass
                print(f"[LX][shared] config read failed, skipped {path}: {exc}")
        return _default_config()


def save_config(config):
    with _config_lock:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        tmp_file = f"{CONFIG_FILE}.tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_file, CONFIG_FILE)


def _normalize_node_id(node_id):
    if node_id is None:
        return ""
    return str(node_id).strip()


def _normalize_secret_id(secret_id):
    if secret_id is None:
        return ""
    text = str(secret_id).strip()
    return "".join(ch for ch in text if ch.isalnum() or ch in ("_", "-"))


def make_secret_ref(kind, secret_id):
    kind = str(kind or "").strip()
    secret_id = _normalize_secret_id(secret_id)
    if not kind or not secret_id:
        return ""
    return f"{SECRET_REF_PREFIX}{kind}:{secret_id}"


def parse_secret_ref(value, expected_kind=None):
    text = "" if value is None else str(value).strip()
    if not text.startswith(SECRET_REF_PREFIX):
        return ""
    rest = text[len(SECRET_REF_PREFIX):]
    kind, sep, secret_id = rest.partition(":")
    if not sep:
        return ""
    if expected_kind and kind != expected_kind:
        return ""
    return _normalize_secret_id(secret_id)


def _generate_secret_id(kind):
    safe_kind = "".join(ch for ch in str(kind or "key") if ch.isalnum() or ch in ("_", "-")) or "key"
    return f"{safe_kind}_{uuid.uuid4().hex}"


def _secret_records(config):
    records = config.get("key_secrets", {})
    if not isinstance(records, dict):
        records = {}
        config["key_secrets"] = records
    return records


def get_secret_record(secret_id):
    secret_id = _normalize_secret_id(secret_id)
    if not secret_id:
        return {}
    config = get_config()
    records = _secret_records(config)
    record = records.get(secret_id, {})
    return record if isinstance(record, dict) else {}


def save_secret_record(secret_id, **updates):
    secret_id = _normalize_secret_id(secret_id)
    if not secret_id:
        return ""
    config = get_config()
    records = _secret_records(config)
    current = records.get(secret_id, {})
    if not isinstance(current, dict):
        current = {}
    for key, value in updates.items():
        if value is None:
            current.pop(key, None)
        else:
            current[key] = value
    if current:
        records[secret_id] = current
    else:
        records.pop(secret_id, None)
    config["key_secrets"] = records
    save_config(config)
    return secret_id


def get_node_settings(node_id):
    normalized = _normalize_node_id(node_id)
    if not normalized:
        return {}
    config = get_config()
    node_settings = config.get("node_settings", {})
    settings = node_settings.get(normalized, {})
    return settings if isinstance(settings, dict) else {}


def save_node_settings(node_id, **updates):
    normalized = _normalize_node_id(node_id)
    if not normalized:
        return
    config = get_config()
    node_settings = config.get("node_settings", {})
    current = node_settings.get(normalized, {})
    if not isinstance(current, dict):
        current = {}
    for key, value in updates.items():
        if value is None:
            current.pop(key, None)
        else:
            if isinstance(value, str) and value.strip().lower() in ("none", "null"):
                current.pop(key, None)
            else:
                current[key] = value
    if current:
        node_settings[normalized] = current
    else:
        node_settings.pop(normalized, None)
    config["node_settings"] = node_settings
    save_config(config)


def get_or_create_node_secret_id(node_id, kind, secret_id=None):
    normalized = _normalize_node_id(node_id)
    hinted_secret_id = parse_secret_ref(secret_id, kind) or _normalize_secret_id(secret_id)
    existing_secret_id = ""
    settings = get_node_settings(normalized)
    if normalized:
        secret_ids = settings.get("secret_ids", {})
        if isinstance(secret_ids, dict):
            existing_secret_id = _normalize_secret_id(secret_ids.get(kind, ""))

    if hinted_secret_id:
        if existing_secret_id and existing_secret_id != hinted_secret_id:
            secret_id = hinted_secret_id
        elif existing_secret_id:
            secret_id = existing_secret_id
        else:
            source = get_secret_record(hinted_secret_id)
            if normalized and source:
                secret_id = _generate_secret_id(kind)
                save_secret_record(secret_id, **source)
            else:
                secret_id = hinted_secret_id
    elif existing_secret_id:
        secret_id = existing_secret_id
    else:
        secret_id = _generate_secret_id(kind)

    if normalized:
        secret_ids = settings.get("secret_ids", {})
        if not isinstance(secret_ids, dict):
            secret_ids = {}
        if secret_ids.get(kind) != secret_id:
            secret_ids[kind] = secret_id
            save_node_settings(normalized, secret_ids=secret_ids)
    return secret_id


def get_secret_api_key(secret_ref_or_id, kind=SECRET_KIND_API_KEY):
    secret_id = parse_secret_ref(secret_ref_or_id, kind) or _normalize_secret_id(secret_ref_or_id)
    if not secret_id:
        return ""
    api_key = get_secret_record(secret_id).get("api_key", "")
    if isinstance(api_key, str) and api_key.strip() and api_key.strip().lower() not in ("none", "null"):
        return api_key.strip()
    return ""


def save_secret_api_key(node_id, api_key, kind=SECRET_KIND_API_KEY, secret_id=None):
    secret_id = get_or_create_node_secret_id(node_id, kind, secret_id)
    api_key = "" if api_key is None else str(api_key).strip()
    if api_key and api_key.lower() not in ("none", "null"):
        save_secret_record(secret_id, kind=kind, api_key=api_key)
    else:
        save_secret_record(secret_id, api_key=None)
    return secret_id


def get_secret_api_pool_keys(secret_ref_or_id):
    secret_id = parse_secret_ref(secret_ref_or_id, SECRET_KIND_API_POOL) or _normalize_secret_id(secret_ref_or_id)
    if not secret_id:
        return []
    api_keys = get_secret_record(secret_id).get("api_pool_keys", [])
    if not isinstance(api_keys, list):
        return []
    return [str(key or "") for key in api_keys[:8]]


def save_secret_api_pool_keys(node_id, api_keys, secret_id=None):
    secret_id = get_or_create_node_secret_id(node_id, SECRET_KIND_API_POOL, secret_id)
    if not isinstance(api_keys, list):
        api_keys = []
    normalized = [str(key or "").strip() for key in api_keys[:8]]
    while len(normalized) < 8:
        normalized.append("")
    save_secret_record(
        secret_id,
        kind=SECRET_KIND_API_POOL,
        api_pool_keys=normalized if any(normalized) else None,
    )
    return secret_id


def get_node_api_key(node_id, secret_ref_or_id=None, kind=SECRET_KIND_API_KEY):
    api_key = get_secret_api_key(secret_ref_or_id, kind)
    if api_key:
        return api_key
    settings = get_node_settings(node_id)
    secret_ids = settings.get("secret_ids", {})
    if isinstance(secret_ids, dict):
        api_key = get_secret_api_key(secret_ids.get(kind, ""), kind)
        if api_key:
            return api_key
    if kind != SECRET_KIND_API_KEY:
        return ""
    api_key = settings.get("api_key", "")
    if isinstance(api_key, str) and api_key.strip() and api_key.strip().lower() not in ("none", "null", ""):
        return api_key
    return ""


def get_node_api_pool_keys(node_id, secret_ref_or_id=None):
    api_keys = get_secret_api_pool_keys(secret_ref_or_id)
    if any(api_keys):
        return api_keys
    settings = get_node_settings(node_id)
    secret_ids = settings.get("secret_ids", {})
    if isinstance(secret_ids, dict):
        api_keys = get_secret_api_pool_keys(secret_ids.get(SECRET_KIND_API_POOL, ""))
        if any(api_keys):
            return api_keys
    api_keys = settings.get("api_pool_keys", [])
    if not isinstance(api_keys, list):
        return []
    return [str(key or "") for key in api_keys[:8]]


def save_node_api_pool_keys(node_id, api_keys):
    if not isinstance(api_keys, list):
        api_keys = []
    normalized = [str(key or "").strip() for key in api_keys[:8]]
    while len(normalized) < 8:
        normalized.append("")
    save_node_settings(node_id, api_pool_keys=normalized if any(normalized) else None)


__all__ = [
    "CONFIG_FILE",
    "CONFIG_EXAMPLE_FILE",
    "LEGACY_CONFIG_FILE",
    "SECRET_REF_PREFIX",
    "SECRET_KIND_API_KEY",
    "SECRET_KIND_API_POOL",
    "SECRET_KIND_QWEN3VL",
    "get_config",
    "save_config",
    "make_secret_ref",
    "parse_secret_ref",
    "get_secret_record",
    "save_secret_record",
    "get_node_settings",
    "save_node_settings",
    "get_or_create_node_secret_id",
    "get_secret_api_key",
    "save_secret_api_key",
    "get_secret_api_pool_keys",
    "save_secret_api_pool_keys",
    "get_node_api_key",
    "get_node_api_pool_keys",
    "save_node_api_pool_keys",
]
