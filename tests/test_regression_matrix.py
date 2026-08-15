"""
tests/test_regression_matrix.py
統合ゲート用の読み取り回帰マトリクス

7z.dll（IInArchive/IOutArchive）ベースの読み取り置換（origin/master）と
統合する際の GO 条件を実行可能な形で保持する。マトリクスの各項目が、
実際にその振る舞いを検証するテストに結びついていることを確認する。

統合レビュー（GO 条件）:
  - normal ZIP / AES ZIP（正しい・誤った・未指定パスワード）
  - 7z（通常・暗号化・ヘッダー暗号化）/ RAR
  - 破損アーカイブ / 日本語ファイル名
  - symlink・パストラバーサル / 抽出安全上限 / preview サイズ上限
  - キャンセル / read operations の subprocess 0 回

注:
  - 抽出の「サイズ上限」（SafetyLimits → ExtractionOptions）は
    origin/master 側の #39 のスコープで、現行ローカルには未実装のため
    マトリクスには載せていない（統合時に #39 側のテストで担保される）。
  - RAR/7z の「subprocess 0 回」は現行の patool 経由では保証できず、
    DLL 置換後の検証項目として docstring にのみ記録する。
"""

import ast
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent

# (項目ID, 説明, 検証するテストのファイル::クラス::メソッド)
MATRIX: list[tuple[str, str, str]] = [
    (
        "zip.normal",
        "通常ZIPの一覧・展開",
        "test_unzip.py::TestListEntries::test_normal_zip",
    ),
    (
        "zip.aes.detect",
        "AES ZIP（flag bit6 / method 99）の暗号化検出",
        "test_unzip.py::TestAesZipBehavior::test_list_entries_detects_encrypted",
    ),
    (
        "zip.aes.extract",
        "AES ZIPの展開は明確なエラー（NotImplementedError）",
        "test_unzip.py::TestAesZipBehavior::test_extract_raises_clear_error",
    ),
    (
        "zip.password.correct",
        "暗号化ZIP・正しいパスワードで展開",
        "test_unzip.py::TestZipCryptoPasswordClassification::test_extract_with_correct_password",
    ),
    (
        "zip.password.wrong",
        "暗号化ZIP・誤パスワードは Bad password に分類",
        "test_unzip.py::TestZipCryptoPasswordClassification::test_extract_with_wrong_password_raises",
    ),
    (
        "zip.password.missing",
        "暗号化ZIP・未指定は password required に分類",
        "test_unzip.py::TestZipCryptoPasswordClassification::test_extract_without_password_raises",
    ),
    (
        "7z.normal",
        "7z 通常の一覧（patool 契約）",
        "test_unzip.py::TestRar7zPatoolContract::test_list_7z_normal",
    ),
    (
        "7z.encrypted",
        "7z パスワード付きの暗号化検出",
        "test_unzip.py::TestRar7zPatoolContract::test_list_7z_encrypted_detected",
    ),
    (
        "7z.header_encrypted",
        "7z ヘッダー暗号化の誤パスワード展開エラー",
        "test_unzip.py::TestRar7zPatoolContract::test_extract_7z_header_encrypted_wrong_password",
    ),
    (
        "rar.normal",
        "RAR 通常の展開（patool 契約）",
        "test_unzip.py::TestRar7zPatoolContract::test_extract_rar_normal",
    ),
    (
        "rar.encrypted",
        "RAR パスワード付きの暗号化検出",
        "test_unzip.py::TestListArchive::test_list_patool_password_protected",
    ),
    (
        "corrupt",
        "破損アーカイブのエラー",
        "test_unzip.py::TestListEntries::test_bad_zip",
    ),
    (
        "jp.filename",
        "日本語ファイル名（CP932）の展開",
        "test_unzip.py::TestEncodingFallback::test_extract_cp932_japanese",
    ),
    (
        "safety.path_traversal",
        "パストラバーサル（ZIP slip）の拒否",
        "test_unzip.py::TestZipSlip::test_file_traversal_rejected",
    ),
    (
        "safety.symlink",
        "symlinkエントリは通常ファイルとして展開（脱出しない）",
        "test_unzip.py::TestSymlinkAndPathSafety::test_symlink_entry_extracted_as_regular_file",
    ),
    (
        "safety.absolute",
        "絶対パスエントリの拒否",
        "test_unzip.py::TestSymlinkAndPathSafety::test_absolute_path_entry_rejected",
    ),
    (
        "safety.subprocess",
        "ZIP読み取りは subprocess を起動しない",
        "test_unzip.py::TestZipReadNoSubprocess::test_list_entries_no_subprocess",
    ),
    (
        "preview.size",
        "プレビュー読み取りのサイズ上限（超過時は読み込まない）",
        "test_unzip_app.py::TestPreviewSizeLimit::test_entry_over_limit_returns_empty",
    ),
    (
        "preview.chars",
        "プレビュー表示文字数上限（2000）",
        "test_unzip_app.py::TestDecodeText::test_truncates_to_max_chars",
    ),
    (
        "cancel.before",
        "キャンセル（開始前）",
        "test_worker.py::TestExtractWorker::test_run_cancel_before_start",
    ),
    (
        "cancel.mid",
        "キャンセル（バッチ途中）",
        "test_worker.py::TestExtractWorker::test_run_cancel_mid_batch",
    ),
]


def _test_methods(file_name: str, class_name: str) -> set[str]:
    """テストファイルから指定クラスの test_* メソッド名を AST で収集する"""
    tree = ast.parse((_ROOT / file_name).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                n.name
                for n in node.body
                if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
            }
    return set()


@pytest.mark.parametrize("entry", MATRIX, ids=[e[0] for e in MATRIX])
def test_matrix_entry_covered(entry: tuple[str, str, str]) -> None:
    """マトリクスの各項目が実際のテストに結びついている"""
    _, description, node_id = entry
    file_part, _, rest = node_id.partition("::")
    class_part, _, method = rest.partition("::")
    methods = _test_methods(file_part, class_part)
    assert method in methods, (
        f"マトリクス項目 '{node_id}' のテストが見つかりません\n"
        f"説明: {description}\n"
        f"クラス {class_part} の test_* メソッド: {sorted(methods) or '(なし)'}"
    )
