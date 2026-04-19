from __future__ import annotations

from main import DashboardLayoutStore


def test_dashboard_layout_store_save_image_persists_image_url(tmp_path):
    store = DashboardLayoutStore(tmp_path / "dashboard_layout")

    image_url = store.save_image("layout.png", b"fake-image-bytes")
    saved = store.load()

    assert image_url.startswith("/dashboard/assets/")
    assert saved["imageUrl"] == image_url
    assert saved["markers"] == []
