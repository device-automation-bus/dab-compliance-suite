# util/log_handler.py
from __future__ import annotations
from typing import Any, Dict, Optional
import os, base64, json, datetime as dt

def handle_stop_log_collection_response(
    resp: Dict[str, Any],
    results_json_path: str,
    device_id: Optional[str],
) -> str:
    """
    Minimal: take base64 JSON from response, decode -> parse -> pretty dump as-is.
    File: <results_dir>/logs/<device>-<timestamp>.json
    """
    results_root = os.path.dirname(results_json_path) or "."
    logs_dir = os.path.join(results_root, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    # pull base64 payload
    b64 = None
    la = resp.get("logArchive")
    if isinstance(la, dict):
        b64 = la.get("base64") or la.get("blob") or la.get("data")
    elif isinstance(la, str):
        b64 = la
    if not b64 and isinstance(resp.get("logs"), str):
        b64 = resp["logs"]
    if not b64:
        return "[INFO] No base64 log content found; nothing was saved."

    raw = base64.b64decode(b64, validate=True)
    obj = json.loads(raw.decode("utf-8"))  # the payload is JSON by requirement

    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_dev = "".join(c if (c.isalnum() or c in "-_.:@") else "_" for c in (device_id or "device"))
    out_path = os.path.join(logs_dir, f"{safe_dev}-{ts}.json")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

    return f"[INFO] Decoded base64 JSON log saved: {out_path} ({len(raw)} bytes)"
