from pathlib import Path


def test_live_power_map_proxy_does_not_block_iframe_save():
    source = Path("backend/app/main.py").read_text(encoding="utf-8")

    assert "forwarding live power map iframe write" in source
    assert "blocked live power map write through iframe proxy" not in source
    assert "原版权力地图页面为只读预览" not in source
