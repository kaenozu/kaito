"""
src/kaito/domain/errors.py
アーカイブ操作の例外定義
関連: archive/service.py (呼び出し元), archive/zip_backend.py, archive/sevenzip_backend.py
"""

from __future__ import annotations

from typing import Optional


class ArchiveError(Exception):
    """アーカイブ操作全般の基底例外"""

    def __init__(self, message: str, *, archive_path: Optional[str] = None) -> None:
        super().__init__(message)
        self.archive_path = archive_path

    def user_message(self) -> str:
        """ユーザー向けメッセージ"""
        return str(self)


class UnsupportedFormatError(ArchiveError):
    """未対応のアーカイブ形式"""

    def __init__(self, format_name: str, archive_path: Optional[str] = None) -> None:
        super().__init__(
            f"未対応のアーカイブ形式です: {format_name}", archive_path=archive_path
        )
        self.format_name = format_name


class PasswordRequiredError(ArchiveError):
    """パスワードが必要"""

    def __init__(self, archive_path: str) -> None:
        super().__init__(
            "このアーカイブはパスワードで保護されています", archive_path=archive_path
        )


class InvalidPasswordError(ArchiveError):
    """パスワードが間違っている"""

    def __init__(self, archive_path: str) -> None:
        super().__init__("パスワードが正しくありません", archive_path=archive_path)


class UnsafeArchiveError(ArchiveError):
    """安全でないアーカイブ (パストラバーサル等)"""

    def __init__(self, reason: str, archive_path: Optional[str] = None) -> None:
        super().__init__(f"安全でないアーカイブ: {reason}", archive_path=archive_path)


class ArchiveBombError(ArchiveError):
    """アーカイブ爆弾 (異常な圧縮率・サイズ)"""

    def __init__(
        self,
        reason: str,
        archive_path: Optional[str] = None,
        limit_name: str = "",
        limit_value: int = 0,
        actual_value: int = 0,
    ) -> None:
        super().__init__(f"アーカイブ爆弾を検知: {reason}", archive_path=archive_path)
        self.limit_name = limit_name
        self.limit_value = limit_value
        self.actual_value = actual_value


class ExternalToolNotFoundError(ArchiveError):
    """外部ツール (7z等) が見つからない"""

    def __init__(
        self,
        tool_name: str,
        message: Optional[str] = None,
        archive_path: Optional[str] = None,
    ) -> None:
        if message is None:
            message = f"必要な展開エンジンが見つかりません: {tool_name}。インストールしてください。"
        super().__init__(message, archive_path=archive_path)
        self.tool_name = tool_name


class ExtractionFailedError(ArchiveError):
    """展開失敗 (一般)"""

    def __init__(self, reason: str, archive_path: Optional[str] = None) -> None:
        super().__init__(f"展開に失敗しました: {reason}", archive_path=archive_path)


class CompressionFailedError(ArchiveError):
    """圧縮失敗 (一般)"""

    def __init__(self, reason: str, archive_path: Optional[str] = None) -> None:
        super().__init__(f"圧縮に失敗しました: {reason}", archive_path=archive_path)


class CancelledError(ArchiveError):
    """ユーザーによるキャンセル"""

    def __init__(self, archive_path: Optional[str] = None) -> None:
        super().__init__("処理がキャンセルされました", archive_path=archive_path)
