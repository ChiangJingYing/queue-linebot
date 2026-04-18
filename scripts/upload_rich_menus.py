#!/usr/bin/env python3
"""Upload admin/user rich menus to LINE and optionally write IDs into queue_config.yaml.

Usage:
  python scripts/upload_rich_menus.py \
    --admin-image assets/admin-rich-menu.png \
    --user-image assets/user-rich-menu.png \
    [--config queue_config.yaml] \
    [--token <LINE_CHANNEL_ACCESS_TOKEN>] \
    [--write-config]

Notes:
- Rich menu structure JSON is read from rich_menus/admin_rich_menu.json and rich_menus/user_rich_menu.json
- Images should match LINE rich menu requirements (typically 2500x1686)
- Access token can come from --token, LINE_CHANNEL_ACCESS_TOKEN, or queue_config.yaml
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "queue_config.yaml"
ADMIN_JSON = ROOT / "rich_menus" / "admin_rich_menu.json"
USER_JSON = ROOT / "rich_menus" / "user_rich_menu.json"


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _save_yaml(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)


def _resolve_token(args_token: str | None, config_path: Path) -> str:
    if args_token:
        return args_token
    env_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or os.getenv("LINE_CHANNEL_TOKEN")
    if env_token:
        return env_token
    config = _load_yaml(config_path)
    return str(config.get("line_bot", {}).get("channel_access_token", ""))


def _request(method: str, url: str, token: str, body: bytes, content_type: str) -> bytes:
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"LINE API {exc.code} {exc.reason}: {detail}") from exc


def _create_rich_menu(token: str, rich_menu_json: Path) -> str:
    body = rich_menu_json.read_bytes()
    resp = _request(
        "POST",
        "https://api.line.me/v2/bot/richmenu",
        token,
        body,
        "application/json",
    )
    payload = json.loads(resp.decode("utf-8"))
    return payload["richMenuId"]


def _upload_rich_menu_image(token: str, rich_menu_id: str, image_path: Path) -> None:
    suffix = image_path.suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg"}:
        raise ValueError(f"不支援的圖片格式：{image_path}")
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    _request(
        "POST",
        f"https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content",
        token,
        image_path.read_bytes(),
        mime,
    )


def upload_one(token: str, json_path: Path, image_path: Path, label: str) -> str:
    if not json_path.exists():
        raise FileNotFoundError(f"找不到 Rich Menu JSON：{json_path}")
    if not image_path.exists():
        raise FileNotFoundError(f"找不到 Rich Menu 圖片：{image_path}")
    rich_menu_id = _create_rich_menu(token, json_path)
    _upload_rich_menu_image(token, rich_menu_id, image_path)
    print(f"{label} rich menu 上傳成功：{rich_menu_id}")
    return rich_menu_id


def maybe_write_config(config_path: Path, admin_id: str, user_id: str) -> None:
    config = _load_yaml(config_path)
    config.setdefault("line_bot", {})
    config["line_bot"]["admin_rich_menu_id"] = admin_id
    config["line_bot"]["user_rich_menu_id"] = user_id
    _save_yaml(config_path, config)
    print(f"已寫入 {config_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Upload admin/user LINE rich menus")
    parser.add_argument("--admin-image", required=True, help="admin rich menu image path")
    parser.add_argument("--user-image", required=True, help="user rich menu image path")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="config yaml path")
    parser.add_argument("--token", default=None, help="LINE channel access token")
    parser.add_argument("--write-config", action="store_true", help="write returned menu IDs into config yaml")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    token = _resolve_token(args.token, config_path)
    if not token:
        print("缺少 LINE access token。請用 --token、環境變數，或在 queue_config.yaml 設定。", file=sys.stderr)
        return 1

    admin_image = Path(args.admin_image).resolve()
    user_image = Path(args.user_image).resolve()

    try:
        admin_id = upload_one(token, ADMIN_JSON, admin_image, "admin")
        user_id = upload_one(token, USER_JSON, user_image, "user")
        print("\n請把下列 ID 設到設定中：")
        print(f"admin_rich_menu_id: {admin_id}")
        print(f"user_rich_menu_id: {user_id}")
        if args.write_config:
            maybe_write_config(config_path, admin_id, user_id)
    except Exception as exc:
        print(f"上傳失敗：{exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
