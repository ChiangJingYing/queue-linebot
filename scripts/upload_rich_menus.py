#!/usr/bin/env python3
"""Upload admin/user rich menus to LINE and optionally write IDs into .env.

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
- Access token can come from --token, LINE_CHANNEL_ACCESS_TOKEN, .env, or queue_config.yaml
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "queue_config.yaml"
ADMIN_JSON = ROOT / "rich_menus" / "admin_rich_menu.json"
ADMIN_PAGE2_JSON = ROOT / "rich_menus" / "admin_page2_rich_menu.json"
USER_JSON = ROOT / "rich_menus" / "user_rich_menu.json"
USER_PAGE2_JSON = ROOT / "rich_menus" / "user_page2_rich_menu.json"
MAX_IMAGE_BYTES = 1024 * 1024
USER_PAGE1_ALIAS_ID = "member-menu-page1"
USER_PAGE2_ALIAS_ID = "member-menu-page2"
ADMIN_PAGE1_ALIAS_ID = "admin-menu-page1"
ADMIN_PAGE2_ALIAS_ID = "admin-menu-page2"
MENU_ID_ENV_KEYS = {
    "admin_id": "LINE_ADMIN_RICH_MENU_ID",
    "admin_page2_id": "LINE_ADMIN_RICH_MENU_PAGE2_ID",
    "user_id": "LINE_USER_RICH_MENU_ID",
    "user_page2_id": "LINE_USER_RICH_MENU_PAGE2_ID",
}


def _load_dotenv_values(dotenv_path: Path) -> dict[str, str]:
    if not dotenv_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value and len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def _resolve_dotenv_path(config_path: Path) -> Path:
    root_dotenv = ROOT / ".env"
    if root_dotenv.exists():
        return root_dotenv
    return root_dotenv


def _load_dotenv_token(config_path: Path) -> str:
    dotenv_path = _resolve_dotenv_path(config_path)
    dotenv_values = _load_dotenv_values(dotenv_path)
    dotenv_token = dotenv_values.get("LINE_CHANNEL_ACCESS_TOKEN") or dotenv_values.get("LINE_CHANNEL_TOKEN")
    if dotenv_token:
        return dotenv_token
    return ""


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _save_yaml(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)


def load_existing_menu_ids(config_path: Path) -> dict[str, str]:
    dotenv_values = _load_dotenv_values(_resolve_dotenv_path(config_path))

    return {
        key: str(dotenv_values.get(env_key) or "")
        for key, env_key in MENU_ID_ENV_KEYS.items()
    }


def _save_dotenv_values(dotenv_path: Path, updates: dict[str, str]) -> None:
    existing_lines = []
    if dotenv_path.exists():
        existing_lines = dotenv_path.read_text(encoding="utf-8").splitlines()

    remaining_updates = dict(updates)
    written_lines: list[str] = []
    for raw_line in existing_lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw_line:
            written_lines.append(raw_line)
            continue

        key, _ = raw_line.split("=", 1)
        normalized_key = key.strip()
        if normalized_key in remaining_updates:
            written_lines.append(f"{normalized_key}={remaining_updates.pop(normalized_key)}")
        else:
            written_lines.append(raw_line)

    for key, value in remaining_updates.items():
        written_lines.append(f"{key}={value}")

    payload = "\n".join(written_lines).rstrip() + "\n"
    dotenv_path.write_text(payload, encoding="utf-8")


def resolve_final_menu_ids(existing_ids: dict[str, str], uploaded_ids: dict[str, str]) -> dict[str, str]:
    return {
        key: str(uploaded_ids.get(key) or existing_ids.get(key) or "")
        for key in MENU_ID_ENV_KEYS
    }


def _resolve_token(args_token: str | None, config_path: Path) -> str:
    if args_token:
        return args_token
    env_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or os.getenv("LINE_CHANNEL_TOKEN")
    if env_token:
        return env_token
    dotenv_token = _load_dotenv_token(config_path)
    if dotenv_token:
        return dotenv_token
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
        if exc.code == 413:
            raise RuntimeError(
                "LINE API 413 Request Entity Too Large：通常是 Rich Menu 圖片超過 1MB。"
            ) from exc
        raise RuntimeError(f"LINE API {exc.code} {exc.reason}: {detail}") from exc


def _prepare_image(image_path: Path, auto_compress: bool = False) -> tuple[Path, str]:
    """Validate image size and optionally create a compressed JPEG copy."""
    suffix = image_path.suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg"}:
        raise ValueError(f"不支援的圖片格式：{image_path}")

    size = image_path.stat().st_size
    if size <= MAX_IMAGE_BYTES:
        mime = "image/png" if suffix == ".png" else "image/jpeg"
        return image_path, mime

    if not auto_compress:
        raise ValueError(
            f"圖片過大：{image_path.name} = {size} bytes，LINE Rich Menu 圖片上限約 1MB。"
            "可先壓縮圖片，或重新執行時加上 --auto-compress。"
        )

    tmp_dir = Path(tempfile.mkdtemp(prefix="line-rich-menu-"))
    out_path = tmp_dir / f"{image_path.stem}.jpg"
    try:
        subprocess.run(
            [
                "sips",
                "-s",
                "format",
                "jpeg",
                "--setProperty",
                "formatOptions",
                "75",
                str(image_path),
                "--out",
                str(out_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("找不到 sips，無法自動壓縮圖片。請先手動壓縮到 1MB 內。") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"自動壓縮圖片失敗：{exc.stderr or exc.stdout}") from exc

    out_size = out_path.stat().st_size
    if out_size > MAX_IMAGE_BYTES:
        raise RuntimeError(
            f"自動壓縮後仍超過 1MB：{out_path.name} = {out_size} bytes。請再縮小圖片。"
        )

    return out_path, "image/jpeg"


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


def _upload_rich_menu_image(token: str, rich_menu_id: str, image_path: Path, auto_compress: bool = False) -> None:
    prepared_path, mime = _prepare_image(image_path, auto_compress=auto_compress)
    _request(
        "POST",
        f"https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content",
        token,
        prepared_path.read_bytes(),
        mime,
    )


def upload_one(token: str, json_path: Path, image_path: Path, label: str, auto_compress: bool = False) -> str:
    if not json_path.exists():
        raise FileNotFoundError(f"找不到 Rich Menu JSON：{json_path}")
    if not image_path.exists():
        raise FileNotFoundError(f"找不到 Rich Menu 圖片：{image_path}")
    rich_menu_id = _create_rich_menu(token, json_path)
    _upload_rich_menu_image(token, rich_menu_id, image_path, auto_compress=auto_compress)
    print(f"{label} rich menu 上傳成功：{rich_menu_id}")
    return rich_menu_id


def upload_page2(token: str, json_path: Path, image_path: Path, auto_compress: bool = False) -> str:
    return upload_one(token, json_path, image_path, "admin page2", auto_compress=auto_compress)


def upsert_rich_menu_alias(token: str, alias_id: str, rich_menu_id: str) -> None:
    body = json.dumps({
        "richMenuAliasId": alias_id,
        "richMenuId": rich_menu_id,
    }).encode("utf-8")
    try:
        _request(
            "POST",
            "https://api.line.me/v2/bot/richmenu/alias",
            token,
            body,
            "application/json",
        )
    except RuntimeError as exc:
        error_message = str(exc)
        if "LINE API 409" not in error_message and "conflict richmenu alias id" not in error_message:
            raise
        _request(
            "POST",
            f"https://api.line.me/v2/bot/richmenu/alias/{alias_id}",
            token,
            body,
            "application/json",
        )


def sync_rich_menu_aliases(token: str, final_ids: dict[str, str]) -> None:
    admin_page1_id = str(final_ids.get("admin_id") or "")
    admin_page2_id = str(final_ids.get("admin_page2_id") or "")
    user_page1_id = str(final_ids.get("user_id") or "")
    user_page2_id = str(final_ids.get("user_page2_id") or "")

    if admin_page1_id:
        upsert_rich_menu_alias(token, ADMIN_PAGE1_ALIAS_ID, admin_page1_id)
    else:
        print("略過 admin page1 alias 同步：缺少 admin page1 rich menu ID")
    if admin_page2_id:
        upsert_rich_menu_alias(token, ADMIN_PAGE2_ALIAS_ID, admin_page2_id)
    else:
        print("略過 admin page2 alias 同步：缺少 admin page2 rich menu ID")
    print(f"admin rich menu alias 已同步：{ADMIN_PAGE1_ALIAS_ID}, {ADMIN_PAGE2_ALIAS_ID}")

    if user_page1_id:
        upsert_rich_menu_alias(token, USER_PAGE1_ALIAS_ID, user_page1_id)
    else:
        print("略過 user page1 alias 同步：缺少 user page1 rich menu ID")
    if user_page2_id:
        upsert_rich_menu_alias(token, USER_PAGE2_ALIAS_ID, user_page2_id)
    else:
        print("略過 user page2 alias 同步：缺少 user page2 rich menu ID")
    print(f"user rich menu alias 已同步：{USER_PAGE1_ALIAS_ID}, {USER_PAGE2_ALIAS_ID}")


def maybe_write_config(
    config_path: Path,
    admin_id: str,
    user_id: str,
    admin_page2_id: str,
    user_page2_id: str = "",
) -> None:
    existing_ids = load_existing_menu_ids(config_path)
    final_ids = resolve_final_menu_ids(
        existing_ids,
        {
            "admin_id": admin_id,
            "admin_page2_id": admin_page2_id,
            "user_id": user_id,
            "user_page2_id": user_page2_id,
        },
    )
    dotenv_path = _resolve_dotenv_path(config_path)
    _save_dotenv_values(
        dotenv_path,
        {
            MENU_ID_ENV_KEYS["admin_id"]: final_ids["admin_id"],
            MENU_ID_ENV_KEYS["admin_page2_id"]: final_ids["admin_page2_id"],
            MENU_ID_ENV_KEYS["user_id"]: final_ids["user_id"],
            MENU_ID_ENV_KEYS["user_page2_id"]: final_ids["user_page2_id"],
        },
    )
    print(f"已寫入 {dotenv_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Upload admin/user LINE rich menus")
    parser.add_argument("--admin-image", required=True, help="admin page1 rich menu image path")
    parser.add_argument("--admin-page2-image", default=None, help="admin page2 rich menu image path (optional)")
    parser.add_argument("--user-image", required=True, help="user rich menu image path")
    parser.add_argument("--user-page2-image", default=None, help="user page2 rich menu image path (optional)")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="config yaml path")
    parser.add_argument("--token", default=None, help="LINE channel access token")
    parser.add_argument("--write-config", action="store_true", help="write returned menu IDs into .env")
    parser.add_argument("--auto-compress", action="store_true", help="if image is over 1MB, try compressing it to JPEG automatically with sips")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config_path = Path(args.config).resolve()
    token = _resolve_token(args.token, config_path)
    if not token:
        print("缺少 LINE access token。請用 --token、環境變數、.env，或在 queue_config.yaml 設定。", file=sys.stderr)
        return 1

    admin_image = Path(args.admin_image).resolve()
    user_image = Path(args.user_image).resolve()
    existing_ids = load_existing_menu_ids(config_path)

    try:
        admin_id = upload_one(token, ADMIN_JSON, admin_image, "admin", auto_compress=args.auto_compress)
        admin_page2_id = ""
        if args.admin_page2_image:
            admin_page2_id = upload_page2(token, ADMIN_PAGE2_JSON, Path(args.admin_page2_image).resolve(), auto_compress=args.auto_compress)
        user_id = upload_one(token, USER_JSON, user_image, "user", auto_compress=args.auto_compress)
        user_page2_id = ""
        if args.user_page2_image:
            user_page2_id = upload_one(
                token,
                USER_PAGE2_JSON,
                Path(args.user_page2_image).resolve(),
                "user page2",
                auto_compress=args.auto_compress,
            )
        final_ids = resolve_final_menu_ids(
            existing_ids,
            {
                "admin_id": admin_id,
                "admin_page2_id": admin_page2_id,
                "user_id": user_id,
                "user_page2_id": user_page2_id,
            },
        )
        sync_rich_menu_aliases(token, final_ids)
        print("\n請把下列 ID 設到設定中：")
        print(f"admin_rich_menu_id: {final_ids['admin_id']}")
        if final_ids["admin_page2_id"]:
            print(f"admin_rich_menu_page2_id: {final_ids['admin_page2_id']}")
        print(f"user_rich_menu_id: {final_ids['user_id']}")
        if final_ids["user_page2_id"]:
            print(f"user_rich_menu_page2_id: {final_ids['user_page2_id']}")
        if args.write_config:
            maybe_write_config(
                config_path,
                final_ids["admin_id"],
                final_ids["user_id"],
                final_ids["admin_page2_id"],
                user_page2_id=final_ids["user_page2_id"],
            )
    except Exception as exc:
        print(f"上傳失敗：{exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
