# util/log_handler.py
from __future__ import annotations
from typing import Any, Dict, Optional, Union
import os, base64, json, re, datetime as dt

# ---------- internal helpers ----------

def _safe_device(dev_id: Optional[str]) -> str:
    s = dev_id or "device"
    return "".join(c if (c.isalnum() or c in "-_.:@") else "_" for c in s)

def _normalize_b64(s: str) -> str:
    s = re.sub(r"\s+", "", s or "")
    pad = (-len(s)) % 4
    if pad:
        s += "=" * pad
    return s

def _extract_b64_from_resp(resp: Dict[str, Any]) -> str:
    """
    Find base64 content from a stop-collection response.
    Supports:
      - resp["logArchive"] as str, or as {"base64"| "data" | "blob"}
      - resp["logs"] as str
    """
    la = resp.get("logArchive")
    if isinstance(la, dict):
        for k in ("base64", "data", "blob"):
            v = la.get(k)
            if isinstance(v, str) and v.strip():
                return v
    if isinstance(la, str) and la.strip():
        return la
    logs = resp.get("logs")
    if isinstance(logs, str) and logs.strip():
        return logs
    raise ValueError("No base64 log content found (logArchive/logs missing).")

def _decode_to_obj_and_raw(resp: Union[str, Dict[str, Any]]) -> tuple[Union[Dict[str, Any], list], bytes]:
    """Decode base64 JSON logs and return (parsed_json, raw_bytes)."""
    if isinstance(resp, str):
        try:
            resp = json.loads(resp)
        except Exception as e:
            raise ValueError(f"Response is not valid JSON: {e}")
    if not isinstance(resp, dict):
        raise ValueError("Response must be a JSON object.")

    b64 = _normalize_b64(_extract_b64_from_resp(resp))
    raw = base64.b64decode(b64, validate=False)
    try:
        obj = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception as e:
        raise ValueError(f"Decoded payload is not valid JSON: {e}")
    return obj, raw

# ---------- public API (decode only) ----------

def decode_stop_logs_json(resp: Union[str, Dict[str, Any]]) -> Union[Dict[str, Any], list]:
    """
    Decode the base64-encoded log payload from a stop-collection response
    and return the parsed JSON (dict or list). Does NOT write any files.
    Raises ValueError on failure.
    """
    obj, _raw = _decode_to_obj_and_raw(resp)
    return obj

# ---------- public API (optional: store prettified JSON) ----------

def save_logs_json(
    log_json: Union[Dict[str, Any], list],
    results_json_path: str,
    device_id: Optional[str],
) -> str:
    """
    Save the given log JSON (already decoded) to:
        <dir(results_json_path)>/logs/<device>-<timestamp>.json
    Returns the absolute file path.
    """
    results_root = os.path.dirname(results_json_path) or "."
    logs_dir = os.path.join(results_root, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = os.path.join(logs_dir, f"{_safe_device(device_id)}-{ts}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(log_json, f, ensure_ascii=False, indent=2)
    return os.path.abspath(out_path)

# ---------- back-compat wrapper (used elsewhere) ----------

def handle_stop_log_collection_response(
    resp: Union[Dict[str, Any], str],
    results_json_path: str,
    device_id: Optional[str],
) -> str:
    """
    Back-compat convenience: decode + save in one call and return a short message.
    """
    try:
        obj, raw = _decode_to_obj_and_raw(resp)
    except Exception as e:
        return f"[WARN] Could not decode base64 logs: {e}"
    try:
        path = save_logs_json(obj, results_json_path, device_id)
        return f"[INFO] Decoded base64 JSON log saved: {path} ({len(raw)} bytes)"
    except Exception as e:
        return f"[WARN] Could not save decoded log JSON: {e}"

from typing import Any, Optional, Sequence

def summarize_log_evidence(payload: Any, item_snippet_len: int = 160, max_keys: int = 5) -> str:
    """
    Return a concise, human-readable summary of a decoded log payload,
    without dumping full content.
      - list -> "items=42, first_item_sample={...}"
      - dict -> "keys=7, sample_keys=['a','b','c']"
      - other -> "type=str"
    """
    try:
        if isinstance(payload, list):
            count = len(payload)
            if count:
                first = payload[0]
                try:
                    import json
                    snippet = json.dumps(first, ensure_ascii=False)[:item_snippet_len]
                except Exception:
                    snippet = str(first)[:item_snippet_len]
                return f"items={count}, first_item_sample={snippet}"
            return "items=0"

        if isinstance(payload, dict):
            keys = list(payload.keys())
            # show up to max_keys keys in the summary line
            show = keys[:max_keys]
            return f"keys={len(keys)}, sample_keys={show}"

        return f"type={type(payload).__name__}"
    except Exception as e:
        return f"evidence_unavailable: {e}"


def emit_log_evidence(
    payload: Any,
    *,
    logger=None,
    sink: Optional[Sequence] = None,
    label: str = "collected_log",
    max_subkeys_per_key: int = 20,
) -> str:
    """
    Log a compact evidence summary + top-level keys and each key's subkeys.
    - Does NOT log raw payload values.
    - Writes via `logger.result(...)` if provided and appends strings to `sink`
      (e.g., your `logs` list) if provided.
    - Returns the one-line high-level summary string for use in result.response.
    """
    def _emit(line: str):
        if logger is not None:
            try:
                logger.result(line)
            except Exception:
                pass
        if sink is not None:
            try:
                sink.append(line)
            except Exception:
                pass

    # High-level one-liner
    high = summarize_log_evidence(payload)
    _emit(f"[EVIDENCE] {label}: {high}")

    # Structure details (keys & subkeys) — names only, no values
    if isinstance(payload, dict):
        keys = list(payload.keys())
        _emit(f"[EVIDENCE] top_keys: {keys}")
        for k in keys:
            v = payload.get(k)
            if isinstance(v, dict):
                sub = list(v.keys())[:max_subkeys_per_key]
                _emit(f"[EVIDENCE] {k}.subkeys ({len(sub)}): {sub}")
            elif isinstance(v, list):
                if v and isinstance(v[0], dict):
                    sub = list(v[0].keys())[:max_subkeys_per_key]
                    _emit(f"[EVIDENCE] {k}.subkeys_from_first_item ({len(sub)}): {sub}")
                else:
                    _emit(f"[EVIDENCE] {k}.subkeys: [] (list without dict items)")
            else:
                _emit(f"[EVIDENCE] {k}.subkeys: [] (non-dict/list value)")

    return high
