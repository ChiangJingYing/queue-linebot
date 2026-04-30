"""Register Discord slash commands for the DM user flow."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


DISCORD_API_BASE = "https://discord.com/api/v10"


def build_discord_command_payloads() -> list[dict]:
    commands = [
        ("menu", "顯示常用功能按鈕選單"),
        ("register", "開始設定學號與座位資料"),
        ("join", "加入一般排隊隊列"),
        ("cancel", "取消目前排隊"),
        ("status", "查看目前排隊狀態"),
        ("history", "查看個人排隊歷史"),
        ("help", "顯示 Discord 隊列指令說明"),
    ]
    return [
        {
            "name": name,
            "type": 1,
            "description": description,
            "dm_permission": True,
            "contexts": [1, 2],
            "integration_types": [1],
        }
        for name, description in commands
    ]


def register_discord_commands(*, application_id: str, bot_token: str) -> dict:
    payload = json.dumps(build_discord_command_payloads()).encode("utf-8")
    request = urllib.request.Request(
        url=f"{DISCORD_API_BASE}/applications/{application_id}/commands",
        data=payload,
        method="PUT",
        headers={
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else {"status": "ok"}


def main() -> int:
    application_id = os.getenv("DISCORD_APPLICATION_ID", "").strip()
    bot_token = os.getenv("DISCORD_BOT_TOKEN", "").strip()

    if not application_id:
        print("Missing DISCORD_APPLICATION_ID")
        return 1
    if not bot_token:
        print("Missing DISCORD_BOT_TOKEN")
        return 1

    try:
        result = register_discord_commands(application_id=application_id, bot_token=bot_token)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        print(f"Discord command registration failed: HTTP {exc.code} {detail}")
        return 1
    except urllib.error.URLError as exc:
        print(f"Discord command registration failed: {exc}")
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
