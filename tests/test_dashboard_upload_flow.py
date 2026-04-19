from __future__ import annotations

from fastapi.testclient import TestClient

import main
from tests.test_main_and_config import _setup_runtime


def test_dashboard_config_renders_existing_markers_without_click(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    client = TestClient(main.app)
    client.post(
        '/dashboard/layout',
        json={
            'imageUrl': '/dashboard/assets/existing.png?v=1',
            'markers': [{'location': '1-1', 'x': 15, 'y': 25, 'label': 'A'}],
        },
    )

    response = client.get('/dashboard/config')

    assert response.status_code == 200
    assert 'stageImage.addEventListener(\'load\'' in response.text
    assert 'stageOverlay.appendChild(el);' in response.text
    assert 'requestAnimationFrame(() => renderEditor());' in response.text
    assert 'setTimeout(() => renderEditor(), 50);' in response.text


def test_dashboard_layout_upload_generates_distinct_asset_path_each_time(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    client = TestClient(main.app)

    r1 = client.post('/dashboard/layout/image', files={'file': ('a.png', b'pngdata-one', 'image/png')})
    r2 = client.post('/dashboard/layout/image', files={'file': ('a.png', b'pngdata-two', 'image/png')})

    assert r1.status_code == 200
    assert r2.status_code == 200
    url1 = r1.json()['imageUrl']
    url2 = r2.json()['imageUrl']
    assert url1 != url2
    assert url1.split('?', 1)[0] != url2.split('?', 1)[0]
