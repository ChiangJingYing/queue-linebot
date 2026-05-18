from __future__ import annotations

from pathlib import Path

import scripts.upload_rich_menus as upload_rich_menus


def test_build_parser_accepts_user_page2_image_argument():
    parser = upload_rich_menus.build_parser()

    args = parser.parse_args(
        [
            "--admin-image",
            "admin.png",
            "--user-image",
            "user-page1.png",
            "--user-page2-image",
            "user-page2.png",
        ]
    )

    assert args.user_page2_image == "user-page2.png"
    assert parser.parse_args(
        [
            "--admin-image",
            "admin.png",
            "--user-image",
            "user-page1.png",
            "--write-config",
        ]
    ).write_config is True


def test_maybe_write_config_persists_user_page2_id_to_dotenv(tmp_path, monkeypatch):
    config_path = tmp_path / "queue_config.yaml"
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "LINE_CHANNEL_TOKEN=token-123\nEXISTING_KEY=keep-me\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(upload_rich_menus, "ROOT", tmp_path)

    upload_rich_menus.maybe_write_config(
        config_path=config_path,
        admin_id="admin-page1-id",
        user_id="user-page1-id",
        admin_page2_id="admin-page2-id",
        user_page2_id="user-page2-id",
    )

    written = dotenv_path.read_text(encoding="utf-8")
    assert "LINE_CHANNEL_TOKEN=token-123" in written
    assert "EXISTING_KEY=keep-me" in written
    assert "LINE_ADMIN_RICH_MENU_ID=admin-page1-id" in written
    assert "LINE_ADMIN_RICH_MENU_PAGE2_ID=admin-page2-id" in written
    assert "LINE_USER_RICH_MENU_ID=user-page1-id" in written
    assert "LINE_USER_RICH_MENU_PAGE2_ID=user-page2-id" in written


def test_maybe_write_config_creates_root_dotenv_when_missing(tmp_path, monkeypatch):
    config_path = tmp_path / "config" / "queue_config.yaml"
    config_path.parent.mkdir()
    monkeypatch.setattr(upload_rich_menus, "ROOT", tmp_path)

    upload_rich_menus.maybe_write_config(
        config_path=config_path,
        admin_id="admin-page1-id",
        user_id="user-page1-id",
        admin_page2_id="admin-page2-id",
        user_page2_id="user-page2-id",
    )

    written = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "LINE_ADMIN_RICH_MENU_ID=admin-page1-id" in written


def test_resolve_dotenv_path_uses_repo_root_only(tmp_path, monkeypatch):
    config_path = tmp_path / "config" / "queue_config.yaml"
    config_path.parent.mkdir()
    (tmp_path / "config" / ".env").write_text("LINE_CHANNEL_TOKEN=config-token\n", encoding="utf-8")
    (tmp_path / ".env").write_text("LINE_CHANNEL_TOKEN=root-token\n", encoding="utf-8")
    monkeypatch.setattr(upload_rich_menus, "ROOT", tmp_path)

    resolved = upload_rich_menus._resolve_dotenv_path(config_path)

    assert resolved == tmp_path / ".env"


