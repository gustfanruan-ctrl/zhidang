"""Local sandbox infrastructure for power-map rendering.

Phase A — fully local BI mirror:

* `download_bi_resources` fetches the real BI HTML + all dependent JS/CSS once
  and writes them to ``backend/static/sandbox/`` together with a manifest of
  SHA-256 hashes.
* `verify_manifest` is called at app startup to catch drift between disk and
  manifest (logs a WARNING and continues).
* `render_sandbox_html` reads the patched HTML and substitutes ``{PLACEHOLDER}``
  with the actual session id at render time.
* `ctx_to_full_getinfo_response` materializes a `MergeContext` into the full
  BI getInfo JSON shape with every documented node/edge field present, using
  `FULL_NODE_DEFAULTS` / `FULL_EDGE_DEFAULTS` to fill blanks.

The sandbox dir maps to the in-container path mentioned in the Phase A spec
(``/app/static/sandbox/``); on the host it lives at ``backend/static/sandbox/``.
The URL prefix is ``/static/sandbox/`` (mounted by `main.py`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("zhidang.sandbox_infra")

# ─────────────────────────────────────────────────────────────
#  Paths & constants
# ─────────────────────────────────────────────────────────────

BI_BASE_URL = "https://crm.finereporthelp.com/WebReport/power_map/"
HTML_FILENAME = "powerMap_v3.13.html"

# backend/app/services/sandbox_infra.py → backend/static/sandbox/
SANDBOX_DIR: Path = Path(__file__).resolve().parents[2] / "static" / "sandbox"
MANIFEST_PATH: Path = SANDBOX_DIR / ".manifest.json"

# Resources to download. Each entry is a path relative to BI_BASE_URL *and*
# the on-disk layout we write to. Order matters only for logging.
BI_RESOURCES: list[str] = [
    HTML_FILENAME,
    "js/html2canvas.min.js",
    "js/fineui.min.js",
    "js/materials.min.js",
    "js/jquery.min.js",
    "js/x6_index.min.js",
    "js/history_index.min.js",
    "js/keyboard_index.min.js",
    "js/stencil_index.min.js",
    "js/selection_index.min.js",
    "js/clipboard_index.min.js",
    "js/snapline_index.min.js",
    "js/export_index.min.js",
    "js/transform.min.js",
    "css/fineui.min.css",
    "css/materials.min.css",
]

# Best-effort: include if upstream serves it. Iconfont assets are referenced by
# icon_font.css relative to the css/ directory; without them the page renders
# but toolbar/header icons show as boxes.
BI_OPTIONAL_RESOURCES: list[str] = [
    "css/icon_font.css",
    "css/iconfont.woff2",
    "css/iconfont.woff",
    "css/iconfont.ttf",
    "css/iconfont.svg",
]

# ─────────────────────────────────────────────────────────────
#  Full field defaults (BI getInfo shape)
# ─────────────────────────────────────────────────────────────

FULL_NODE_DEFAULTS: dict[str, Any] = {
    "id": "",
    "pid": "",
    "cont_id": "",
    "tagA": "",
    "tagB": "",
    "x": 0,
    "y": 0,
    "name": "",
    "phone": "",
    "position": "",
    "department": "",
    "information": "",
    "school": "",
    "hobby": "",
    "if_highLight": "1",
    "node_manager": "0",
    "node_reach": "0",
    "tagD_other_abbr": "",
    "tagD_other_name": "",
    "node_type": "person",
    "node_width": 0,
    "node_height": 0,
    "node_parent_dept": "",
    "node_background": "",
    "node_border_color": "",
    "tagC": "",
    "tagC_arr": "",
    "tagD": "",
    "tagD_label": "",
    "tagD_level": "",
    "attitude_arr": [],
}

FULL_EDGE_DEFAULTS: dict[str, Any] = {
    "source_id": "",
    "target_id": "",
    "source_port": "port-bottom",
    "target_port": "port-top",
    "color": "#A2B1C3",
    "edge_remark": "",
    "edge_type": "",
}

# ─────────────────────────────────────────────────────────────
#  HTML patching
# ─────────────────────────────────────────────────────────────

# Three head injections, see Phase A spec Step 2.
SESSION_PLACEHOLDER = "{PLACEHOLDER}"
_BASE_TAG = '<base href="/static/sandbox/">'
_SESSION_TAG = '<script>window.__SANDBOX_SESSION__ = "{PLACEHOLDER}";</script>'
# Forward the session id on every XHR so the page's $.ajax calls reach the mock
# routes without modifying the BI HTML's request code. setRequestHeader after
# open() is the only spot where the header can be attached for jQuery's calls.
_XHR_HOOK = """<script>
(function() {
    var origOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function(method, url) {
        origOpen.apply(this, arguments);
        try {
            if (window.__SANDBOX_SESSION__) {
                this.setRequestHeader('X-Sandbox-Session', window.__SANDBOX_SESSION__);
            }
        } catch (e) {}
    };
})();
</script>"""
_READY_OBSERVER = """<script>
window.__SANDBOX_READY__ = false;
(function() {
    var checkReady = function() {
        var svg = document.querySelector('.x6-graph-svg');
        if (svg && svg.querySelectorAll('g.x6-node').length > 0) {
            window.__SANDBOX_READY__ = true;
            window.dispatchEvent(new Event('sandbox-ready'));
            return true;
        }
        return false;
    };
    document.addEventListener('DOMContentLoaded', function() {
        if (checkReady()) return;
        var observer = new MutationObserver(function() {
            if (checkReady()) observer.disconnect();
        });
        observer.observe(document.body, { childList: true, subtree: true });
        // 8s fallback — empty graphs have no x6-node elements
        setTimeout(function() {
            window.__SANDBOX_READY__ = true;
            observer.disconnect();
        }, 8000);
    });
})();
</script>"""

_HEAD_INJECTION = "\n".join([_BASE_TAG, _SESSION_TAG, _XHR_HOOK, _READY_OBSERVER]) + "\n"

# Matches the first <script ...> or <link ...> tag (the spot we insert before).
_FIRST_HEAD_ASSET = re.compile(r"(<script\b|<link\b)", re.IGNORECASE)


def patch_html(html: str) -> str:
    """Inject sandbox <head> elements before the first <script>/<link> tag.

    Idempotent: if the markers are already present we return the input
    unchanged so re-patching is safe.
    """
    if _BASE_TAG in html:
        return html
    match = _FIRST_HEAD_ASSET.search(html)
    if not match:
        # No script/link found — inject right after <head> as a fallback.
        if "<head>" in html:
            return html.replace("<head>", "<head>\n" + _HEAD_INJECTION, 1)
        return _HEAD_INJECTION + html
    idx = match.start()
    return html[:idx] + _HEAD_INJECTION + html[idx:]


# ─────────────────────────────────────────────────────────────
#  Manifest
# ─────────────────────────────────────────────────────────────


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_manifest(entries: dict[str, dict[str, Any]]) -> None:
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def load_manifest() -> dict[str, dict[str, Any]]:
    if not MANIFEST_PATH.exists():
        return {}
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("sandbox: manifest unreadable, treating as empty")
        return {}


def verify_manifest() -> list[str]:
    """Compare every manifest entry against disk; return list of mismatch keys.

    Mismatches are logged as WARNINGS but do not raise — startup continues.
    """
    manifest = load_manifest()
    if not manifest:
        logger.warning("sandbox: manifest missing at %s — run downloader before serving", MANIFEST_PATH)
        return list(BI_RESOURCES)
    mismatches: list[str] = []
    for rel_path, meta in manifest.items():
        target = SANDBOX_DIR / rel_path
        if not target.exists():
            mismatches.append(rel_path)
            logger.warning("sandbox: manifest entry %s missing on disk", rel_path)
            continue
        data = target.read_bytes()
        actual = _sha256_bytes(data)
        expected = str(meta.get("sha256", ""))
        if expected and actual != expected:
            mismatches.append(rel_path)
            logger.warning(
                "sandbox: manifest mismatch %s (expected %s, got %s)",
                rel_path,
                expected[:12],
                actual[:12],
            )
    if not mismatches:
        logger.info("sandbox: manifest verified (%d files)", len(manifest))
    return mismatches


# ─────────────────────────────────────────────────────────────
#  Download
# ─────────────────────────────────────────────────────────────


async def _fetch_one(
    client: httpx.AsyncClient,
    rel_path: str,
    headers: dict[str, str],
    *,
    optional: bool = False,
) -> bytes | None:
    url = BI_BASE_URL + rel_path
    try:
        resp = await client.get(url, headers=headers)
    except Exception as exc:
        if optional:
            logger.info("sandbox: optional resource %s fetch failed (%s) — skipping", rel_path, exc)
            return None
        raise
    if resp.status_code == 404 and optional:
        logger.info("sandbox: optional resource %s not found upstream — skipping", rel_path)
        return None
    resp.raise_for_status()
    return resp.content


async def download_bi_resources(auth_token: str | None) -> dict[str, dict[str, Any]]:
    """Download the full BI sandbox bundle into SANDBOX_DIR.

    Returns the manifest dict that was written to ``.manifest.json``. The HTML
    file is stored already patched (so SHA-256 in the manifest covers the
    patched form). Re-running overwrites existing files in place — no rm -rf.
    """
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    (SANDBOX_DIR / "js").mkdir(exist_ok=True)
    (SANDBOX_DIR / "css").mkdir(exist_ok=True)

    headers: dict[str, str] = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    manifest: dict[str, dict[str, Any]] = {}

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True, verify=False) as client:
        for rel in BI_RESOURCES:
            data = await _fetch_one(client, rel, headers)
            if data is None:
                continue
            if rel == HTML_FILENAME:
                # Patch BEFORE writing so the manifest hash covers the patched form.
                text = data.decode("utf-8", errors="replace")
                text = patch_html(text)
                data = text.encode("utf-8")
            target = SANDBOX_DIR / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            manifest[rel] = {"sha256": _sha256_bytes(data), "size": len(data)}
            logger.info("sandbox: wrote %s (%d bytes)", rel, len(data))

        for rel in BI_OPTIONAL_RESOURCES:
            data = await _fetch_one(client, rel, headers, optional=True)
            if data is None:
                continue
            target = SANDBOX_DIR / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            manifest[rel] = {"sha256": _sha256_bytes(data), "size": len(data)}
            logger.info("sandbox: wrote optional %s (%d bytes)", rel, len(data))

    _write_manifest(manifest)
    logger.info("sandbox: manifest written with %d entries → %s", len(manifest), MANIFEST_PATH)
    return manifest


# ─────────────────────────────────────────────────────────────
#  HTML render (session_id substitution)
# ─────────────────────────────────────────────────────────────


def ensure_placeholder_assets() -> None:
    """Create empty stand-ins for assets the BI HTML references but we don't ship.

    The BI page references ``watermark/<picname>.png`` and ``iconfont.{woff2,woff,ttf}``
    relative to ``<base href="/static/sandbox/">``. Missing files produce 404 noise
    but don't crash JS; this just keeps the network panel clean.
    """
    (SANDBOX_DIR / "watermark").mkdir(parents=True, exist_ok=True)
    blank_png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
    )
    placeholders: list[tuple[Path, bytes]] = [
        (SANDBOX_DIR / "watermark" / "noauthority.png", blank_png),
        (SANDBOX_DIR / "iconfont.woff2", b""),
        (SANDBOX_DIR / "iconfont.woff", b""),
        (SANDBOX_DIR / "iconfont.ttf", b""),
    ]
    for path, content in placeholders:
        if path.exists():
            continue
        try:
            path.write_bytes(content)
        except OSError as exc:
            logger.warning("sandbox: failed to create placeholder %s: %s", path, exc)


def render_sandbox_html(session_id: str) -> str:
    """Read the patched sandbox HTML and substitute the session placeholder."""
    html_path = SANDBOX_DIR / HTML_FILENAME
    if not html_path.exists():
        raise FileNotFoundError(
            f"sandbox HTML missing at {html_path}; run download_bi_resources first"
        )
    ensure_placeholder_assets()
    text = html_path.read_text(encoding="utf-8")
    # Defensive re-patch: if file was placed manually without patching, apply now.
    if _BASE_TAG not in text:
        text = patch_html(text)
    # Defensive upgrade: earlier patch versions wrote BASE + SESSION + READY
    # without the XHR hook, so the page's $.ajax never carried the session.
    # Inject the hook immediately after the session tag if it's missing.
    if "X-Sandbox-Session" not in text:
        text = text.replace(_SESSION_TAG, _SESSION_TAG + "\n" + _XHR_HOOK, 1)
    return text.replace(SESSION_PLACEHOLDER, session_id or "")


# ─────────────────────────────────────────────────────────────
#  ctx → BI getInfo JSON (full field coverage)
# ─────────────────────────────────────────────────────────────


def _full_node_dict(node: Any) -> dict[str, Any]:
    """Materialize a PowerNode into BI getInfo's node_info shape."""
    # Import locally to avoid a circular import at module load time.
    from .power_map_service import _power_node_to_bi_info_dict

    base = dict(FULL_NODE_DEFAULTS)
    base.update(_power_node_to_bi_info_dict(node))
    # Cross-field aliases: BI consumes both `par_id` and `node_parent_dept`.
    parent_dept = base.get("node_parent_dept") or base.get("par_id") or ""
    base["node_parent_dept"] = parent_dept
    base.setdefault("par_id", parent_dept)
    return base


