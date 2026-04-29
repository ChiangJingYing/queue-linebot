from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_templates_are_extracted_from_main():
    main_source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")

    assert "return \"\"\"" not in main_source
    assert "return f\"\"\"" not in main_source
    assert "from web.dashboard_pages import" not in main_source

    templates_dir = PROJECT_ROOT / "templates"
    assert (templates_dir / "dashboard.html").exists()
    assert (templates_dir / "dashboard_config.html").exists()
    assert (templates_dir / "dashboard_login.html").exists()

    assert not (PROJECT_ROOT / "web" / "dashboard_pages.py").exists()


def test_handler_module_is_split_into_submodules():
    bot_dir = PROJECT_ROOT / "bot"

    assert (bot_dir / "handler.py").exists()
    assert (bot_dir / "handler_admin.py").exists()
    assert (bot_dir / "handler_commands.py").exists()
    assert (bot_dir / "handler_registration.py").exists()
    assert (bot_dir / "handler_support.py").exists()
