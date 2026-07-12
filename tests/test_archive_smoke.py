"""配布物スモーク診断の回帰テスト。"""

from __future__ import annotations

from kaito.archive_smoke import run_archive_smoke


def test_archive_smoke_passes() -> None:
    result = run_archive_smoke()

    assert result["failed"] == 0, result["checks"]
    assert result["passed"] == 6
    assert all(check["status"] == "pass" for check in result["checks"])
