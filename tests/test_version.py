"""バージョン情報の一元化テスト。"""

from importlib.metadata import version

from kaito.__main__ import _version
from kaito.gui.unzip_app import __version__ as gui_version
from kaito.version import __version__


def test_all_runtime_versions_use_package_metadata() -> None:
    expected = version("kaito")
    assert expected == "0.12.0"
    assert __version__ == expected
    assert gui_version == expected
    assert _version() == expected
