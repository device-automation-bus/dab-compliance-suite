# util/output_image_handler.py
from __future__ import annotations
from typing import Any, Dict, Optional
import os, base64, datetime as dt, re

def _ts() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")

def _safe(s: Optional[str]) -> str:
    return "".join(c if (c.isalnum() or c in "-_.:@") else "_" for c in (s or "device"))

def _normalize_b64(s: str) -> str:
    s = re.sub(r"\s+", "", s)
    pad = (-len(s)) % 4
    if pad:
        s += "=" * pad
    return s

def _from_data_uri(value: str) -> Optional[str]:
    if not isinstance(value, str):
        return None
    if value.startswith("data:image/"):
        idx = value.find(",")
        if idx != -1:
            return value[idx + 1 :]
    return None

def _pick_base64(resp: Dict[str, Any]) -> Optional[str]:
    # Exact format you shared:
    oi = resp.get("outputImage")
    if isinstance(oi, str) and oi.strip():
        return _from_data_uri(oi) or oi

    img = resp.get("image")
    if isinstance(img, dict):
        for k in ("base64", "data", "blob"):
            v = img.get(k)
            if isinstance(v, str) and v.strip():
                return _from_data_uri(v) or v

    for k in ("base64", "data", "blob", "png"):
        v = resp.get(k)
        if isinstance(v, str) and v.strip():
            return _from_data_uri(v) or v

    return None

def handle_output_image_response(
    resp: Dict[str, Any],
    results_json_path: str,
    device_id: Optional[str],
) -> str:
    """
    Minimal: extract base64 (supports data:image/*;base64,...) and save as PNG.
    File: <results_dir>/images/<device>-<timestamp>.png
    """
    b64 = _pick_base64(resp)
    if not b64:
        return "[INFO] No image content found; nothing was saved."

    try:
        png_bytes = base64.b64decode(_normalize_b64(b64), validate=False)
    except Exception as e:
        return f"[WARN] Base64 decode failed: {e}"

    results_root = os.path.dirname(results_json_path) or "."
    images_dir = os.path.join(results_root, "images")
    os.makedirs(images_dir, exist_ok=True)

    out_path = os.path.join(images_dir, f"{_safe(device_id)}-{_ts()}.png")
    try:
        with open(out_path, "wb") as f:
            f.write(png_bytes)
    except Exception as e:
        return f"[WARN] Could not write PNG: {e}"

    return f"[INFO] Image saved: {out_path} ({len(png_bytes)} bytes)"