def _full_edge_dict(edge: dict[str, Any]) -> dict[str, Any]:
    out = dict(FULL_EDGE_DEFAULTS)
    for k, v in (edge or {}).items():
        out[k] = v
    return out


_DEFAULT_VERSION = {
    "value": "main",
    "text": "【主】默认",
    "ver_name": "【主】默认",
}


def ctx_to_full_getinfo_response(ctx: Any) -> dict[str, Any]:
    """Build a getInfo-shaped payload matching the full BI response format."""
    # version_info MUST be non-empty: BI's init reads version_arr[0].value
    # unconditionally after the lookup loop and crashes on undefined otherwise.
    ver_id = getattr(ctx, "bi_ver_info", None) or getattr(ctx, "harness_version_id", "") or ""
    prj_type = getattr(ctx, "bi_prj_type", None) or "company"

    if ver_id:
        version_info = [{"value": ver_id, "text": "当前版本", "ver_name": "当前版本"}]
    else:
        version_info = [dict(_DEFAULT_VERSION)]

    return {
        "node_info": [_full_node_dict(n) for n in getattr(ctx, "all_nodes", [])],
        "edge_info": [_full_edge_dict(e) for e in getattr(ctx, "edges", [])],
        "prj_type": prj_type,
        "version_info": version_info,
        "version_info_copy": [dict(v) for v in version_info],
        "contact_info": [],
        "owner_info": [],
        "competitor_info": [],
        "company_name": getattr(ctx, "harness_prj_id", "") or "",
        "todo_table_info": [],
        "todo_data": [],
        "picname": "",
        "is_support": False,
        "jdy_post_node": {},
        "opp_info": [],
        "his_totol_num": 0,
        "his_page_size": 0,
        "his_arr": [],
    }


# ─────────────────────────────────────────────────────────────
#  Empty / not-found response (no live session)
# ─────────────────────────────────────────────────────────────


def empty_getinfo_response(error: str = "session_not_found") -> dict[str, Any]:
    return {
        "node_info": [],
        "edge_info": [],
        "prj_type": "company",
        "version_info": [dict(_DEFAULT_VERSION)],
        "version_info_copy": [dict(_DEFAULT_VERSION)],
        "contact_info": [],
        "owner_info": [],
        "competitor_info": [],
        "company_name": "",
        "todo_table_info": [],
        "todo_data": [],
        "picname": "",
        "is_support": False,
        "jdy_post_node": {},
        "opp_info": [],
        "his_totol_num": 0,
        "his_page_size": 0,
        "his_arr": [],
        "error": error,
    }
