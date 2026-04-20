"""FastAPI entry point for queue LINE Bot."""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from contextlib import asynccontextmanager
from hmac import compare_digest
from typing import AsyncGenerator

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from bot.handler import LineBotHandler
from config import load_config
from core.database import DatabaseManager
from core.queue_manager import QueueManager
from services.notifier import Notifier
from services.vip_service import VipService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

config = load_config()
line_bot_config = config.get("line_bot", {})

CHANNEL_SECRET = line_bot_config.get("channel_secret", "")
CHANNEL_ACCESS_TOKEN = line_bot_config.get("channel_access_token", "")
ADMIN_IDS: list[str] = line_bot_config.get("admin_ids", ["admin_xxxxx", "another_admin"])
ADMIN_RICH_MENU_ID = line_bot_config.get("admin_rich_menu_id", "")
USER_RICH_MENU_ID = line_bot_config.get("user_rich_menu_id", "")
LOCATION_OPTIONS = config.get("registration", {}).get("location_options", {"A": ["1", "2"], "B": ["1", "2"]})


db_manager: DatabaseManager | None = None
queue_manager: QueueManager | None = None
vip_service: VipService | None = None
notifier: Notifier | None = None
line_handler: LineBotHandler | None = None


class DashboardLayoutStore:
    def __init__(self, root: str | Path = "dashboard_layout") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.layout_path = self.root / "layout.json"

    def load(self) -> dict:
        if not self.layout_path.exists():
            return {"imageUrl": "", "markers": []}
        try:
            data = json.loads(self.layout_path.read_text(encoding="utf-8"))
        except Exception:
            return {"imageUrl": "", "markers": []}
        if not isinstance(data, dict):
            return {"imageUrl": "", "markers": []}
        return {
            "imageUrl": data.get("imageUrl", ""),
            "markers": data.get("markers", []),
        }

    def save(self, payload: dict) -> dict:
        layout = {
            "imageUrl": payload.get("imageUrl", ""),
            "markers": payload.get("markers", []),
        }
        self.layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
        return layout

    def save_image(self, filename: str, content: bytes) -> str:
        ext = Path(filename or "layout.png").suffix or ".png"
        stored_name = f"{uuid4().hex}{ext}"
        target = self.root / stored_name
        target.write_bytes(content)
        image_url = f"/dashboard/assets/{stored_name}"
        current = self.load()
        self.save(
            {
                "imageUrl": image_url,
                "markers": current.get("markers", []),
            }
        )
        return image_url

    def resolve_asset(self, filename: str) -> Path:
        return self.root / Path(filename).name


