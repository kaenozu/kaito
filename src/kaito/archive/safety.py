"""
src/kaito/archive/safety.py
アーカイブ安全性検証 (パストラバーサル, アーカイブ爆弾等)
関連: domain/models.py (検証処理を委譲)
"""

# domain/models.py から検証関数を再エクスポート
from kaito.domain.models import (
    check_archive_safety,
    validate_entry_path,
    SafetyLimits as SafetyLimits,
)

__all__ = [
    "check_archive_safety",
    "validate_entry_path",
    "SafetyLimits",
]