def test_resolve_token_reads_dotenv_before_config(tmp_path, monkeypatch):
    config_path = tmp_path / "queue_config.yaml"
    config_path.write_text(
        "line_bot:\n  channel_access_token: config-token\n",
        encoding="utf-8",
    )
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "LINE_CHANNEL_TOKEN=dotenv-token\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(upload_rich_menus, "ROOT", tmp_path)
    monkeypatch.delenv("LINE_CHANNEL_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("LINE_CHANNEL_TOKEN", raising=False)

    resolved = upload_rich_menus._resolve_token(None, config_path)

    assert resolved == "dotenv-token"


def test_resolve_token_prefers_explicit_env_over_dotenv(tmp_path, monkeypatch):
    config_path = tmp_path / "queue_config.yaml"
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "LINE_CHANNEL_TOKEN=dotenv-token\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(upload_rich_menus, "ROOT", tmp_path)
    monkeypatch.setenv("LINE_CHANNEL_TOKEN", "process-env-token")

    resolved = upload_rich_menus._resolve_token(None, config_path)

    assert resolved == "process-env-token"


def test_resolve_token_ignores_config_dotenv_and_uses_root_dotenv(tmp_path, monkeypatch):
    config_path = tmp_path / "config" / "queue_config.yaml"
    config_path.parent.mkdir()
    (tmp_path / "config" / ".env").write_text("LINE_CHANNEL_TOKEN=config-token\n", encoding="utf-8")
    (tmp_path / ".env").write_text("LINE_CHANNEL_TOKEN=root-token\n", encoding="utf-8")
    monkeypatch.setattr(upload_rich_menus, "ROOT", tmp_path)
    monkeypatch.delenv("LINE_CHANNEL_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("LINE_CHANNEL_TOKEN", raising=False)

    resolved = upload_rich_menus._resolve_token(None, config_path)

    assert resolved == "root-token"


def test_upsert_rich_menu_alias_falls_back_to_update_on_conflict(monkeypatch):
    calls = []

    def fake_request(method, url, token, body, content_type):
        calls.append((method, url, token, body, content_type))
        if url.endswith("/v2/bot/richmenu/alias"):
            raise RuntimeError('LINE API 400 Bad Request: {"message":"conflict richmenu alias id","details":[]}')
        return b"{}"

    monkeypatch.setattr(upload_rich_menus, "_request", fake_request)

    upload_rich_menus.upsert_rich_menu_alias("token-123", "member-menu-page1", "richmenu-123")

    assert calls[0][1] == "https://api.line.me/v2/bot/richmenu/alias"
    assert calls[1][1] == "https://api.line.me/v2/bot/richmenu/alias/member-menu-page1"


def test_maybe_write_config_keeps_existing_dotenv_values_and_updates_menu_ids(tmp_path, monkeypatch):
    config_path = tmp_path / "queue_config.yaml"
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "LINE_ADMIN_RICH_MENU_ID=old-admin-1\n"
        "LINE_ADMIN_RICH_MENU_PAGE2_ID=old-admin-2\n"
        "LINE_USER_RICH_MENU_ID=old-user-1\n"
        "LINE_USER_RICH_MENU_PAGE2_ID=old-user-2\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(upload_rich_menus, "ROOT", tmp_path)

    upload_rich_menus.maybe_write_config(
        config_path=config_path,
        admin_id="new-admin-1",
        user_id="new-user-1",
        admin_page2_id="new-admin-2",
        user_page2_id="new-user-2",
    )

    written = dotenv_path.read_text(encoding="utf-8")
    assert "LINE_ADMIN_RICH_MENU_ID=new-admin-1" in written
    assert "LINE_ADMIN_RICH_MENU_PAGE2_ID=new-admin-2" in written
    assert "LINE_USER_RICH_MENU_ID=new-user-1" in written
    assert "LINE_USER_RICH_MENU_PAGE2_ID=new-user-2" in written


def test_load_existing_menu_ids_prefers_dotenv_over_config(tmp_path, monkeypatch):
    config_path = tmp_path / "queue_config.yaml"
    config_path.write_text(
        "line_bot:\n"
        "  admin_rich_menu_id: config-admin-1\n"
        "  admin_rich_menu_page2_id: config-admin-2\n"
        "  user_rich_menu_id: config-user-1\n"
        "  user_rich_menu_page2_id: config-user-2\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "LINE_ADMIN_RICH_MENU_ID=dotenv-admin-1\n"
        "LINE_ADMIN_RICH_MENU_PAGE2_ID=dotenv-admin-2\n"
        "LINE_USER_RICH_MENU_ID=dotenv-user-1\n"
        "LINE_USER_RICH_MENU_PAGE2_ID=dotenv-user-2\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(upload_rich_menus, "ROOT", tmp_path)

    existing = upload_rich_menus.load_existing_menu_ids(config_path)

    assert existing == {
        "admin_id": "dotenv-admin-1",
        "admin_page2_id": "dotenv-admin-2",
        "user_id": "dotenv-user-1",
        "user_page2_id": "dotenv-user-2",
    }


def test_load_existing_menu_ids_ignores_yaml_fallback_when_dotenv_missing(tmp_path, monkeypatch):
    config_path = tmp_path / "queue_config.yaml"
    config_path.write_text(
        "line_bot:\n"
        "  admin_rich_menu_id: config-admin-1\n"
        "  admin_rich_menu_page2_id: config-admin-2\n"
        "  user_rich_menu_id: config-user-1\n"
        "  user_rich_menu_page2_id: config-user-2\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(upload_rich_menus, "ROOT", tmp_path)

    existing = upload_rich_menus.load_existing_menu_ids(config_path)

    assert existing == {
        "admin_id": "",
        "admin_page2_id": "",
        "user_id": "",
        "user_page2_id": "",
    }


def test_maybe_write_config_preserves_existing_page2_ids_when_new_values_missing(tmp_path, monkeypatch):
    config_path = tmp_path / "queue_config.yaml"
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "LINE_ADMIN_RICH_MENU_ID=old-admin-1\n"
        "LINE_ADMIN_RICH_MENU_PAGE2_ID=old-admin-2\n"
        "LINE_USER_RICH_MENU_ID=old-user-1\n"
        "LINE_USER_RICH_MENU_PAGE2_ID=old-user-2\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(upload_rich_menus, "ROOT", tmp_path)

    upload_rich_menus.maybe_write_config(
        config_path=config_path,
        admin_id="new-admin-1",
        user_id="new-user-1",
        admin_page2_id="",
        user_page2_id="",
    )

    written = dotenv_path.read_text(encoding="utf-8")
    assert "LINE_ADMIN_RICH_MENU_ID=new-admin-1" in written
    assert "LINE_USER_RICH_MENU_ID=new-user-1" in written
    assert "LINE_ADMIN_RICH_MENU_PAGE2_ID=old-admin-2" in written
    assert "LINE_USER_RICH_MENU_PAGE2_ID=old-user-2" in written


def test_sync_rich_menu_aliases_uses_existing_page2_ids_for_partial_upload(monkeypatch, capsys):
    calls = []

    monkeypatch.setattr(
        upload_rich_menus,
        "upsert_rich_menu_alias",
        lambda token, alias_id, rich_menu_id: calls.append((token, alias_id, rich_menu_id)),
    )

    upload_rich_menus.sync_rich_menu_aliases(
        "token-123",
        {
            "admin_id": "new-admin-1",
            "admin_page2_id": "old-admin-2",
            "user_id": "new-user-1",
            "user_page2_id": "old-user-2",
        },
    )

    assert calls == [
        ("token-123", upload_rich_menus.ADMIN_PAGE1_ALIAS_ID, "new-admin-1"),
        ("token-123", upload_rich_menus.ADMIN_PAGE2_ALIAS_ID, "old-admin-2"),
        ("token-123", upload_rich_menus.USER_PAGE1_ALIAS_ID, "new-user-1"),
        ("token-123", upload_rich_menus.USER_PAGE2_ALIAS_ID, "old-user-2"),
    ]
    output = capsys.readouterr().out
    assert "admin rich menu alias 已同步" in output
    assert "user rich menu alias 已同步" in output


def test_sync_rich_menu_aliases_skips_missing_page2_ids(monkeypatch, capsys):
    calls = []

    monkeypatch.setattr(
        upload_rich_menus,
        "upsert_rich_menu_alias",
        lambda token, alias_id, rich_menu_id: calls.append((token, alias_id, rich_menu_id)),
    )

    upload_rich_menus.sync_rich_menu_aliases(
        "token-123",
        {
            "admin_id": "new-admin-1",
            "admin_page2_id": "",
            "user_id": "new-user-1",
            "user_page2_id": "",
        },
    )

    assert calls == [
        ("token-123", upload_rich_menus.ADMIN_PAGE1_ALIAS_ID, "new-admin-1"),
        ("token-123", upload_rich_menus.USER_PAGE1_ALIAS_ID, "new-user-1"),
    ]
    output = capsys.readouterr().out
    assert "略過 admin page2 alias 同步" in output
    assert "略過 user page2 alias 同步" in output


def test_main_partial_upload_syncs_aliases_and_preserves_existing_page2_ids(tmp_path, monkeypatch):
    config_path = tmp_path / "queue_config.yaml"
    config_path.write_text("", encoding="utf-8")
    (tmp_path / ".env").write_text(
        "LINE_ADMIN_RICH_MENU_PAGE2_ID=old-admin-2\n"
        "LINE_USER_RICH_MENU_PAGE2_ID=old-user-2\n",
        encoding="utf-8",
    )
    admin_image = tmp_path / "admin.png"
    user_image = tmp_path / "user.png"
    admin_image.write_bytes(b"admin")
    user_image.write_bytes(b"user")

    monkeypatch.setattr(upload_rich_menus, "_resolve_token", lambda args_token, path: "token-123")
    monkeypatch.setattr(
        upload_rich_menus,
        "upload_one",
        lambda token, json_path, image_path, label, auto_compress=False: {
            "admin": "new-admin-1",
            "user": "new-user-1",
        }[label],
    )
    sync_payloads = []
    monkeypatch.setattr(
        upload_rich_menus,
        "sync_rich_menu_aliases",
        lambda token, final_ids: sync_payloads.append((token, dict(final_ids))),
    )
    monkeypatch.setattr(
        upload_rich_menus,
        "ROOT",
        tmp_path,
    )

    exit_code = upload_rich_menus.main(
        [
            "--config",
            str(config_path),
            "--admin-image",
            str(admin_image),
            "--user-image",
            str(user_image),
            "--write-config",
        ]
    )

    assert exit_code == 0
    assert sync_payloads == [
        (
            "token-123",
            {
                "admin_id": "new-admin-1",
                "admin_page2_id": "old-admin-2",
                "user_id": "new-user-1",
                "user_page2_id": "old-user-2",
            },
        )
    ]
    written = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "LINE_ADMIN_RICH_MENU_ID=new-admin-1" in written
    assert "LINE_USER_RICH_MENU_ID=new-user-1" in written
    assert "LINE_ADMIN_RICH_MENU_PAGE2_ID=old-admin-2" in written
    assert "LINE_USER_RICH_MENU_PAGE2_ID=old-user-2" in written