dashboard_layout_store = DashboardLayoutStore()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Initialize DB and services on startup."""
    global db_manager, queue_manager, vip_service, notifier, line_handler, scheduler
    from apscheduler.schedulers.background import BackgroundScheduler

    db_manager = DatabaseManager()
    notifier = Notifier(CHANNEL_SECRET, CHANNEL_ACCESS_TOKEN)
    queue_manager = QueueManager(db_manager, notifier)
    vip_service = VipService(db_manager)
    line_handler = LineBotHandler(
        channel_secret=CHANNEL_SECRET,
        channel_access_token=CHANNEL_ACCESS_TOKEN,
        queue_manager=queue_manager,
        vip_service=vip_service,
        admin_ids=ADMIN_IDS,
        admin_rich_menu_id=ADMIN_RICH_MENU_ID,
        user_rich_menu_id=USER_RICH_MENU_ID,
        location_options=LOCATION_OPTIONS,
    )

    scheduler = BackgroundScheduler()
    from scheduler import register_timeout_job
    register_timeout_job(scheduler, queue_manager, notifier)
    scheduler.start()

    logger.info("Queue system started")
    yield
    logger.info("Queue system shutting down")
    scheduler.shutdown(wait=False)


app = FastAPI(
    title="Queue System - LINE Bot",
    version="2.0.0",
    lifespan=lifespan,
)


@app.get("/")
def health_check():
    return {"status": "ok", "system": "queue-linebot"}


@app.get("/health")
def health():
    return {"status": "healthy"}


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.fromisoformat(value.replace(" ", "T"))
        except ValueError:
            return None


def _build_dashboard_payload() -> dict:
    if db_manager is None:
        raise HTTPException(status_code=500, detail="資料庫尚未初始化")

    rows = sorted(str(row) for row in LOCATION_OPTIONS.keys())
    cols = sorted({str(col) for values in LOCATION_OPTIONS.values() for col in values})

    grid: dict[str, dict[str, dict]] = {
        row: {
            col: {
                "name": "",
                "location": f"{row}-{col}",
                "status": "empty",
                "statusLabel": "空位",
            }
            for col in cols
        }
        for row in rows
    }

    active_queue = {entry.user_id for entry in db_manager.get_all_queue()}
    status_labels = {
        "empty": "空位",
        "registered": "已註冊",
        "queued": "排隊中",
        "served": "已叫號",
    }
    profiles = db_manager.get_all_user_profiles()

    blink_window = 90  # seconds after serve until blink stops
    now = datetime.now()

    for profile in profiles:
        if not profile.location or "-" not in profile.location:
            continue
        row_key, col_key = profile.location.split("-", 1)
        if row_key not in grid or col_key not in grid[row_key]:
            continue

        cell = grid[row_key][col_key]
        cell["name"] = profile.display_name
        cell["status"] = "registered"
        cell["recently_served"] = False

        if profile.user_id in active_queue:
            cell["status"] = "queued"
        else:
            latest = db_manager.get_latest_queue_entry_for_user(profile.user_id)
            latest_joined_at = _parse_timestamp(latest.join_time if latest else None)
            profile_updated_at = _parse_timestamp(profile.updated_at)
            served_after_registration = bool(
                latest
                and latest.served_time
                and not latest.cancel_time
                and latest_joined_at
                and profile_updated_at
                and latest_joined_at >= profile_updated_at
            )
            if served_after_registration:
                cell["status"] = "served"
                serve_dt = _parse_timestamp(latest.served_time)
                if serve_dt and (now - serve_dt).total_seconds() <= blink_window:
                    cell["recently_served"] = True

        cell["statusLabel"] = status_labels[cell["status"]]

    # --- stats ---
    stats = queue_manager.get_queue_stats()

    return {
        "rows": rows,
        "cols": cols,
        "grid": grid,
        "version": hashlib.md5(json.dumps({"rows": rows, "cols": cols, "grid": grid}, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
        "legend": status_labels,
        "stats": {
            "registered": stats["registered"],
            "queue": stats["queue"],
            "served": stats["served"],
        },
    }


@app.get("/dashboard/data")
def dashboard_data() -> dict:
    payload = _build_dashboard_payload()
    payload["layout"] = dashboard_layout_store.load()
    return payload


@app.post("/api/queue/reset")
def reset_queue() -> dict:
    if queue_manager is None:
        raise HTTPException(status_code=503, detail="Queue manager 尚未初始化")

    result = queue_manager.clear_all_queue()
    return {
        "status": "reset",
        "removed_count": result.get("removed_count", 0),
        "removed_users": result.get("removed_users", []),
        "cleared_profiles": result.get("cleared_profiles", 0),
        "cleared_served": result.get("cleared_served", 0),
    }


def _all_locations() -> list[str]:
    return [f"{row}-{col}" for row, cols in LOCATION_OPTIONS.items() for col in cols]


@app.get("/dashboard/layout")
def dashboard_layout() -> dict:
    return dashboard_layout_store.load()


@app.post("/dashboard/layout")
def save_dashboard_layout(payload: dict) -> dict:
    current_layout = dashboard_layout_store.load()
    markers = payload.get("markers", [])
    normalized_markers = []
    for marker in markers:
        if not isinstance(marker, dict):
            continue
        location = str(marker.get("location", "")).strip()
        if not location:
            continue
        normalized_markers.append(
            {
                "location": location,
                "x": max(0.0, min(100.0, float(marker.get("x", 0)))),
                "y": max(0.0, min(100.0, float(marker.get("y", 0)))),
                "label": str(marker.get("label", "")).strip(),
            }
        )
    return dashboard_layout_store.save({
        "imageUrl": str(payload.get("imageUrl", current_layout.get("imageUrl", ""))).strip(),
        "markers": normalized_markers,
    })


@app.post("/dashboard/layout/reset")
def reset_dashboard_layout() -> dict:
    layout = dashboard_layout_store.save({
        "imageUrl": dashboard_layout_store.load().get("imageUrl", ""),
        "markers": [],
    })
    return {"status": "reset", **layout}


@app.post("/dashboard/layout/image")
async def upload_dashboard_layout_image(file: UploadFile = File(...)) -> dict:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="圖片內容為空")
    image_url = dashboard_layout_store.save_image(file.filename or "layout.png", content)
    image_url_with_version = f"{image_url}?v={uuid4().hex}"
    layout = dashboard_layout_store.load()
    layout["imageUrl"] = image_url_with_version
    dashboard_layout_store.save(layout)
    return {"imageUrl": image_url_with_version}


@app.get("/dashboard/assets/{filename}")
def dashboard_asset(filename: str):
    target = dashboard_layout_store.resolve_asset(filename)
    if not target.exists():
        raise HTTPException(status_code=404, detail="找不到圖片")
    media_type, _ = mimetypes.guess_type(target.name)
    return FileResponse(target, media_type=media_type or "application/octet-stream")


@app.get("/dashboard/config", response_class=HTMLResponse)
def dashboard_config_page() -> str:
    layout = dashboard_layout_store.load()
    initial_layout = json.dumps(layout, ensure_ascii=False)
    locations = json.dumps(_all_locations(), ensure_ascii=False)
    return f"""
    <html>
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>版面設定</title>
        <style>
          body {{ font-family:-apple-system,BlinkMacSystemFont,sans-serif; background:#0f172a; color:#e2e8f0; padding:24px; }}
          .wrap {{ display:grid; grid-template-columns: 320px 1fr; gap:20px; }}
          .panel {{ background:#111827; border:1px solid #334155; border-radius:12px; padding:16px; }}
          .toolbar {{ display:grid; grid-template-columns: 1fr 1fr; gap:8px; margin-bottom:12px; }}
          .danger-button {{ background:#ef4444; color:white; }}
          .secondary-button {{ background:#38bdf8; color:#082f49; }}
          .stage {{ position:relative; width:100%; aspect-ratio: var(--stage-aspect-ratio, 16 / 9); background:#020617; border:1px dashed #475569; border-radius:12px; overflow:hidden; }}
          .stage-image {{ position:absolute; inset:0; width:100%; height:100%; object-fit:contain; display:block; pointer-events:none; background:none; }}
          .stage-overlay {{ position:absolute; inset:0; }}
          .marker-editor {{ position:absolute; transform:translate(-50%, -50%); background:#f8fafc; color:#0f172a; border-radius:999px; padding:6px 10px; font-size:12px; font-weight:700; cursor:pointer; user-select:none; box-shadow:0 4px 14px rgba(0,0,0,0.25); }}
          .selected-marker {{ outline:3px solid #f59e0b; }}
          input, select, button {{ width:100%; box-sizing:border-box; margin:8px 0; padding:10px 12px; border-radius:10px; border:1px solid #475569; background:#0b1220; color:#e2e8f0; }}
          button {{ cursor:pointer; background:#2563eb; border:none; font-weight:700; }}
          ul {{ padding-left:18px; }}
          #toast {{ position:fixed; right:20px; bottom:20px; background:#111827; border:1px solid #334155; padding:12px 14px; border-radius:10px; display:none; }}
        </style>
      </head>
      <body>
        <h1>版面設定</h1>
        <div class="wrap">
          <div class="panel">
            <form id="image-form">
              <label>上傳背景圖</label>
              <input type="file" id="image-file" name="file" accept="image/*" />
              <button type="submit">上傳圖片</button>
            </form>
            <label for="location-select">位置</label>
            <select id="location-select"><option value="">請選擇位置</option></select>
            <label for="label-input">標籤</label>
            <input id="label-input" placeholder="例如：座位 A / 會議室 1" />
            <div class="toolbar">
              <button id="save-layout" type="button">儲存版面</button>
              <button id="delete-marker" type="button" class="danger-button">刪除目前位置標記</button>
              <button id="reset-layout" type="button" class="danger-button">清除已放置位置</button>
              <button id="align-horizontal" type="button" class="secondary-button">水平對齊</button>
              <button id="align-vertical" type="button" class="secondary-button">垂直對齊</button>
            </div>
            <h3>未放置位置</h3>
            <ul id="unplaced-list"></ul>
            <h3>已放置位置</h3>
            <ul id="marker-list"></ul>
          </div>
          <div class="panel">
            <p>先選 location，再點圖片放置 marker。可多選後做水平 / 垂直對齊。</p>
            <div id="stage" class="stage">
              <img id="stage-image" class="stage-image" src="{layout.get("imageUrl", "")}" alt="layout" />
              <div id="stage-overlay" class="stage-overlay"></div>
            </div>
          </div>
        </div>
        <div id="toast"></div>
        <script>
          const locations = {locations};
          let layout = {initial_layout};
          let selectedLocation = '';
          let selectedLocations = new Set();
          let toastTimer = null;
          let dirty = false;

          const stage = document.getElementById('stage');
          const stageImage = document.getElementById('stage-image');
          const stageOverlay = document.getElementById('stage-overlay');
          const markerList = document.getElementById('marker-list');
          const unplacedList = document.getElementById('unplaced-list');
          const locationSelect = document.getElementById('location-select');
          const labelInput = document.getElementById('label-input');
          const toast = document.getElementById('toast');

          for (const location of locations) {{
            const option = document.createElement('option');
            option.value = location;
            option.textContent = location;
            locationSelect.appendChild(option);
          }}

          function showToast(message) {{
            toast.textContent = message;
            toast.style.display = 'block';
            if (toastTimer) clearTimeout(toastTimer);
            toastTimer = setTimeout(() => {{ toast.style.display = 'none'; }}, 1800);
          }}

          function setDirty(next) {{ dirty = next; }}

          function setLayout(nextLayout) {{
            layout = {{
              imageUrl: nextLayout.imageUrl || '',
              markers: Array.isArray(nextLayout.markers) ? nextLayout.markers : [],
            }};
          }}

          function syncStageImage() {{
            const nextSrc = layout.imageUrl || '';
            if (stageImage.getAttribute('src') !== nextSrc) {{
              stageImage.setAttribute('src', nextSrc);
            }}
            stageImage.style.display = nextSrc ? 'block' : 'none';
          }}

          function updateStageAspectRatio() {{
            if (stageImage.naturalWidth && stageImage.naturalHeight) {{
              stage.style.setProperty('--stage-aspect-ratio', `${{stageImage.naturalWidth}} / ${{stageImage.naturalHeight}}`);
            }}
          }}

          function getImagePlacementRect() {{
            const rect = stage.getBoundingClientRect();
            const naturalWidth = stageImage.naturalWidth || rect.width || 1;
            const naturalHeight = stageImage.naturalHeight || rect.height || 1;
            const containerRatio = rect.width / rect.height;
            const imageRatio = naturalWidth / naturalHeight;
            let width = rect.width;
            let height = rect.height;
            let left = 0;
            let top = 0;
            if (imageRatio > containerRatio) {{
              height = rect.width / imageRatio;
              top = (rect.height - height) / 2;
            }} else {{
              width = rect.height * imageRatio;
              left = (rect.width - width) / 2;
            }}
            return {{ left, top, width, height }};
          }}

          function refreshPlacementQueue() {{
            const placed = new Set((layout.markers || []).map((m) => m.location));
            return locations.filter((location) => !placed.has(location));
          }}

          function selectLocation(location, label = '', keepSelection = false) {{
            selectedLocation = location;
            if (!keepSelection) selectedLocations = location ? new Set([location]) : new Set();
            else if (location) selectedLocations.add(location);
            locationSelect.value = location;
            labelInput.value = label;
          }}

          function toggleSelectedLocation(location) {{
            if (selectedLocations.has(location)) selectedLocations.delete(location);
            else selectedLocations.add(location);
            selectedLocation = location;
            locationSelect.value = location;
          }}

          function renderEditor() {{
            syncStageImage();
            if (layout.imageUrl && !(stageImage.complete || (stageImage.naturalWidth && stageImage.naturalHeight))) return;
            updateStageAspectRatio();
            stageOverlay.innerHTML = '';
            markerList.innerHTML = '';
            unplacedList.innerHTML = '';
            const placementQueue = refreshPlacementQueue();
            for (const location of placementQueue) {{
              const item = document.createElement('li');
              item.textContent = location;
              unplacedList.appendChild(item);
            }}
            const imageRect = getImagePlacementRect();
            for (const marker of layout.markers || []) {{
              const el = document.createElement('div');
              el.className = 'marker-editor';
              if (selectedLocations.has(marker.location)) el.classList.add('selected-marker');
              el.dataset.location = marker.location;
              const markerLeft = imageRect.left + (marker.x / 100) * imageRect.width;
              const markerTop = imageRect.top + (marker.y / 100) * imageRect.height;
              el.style.left = `${{markerLeft}}px`;
              el.style.top = `${{markerTop}}px`;
              el.textContent = marker.label || marker.location;
              el.addEventListener('click', (event) => {{
                event.stopPropagation();
                if (event.shiftKey || event.metaKey || event.ctrlKey) toggleSelectedLocation(marker.location);
                else selectLocation(marker.location, marker.label || '');
                renderEditor();
              }});
              el.draggable = true;
              el.addEventListener('dragstart', (event) => {{
                event.dataTransfer.setData('text/plain', marker.location);
                el.style.opacity = '0.5';
              }});
              el.addEventListener('dragend', (event) => {{
                el.style.opacity = '1';
              }});
              stageOverlay.appendChild(el);
              const item = document.createElement('li');
              item.textContent = `${{marker.location}} @ (${{marker.x.toFixed(1)}}%, ${{marker.y.toFixed(1)}}%) ${{marker.label || ''}}`;
              markerList.appendChild(item);
            }}
          }}

          function updateMarkerPosition(location, x, y) {{
            layout.markers = (layout.markers || []).map((marker) => marker.location === location ? {{ ...marker, x, y }} : marker);
            setDirty(true);
          }}

          function eventToNormalizedPosition(event) {{
            const stageRect = stage.getBoundingClientRect();
            const imageRect = getImagePlacementRect();
            const x = ((event.clientX - stageRect.left - imageRect.left) / imageRect.width) * 100;
            const y = ((event.clientY - stageRect.top - imageRect.top) / imageRect.height) * 100;
            return {{ x: Math.max(0, Math.min(100, x)), y: Math.max(0, Math.min(100, y)) }};
          }}

          stage.addEventListener('dragover', (event) => {{ event.preventDefault(); }});

          stage.addEventListener('drop', (event) => {{
            event.preventDefault();
            const location = event.dataTransfer.getData('text/plain');
            if (!location) return;
            const pos = eventToNormalizedPosition(event);
            const marker = (layout.markers || []).find((m) => m.location === location);
            if (marker) {{
              marker.x = pos.x;
              marker.y = pos.y;
              setDirty(true);
            }} else {{
              const label = labelInput.value.trim() || location;
              layout.markers = [...(layout.markers || []), {{ location, x: pos.x, y: pos.y, label }}];
              selectLocation(location, label);
              setDirty(true);
            }}
            renderEditor();
          }});

          stage.addEventListener('click', (event) => {{
            if (event.target !== stage && event.target !== stageOverlay && event.target !== stageImage) return;
            if (layout.imageUrl && !(stageImage.complete || (stageImage.naturalWidth && stageImage.naturalHeight))) return;
            const pos = eventToNormalizedPosition(event);
            const nextLocation = refreshPlacementQueue()[0] || locationSelect.value;
            if (!nextLocation) return;
            const label = labelInput.value.trim();
            const existing = (layout.markers || []).filter((item) => item.location !== nextLocation);
            layout.markers = [...existing, {{ location: nextLocation, x: pos.x, y: pos.y, label }}];
            selectLocation(nextLocation, label);
            setDirty(true);
            renderEditor();
          }});

          document.getElementById('delete-marker').addEventListener('click', () => {{
            const targets = selectedLocations.size ? Array.from(selectedLocations) : [locationSelect.value].filter(Boolean);
            layout.markers = (layout.markers || []).filter((item) => !targets.includes(item.location));
            selectedLocations = new Set();
            setDirty(true);
            renderEditor();
          }});

          document.getElementById('reset-layout').addEventListener('click', async () => {{
            const proceed = window.confirm('這會清除目前已放置的位置標記，確定要繼續嗎？');
            if (!proceed) return;
            const response = await fetch('/dashboard/layout/reset', {{ method: 'POST' }});
            const payload = await response.json();
            setLayout(payload);
            selectedLocations = new Set();
            setDirty(false);
            renderEditor();
            showToast('已清除位置標記');
          }});

          function alignSelected(axis) {{
            const targets = (layout.markers || []).filter((item) => selectedLocations.has(item.location));
            if (targets.length < 2) {{
              showToast('請至少選兩個位置再對齊');
              return;
            }}
            const avg = targets.reduce((sum, item) => sum + (axis === 'x' ? item.x : item.y), 0) / targets.length;
            for (const marker of targets) {{
              if (axis === 'x') marker.x = avg;
              else marker.y = avg;
            }}
            setDirty(true);
            renderEditor();
          }}

          document.getElementById('align-horizontal').addEventListener('click', () => alignSelected('y'));
          document.getElementById('align-vertical').addEventListener('click', () => alignSelected('x'));

          document.getElementById('save-layout').addEventListener('click', async () => {{
            const response = await fetch('/dashboard/layout', {{
              method: 'POST',
              headers: {{ 'Content-Type': 'application/json' }},
              body: JSON.stringify(layout),
            }});
            const payload = await response.json();
            setLayout(payload);
            setDirty(false);
            renderEditor();
            showToast('儲存成功');
          }});

          document.getElementById('image-form').addEventListener('submit', async (event) => {{
            event.preventDefault();
            const fileInput = document.getElementById('image-file');
            const file = fileInput.files[0];
            if (!file) return;
            const formData = new FormData();
            formData.append('file', file);
            const response = await fetch('/dashboard/layout/image', {{ method: 'POST', body: formData }});
            const payload = await response.json();
            setLayout({{ ...layout, imageUrl: payload.imageUrl, markers: [] }});
            selectedLocations = new Set();
            selectedLocation = '';
            syncStageImage();
            setDirty(true);
            renderEditor();
            showToast('圖片上傳成功');
          }});

          locationSelect.addEventListener('change', () => {{
            selectLocation(locationSelect.value, labelInput.value);
            renderEditor();
          }});

          stageImage.addEventListener('load', () => {{
            updateStageAspectRatio();
            renderEditor();
          }});

          window.addEventListener('resize', () => renderEditor());
          window.addEventListener('beforeunload', (event) => {{
            if (!dirty) return;
            event.preventDefault();
            event.returnValue = '';
          }});

          syncStageImage();
          renderEditor();
        </script>
      </body>
    </html>
    """


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard() -> str:
    payload = _build_dashboard_payload()
    layout = dashboard_layout_store.load()
    initial_payload = json.dumps(payload, ensure_ascii=False)
    markers_html = []
    for marker in layout.get("markers", []):
        location = marker.get("location", "")
        row, _, col = location.partition("-")
        cell = payload.get("grid", {}).get(row, {}).get(col)
        if not cell:
            continue
        markers_html.append(
            f'<div class="marker" data-location="{location}" style="left:calc({marker.get("x", 0)}% + var(--image-left, 0px));top:calc({marker.get("y", 0)}% + var(--image-top, 0px));">'
            f'<div class="dot {cell["status"]}"></div>'
            f'<div class="tag">{marker.get("label") or location}<br>{cell.get("name") or cell.get("statusLabel")}</div>'
            f'</div>'
        )
    background_style = f'background-image:url({layout.get("imageUrl")});' if layout.get("imageUrl") else ''
    return f"""
    <html>
      <head>
        <meta charset=\"utf-8\" />
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
        <title>位置看板</title>
<style>
          body {{ font-family:-apple-system,BlinkMacSystemFont,sans-serif; background:#020617; color:#e2e8f0; padding:24px; overflow:hidden; }}
          .page {{ max-width:min(100vw - 48px, 1400px); margin:0 auto; }}
          .stats-panel {{ display:grid; grid-template-columns: repeat(3, minmax(120px, 1fr)); gap:12px; margin:0 0 16px; }}
          .stat-card {{ background:#0f172a; border:1px solid #334155; border-radius:14px; padding:14px 16px; }}
          .stat-label {{ font-size:12px; color:#94a3b8; margin-bottom:6px; }}
          .stat-value {{ font-size:28px; font-weight:800; color:#f8fafc; }}
          .legend {{ display:flex; gap:16px; margin-bottom:16px; flex-wrap:wrap; }}
          .legend span {{ display:flex; align-items:center; gap:8px; }}
          .board {{ position:relative; width:100%; max-width:min(100vw - 48px, 1400px); max-height:calc(100vh - 140px); aspect-ratio: var(--board-aspect-ratio, 16 / 9); background:#0f172a; border:1px solid #334155; border-radius:16px; overflow:hidden; margin:0 auto; }}
          .marker {{ position:absolute; transform:translate(-50%, -50%); text-align:center; }}
          .board-image {{ position:absolute; inset:0; width:100%; height:100%; object-fit:contain; }}
          .board-overlay {{ position:absolute; inset:0; }}
          .dot {{ width:18px; height:18px; border-radius:999px; margin:0 auto 6px; box-shadow:0 0 14px currentColor; display:inline-block; }}
          .lamp {{ width:18px; height:18px; border-radius:999px; display:inline-block; box-shadow:0 0 14px currentColor; }}
          .dot.empty, .lamp.empty {{ background:#64748b; color:#64748b; }} .dot.registered, .lamp.blue {{ background:#38bdf8; color:#38bdf8; }} .dot.queued, .lamp.yellow {{ background:#facc15; color:#facc15; }} .dot.served, .lamp.green {{ background:#22c55e; color:#22c55e; }}
          .blink {{ animation: blink-green 1.2s ease-in-out infinite; }}
          @keyframes blink-green {{ 0%, 100% {{ box-shadow:0 0 14px #22c55e; opacity:1; }} 50% {{ box-shadow:0 0 4px #22c55e; opacity:.35; }} }}
          .tag {{ background:rgba(15,23,42,.8); padding:6px 8px; border-radius:10px; font-size:12px; min-width:72px; }}
        </style>      </head>
      <body>
        <div class="page">
        <h1>位置看板</h1>
        <div class="stats-panel">
          <div class="stat-card"><div class="stat-label">Registered</div><div class="stat-value" id="stat-registered">{payload['stats']['registered']}</div></div>
          <div class="stat-card"><div class="stat-label">Queue</div><div class="stat-value" id="stat-queue">{payload['stats']['queue']}</div></div>
          <div class="stat-card"><div class="stat-label">Served</div><div class="stat-value" id="stat-served">{payload['stats']['served']}</div></div>
        </div>
        <div class=\"legend\">
          <span><i class=\"lamp empty\"></i> 空位</span>
          <span><i class=\"lamp blue\"></i> 已註冊</span>
          <span><i class=\"lamp yellow\"></i> 排隊中</span>
          <span><i class=\"lamp green\"></i> 已叫號</span>
        </div>
        <div id=\"board\" class=\"board\">
          <img id=\"board-image\" class=\"board-image\" src=\"{layout.get("imageUrl") or ""}\" alt=\"layout\" />
          <div id=\"board-overlay\" class=\"board-overlay\">{''.join(markers_html)}</div>
        </div>
        <script>
          let previousGrid = {{}}, currentVersion = null;
          const initialPayload = {initial_payload};
          function updateBoardAspectRatio() {{
            const board = document.getElementById('board');
            const boardImage = document.getElementById('board-image');
            if (board && boardImage && boardImage.naturalWidth && boardImage.naturalHeight) {{
              board.style.setProperty('--board-aspect-ratio', `${{boardImage.naturalWidth}} / ${{boardImage.naturalHeight}}`);
            }}
          }}
          function getImagePlacementRect(container, image) {{
            const rect = container.getBoundingClientRect();
            const naturalWidth = image.naturalWidth || rect.width || 1;
            const naturalHeight = image.naturalHeight || rect.height || 1;
            const containerRatio = rect.width / rect.height;
            const imageRatio = naturalWidth / naturalHeight;
            let width = rect.width;
            let height = rect.height;
            let left = 0;
            let top = 0;
            if (imageRatio > containerRatio) {{
              height = rect.width / imageRatio;
              top = (rect.height - height) / 2;
            }} else {{
              width = rect.height * imageRatio;
              left = (rect.width - width) / 2;
            }}
            return {{ left, top, width, height }};
          }}
          function renderMarkers(payload) {{
            previousGrid = payload.grid; currentVersion = payload.version;
            document.getElementById('stat-registered').textContent = payload.stats.registered;
            document.getElementById('stat-queue').textContent = payload.stats.queue;
            document.getElementById('stat-served').textContent = payload.stats.served;
            const board = document.getElementById('board');
            const boardImage = document.getElementById('board-image');
            const imageRect = getImagePlacementRect(board, boardImage);
            board.style.setProperty('--image-left', `${{imageRect.left}}px`);
            board.style.setProperty('--image-top', `${{imageRect.top}}px`);
            board.style.setProperty('--image-width', `${{imageRect.width}}px`);
            board.style.setProperty('--image-height', `${{imageRect.height}}px`);
            document.querySelectorAll('.marker').forEach((marker) => {{
              const location = marker.dataset.location;
              const [row, col] = location.split('-');
              const cell = payload.grid?.[row]?.[col];
              if (!cell) return;
              const dot = marker.querySelector('.dot');
              dot.className = `dot ${{cell.status}}${{cell.recently_served ? ' blink' : ''}}`;
              marker.querySelector('.tag').innerHTML = `${{location}}<br>${{cell.name || cell.statusLabel}}`;
            }});
          }}
          async function pollDashboard() {{
            const response = await fetch('/dashboard/data', {{ cache: 'no-store' }});
            const payload = await response.json();
            if (payload.version !== currentVersion) renderMarkers(payload);
          }}
          const boardImage = document.getElementById('board-image');
          if (boardImage) boardImage.addEventListener('load', () => {{ updateBoardAspectRatio(); renderMarkers(initialPayload); }});
          window.addEventListener('resize', () => renderMarkers(initialPayload));
          updateBoardAspectRatio();
          renderMarkers(initialPayload);
          setInterval(pollDashboard, 3000);
        </script>
      </body>
    </html>
    """


@app.post("/api/line/webhook")
async def webhook(request: Request):
    if line_handler is None:
        raise HTTPException(status_code=503, detail="LINE 處理器尚未初始化")

    body_bytes = await request.body()
    body = body_bytes.decode("utf-8")
    signature = request.headers.get("x-line-signature", "")

    logger.info("Received webhook: %s", signature)
    logger.info("Body: %s", body[:200])

    if CHANNEL_SECRET and not _verify_line_signature(signature, body, CHANNEL_SECRET):
        raise HTTPException(status_code=400, detail="LINE 簽章驗證失敗")

    try:
        payload = json.loads(body or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="JSON 格式錯誤") from exc

    processed_events = 0
    replies_sent = 0

    for event in payload.get("events", []):
        handler_event = _normalize_event(event)
        if handler_event is None:
            continue

        processed_events += 1
        reply_actions = line_handler.handle_event(handler_event)
        if reply_actions:
            replies_sent += _send_replies(reply_actions)

    return {
        "status": "received",
        "processed_events": processed_events,
        "replies_sent": replies_sent,
    }


@app.post("/api/line/callback")
async def callback(request: Request):
    if vip_service is None:
        raise HTTPException(status_code=503, detail="VIP 服務尚未初始化")

    body_bytes = await request.body()
    body = body_bytes.decode("utf-8")
    logger.info("Received callback: %s", body[:200])

    try:
        payload = json.loads(body or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="JSON 格式錯誤") from exc

    user_id = payload.get("userId")
    coffee_id = payload.get("coffeeId")
    amount = payload.get("amount")

    if not user_id:
        raise HTTPException(status_code=400, detail="缺少 userId")

    expected_amount = config.get("vip", {}).get("coffee_price", 60)
    if amount is not None:
        try:
            if int(amount) < int(expected_amount):
                raise HTTPException(status_code=400, detail="金額低於最低要求")
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="金額格式錯誤") from exc

    result = vip_service.record_purchase(
        user_id=user_id,
        platform="webhook",
        coffee_id=coffee_id,
        verified=True,
    )

    return {"status": "verified", **result}


def _verify_line_signature(signature: str, body: str, channel_secret: str) -> bool:
    if not signature:
        return False

    try:
        from linebot.v3.webhooks import SignatureValidator

        return SignatureValidator(channel_secret).validate(body, signature)
    except ImportError:
        try:
            import base64
            import hashlib
            import hmac

            digest = hmac.new(
                channel_secret.encode("utf-8"),
                body.encode("utf-8"),
                hashlib.sha256,
            ).digest()
            expected = base64.b64encode(digest).decode("utf-8")
            return compare_digest(expected, signature)
        except Exception:
            return False


def _normalize_event(event: dict):
    if event.get("type") != "message":
        return None

    message = event.get("message") or {}
    if message.get("type") != "text":
        return None

    source = event.get("source") or {}
    user_id = source.get("userId")
    reply_token = event.get("replyToken", "")
    if not user_id or not reply_token:
        return None

    class _Message:
        def __init__(self, text: str) -> None:
            self.type = "text"
            self.text = text

    class _Source:
        def __init__(self, user_id: str) -> None:
            self.userId = user_id

    class _Event:
        def __init__(self, text: str, user_id: str, reply_token: str) -> None:
            self.message = _Message(text)
            self.source = _Source(user_id)
            self.reply_token = reply_token
            self.replyToken = reply_token

    return _Event(message.get("text", ""), user_id, reply_token)


def _send_replies(reply_actions: list) -> int:
    if not reply_actions:
        return 0

    try:
        from linebot.v3.messaging import (
            ApiClient,
            Configuration,
            MessagingApi,
            ReplyMessageRequest,
            TextMessage,
            QuickReply,
            QuickReplyItem,
            MessageAction,
        )
    except Exception:
        logger.info("LINE SDK 無法使用或已損毀；已產生回覆動作但未送出")
        return len(reply_actions)

    if not CHANNEL_ACCESS_TOKEN:
        logger.info("LINE access token 缺失；已產生回覆動作但未送出")
        return len(reply_actions)

    sent = 0
    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

    with ApiClient(configuration) as api_client:
        messaging_api = MessagingApi(api_client)
        for action in reply_actions:
            reply_token = getattr(action, "replyToken", None)
            text = getattr(action, "text", None)
            quick_options = []
            if isinstance(action, dict):
                reply_token = action.get("replyToken", reply_token)
                text = action.get("text", text)
                quick_options = action.get("quickReply", [])

            if not reply_token or text is None:
                continue

            message = TextMessage(text=text)
            if quick_options:
                try:
                    message = TextMessage(
                        text=text,
                        quick_reply=QuickReply(
                            items=[
                                QuickReplyItem(
                                    action=MessageAction(
                                        label=(option.get("label") if isinstance(option, dict) else option),
                                        text=(option.get("text") if isinstance(option, dict) else option),
                                    )
                                )
                                for option in quick_options
                            ]
                        ),
                    )
                except Exception:
                    message = TextMessage(text=text)

            messaging_api.reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[message],
                )
            )
            sent += 1

    return sent


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
