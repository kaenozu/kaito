"""
src/kaito/i18n.py
アプリの国際化（日本語 / 英語）

GUI の表示文字列はすべて tr() 経由で取得する。
言語は設定 (settings.json の "language" キー: "ja" / "en") から設定する。
関連: gui/unzip_app.py, gui/settings_dialog.py, settings.py
"""

from __future__ import annotations

LANGUAGES = ("ja", "en")

# {言語: {キー: 文字列}}。ja がマスターで、tr() は ja を最終フォールバックに使う。
STRINGS: dict[str, dict[str, str]] = {
    "ja": {
        # ---- メインウィンドウ (gui/unzip_app.py) ----
        "app.subtitle": "ZIP / RAR / 7z 解凍",
        "app.settings": "⚙ 設定",
        "app.archive_label": "アーカイブ",
        "app.open": "開く",
        "app.recent_files": "最近のファイル",
        "app.drop_hint": "ZIP / RAR / 7z ファイルをここにドロップ",
        "app.drop_sub": "または「開く」ボタンでファイルを選択できます",
        "app.contents": "内容:",
        "app.search_placeholder": "絞り込み...",
        "app.dest_label": "展開先:",
        "app.browse": "参照",
        "app.open_folder_on_done": "完了後にフォルダを開く",
        "app.close_on_done": "解凍後に閉じる",
        "app.status_ready": "ファイルを選択してください",
        "app.compress": "圧縮する",
        "app.extract": "解凍する",
        "app.cancel": "キャンセル",

        # ---- ツリー見出し ----
        "tree.name": "名前",
        "tree.size": "サイズ",
        "tree.compressed": "圧縮後",
        "tree.date": "更新日時",

        # ---- 設定ダイアログ (gui/settings_dialog.py) ----
        "settings.title": "設定",
        "settings.heading": "kaito の設定",
        "settings.subtitle": "使い方に合わせて外観と圧縮速度を調整できます",
        "settings.theme": "テーマ:",
        "settings.language": "言語:",
        "settings.dest_mode": "展開先:",
        "settings.fixed_dest": "固定先:",
        "settings.pick": "選択...",
        "settings.dest_hint": "アーカイブを開くたびに展開先をどう決めるか",
        "settings.compression": "圧縮速度:",
        "settings.compression_hint": "最速を選ぶと圧縮処理が軽くなります",
        "settings.save": "保存",
        "dest.archive": "アーカイブと同じフォルダー",
        "dest.last": "最後に使用したフォルダー",
        "dest.fixed": "固定フォルダー",
        "comp.fast": "最速（サイズ大）",
        "comp.normal": "標準",
        "comp.max": "高圧縮（時間長）",

        # ---- ダイアログタイトル ----
        "dialog.open_archive": "アーカイブファイルを選択",
        "dialog.choose_dest": "展開先フォルダを選択",
        "dialog.choose_fixed_dest": "固定展開先フォルダを選択",
        "dialog.compress_files": "圧縮するファイルを選択",
        "dialog.save_archive": "圧縮ファイルの保存先",
        "dialog.password": "パスワード",

        # ---- ファイルタイプ ----
        "filetype.archive": "アーカイブ",
        "filetype.all": "すべてのファイル",

        # ---- ステータス・メッセージ ----
        "msg.compress_candidates": "{n}個のファイルを圧縮できます",
        "msg.queue_status": "[{q}アーカイブ] {current}",
        "msg.error_open": "エラー: ファイルを開けません ({e})",
        "msg.warn_preview": "警告: RAR/7zのプレビューを展開できません ({e})",
        "msg.entries": "{n} 個のエントリ ({size})",
        "msg.password_protected": " (パスワード保護)",
        "msg.preview_unavailable": "プレビュー不可 ({ext})",
        "msg.preview_read_error": "プレビューを読み込めませんでした ({e})",
        "msg.preview_image_error": "画像をプレビューできません ({e})",
        "msg.canceling": "解凍をキャンセルしています...",
        "msg.canceled": "解凍をキャンセルしました ({n}アーカイブ完了)",
        "msg.error_summary": "{n}アーカイブでエラー",
        "msg.error_prefix": "エラー: {msg}",
        "msg.extract_done": "解凍完了 ({n}アーカイブ)",
        "msg.password_prompt": "{name} はパスワードで保護されています\nパスワードを入力してください:",
        "msg.compress_progress": "圧縮中: {pct} ({cur}/{total}) - {name}",
        "msg.compress_done": "圧縮完了",

        # ---- コンテキストメニュー ----
        "ctx.extract": "kaitoで解凍",
        "ctx.compress": "kaitoで圧縮",
        "ctx.installed": "コンテキストメニューを登録しました",
        "ctx.removed": "コンテキストメニューを削除しました",
    },
    "en": {
        "app.subtitle": "ZIP / RAR / 7z Extraction",
        "app.settings": "⚙ Settings",
        "app.archive_label": "Archive",
        "app.open": "Open",
        "app.recent_files": "Recent Files",
        "app.drop_hint": "Drop ZIP / RAR / 7z files here",
        "app.drop_sub": "or use the Open button to select a file",
        "app.contents": "Contents:",
        "app.search_placeholder": "Filter...",
        "app.dest_label": "Destination:",
        "app.browse": "Browse...",
        "app.open_folder_on_done": "Open folder when done",
        "app.close_on_done": "Close after extraction",
        "app.status_ready": "Select a file to get started",
        "app.compress": "Compress",
        "app.extract": "Extract",
        "app.cancel": "Cancel",

        "tree.name": "Name",
        "tree.size": "Size",
        "tree.compressed": "Compressed",
        "tree.date": "Modified",

        "settings.title": "Settings",
        "settings.heading": "kaito Settings",
        "settings.subtitle": "Adjust appearance and compression speed to your needs",
        "settings.theme": "Theme:",
        "settings.language": "Language:",
        "settings.dest_mode": "Destination:",
        "settings.fixed_dest": "Fixed path:",
        "settings.pick": "Choose...",
        "settings.dest_hint": "How to choose the destination each time you open an archive",
        "settings.compression": "Compression speed:",
        "settings.compression_hint": "Choosing Fastest makes compression lighter",
        "settings.save": "Save",
        "dest.archive": "Same folder as archive",
        "dest.last": "Last used folder",
        "dest.fixed": "Fixed folder",
        "comp.fast": "Fastest (larger size)",
        "comp.normal": "Normal",
        "comp.max": "Maximum (slower)",

        "dialog.open_archive": "Select archive file",
        "dialog.choose_dest": "Select destination folder",
        "dialog.choose_fixed_dest": "Select fixed destination folder",
        "dialog.compress_files": "Select files to compress",
        "dialog.save_archive": "Save archive as",
        "dialog.password": "Password",

        "filetype.archive": "Archives",
        "filetype.all": "All Files",

        "msg.compress_candidates": "{n} file(s) ready to compress",
        "msg.queue_status": "[{q} archive(s)] {current}",
        "msg.error_open": "Error: cannot open file ({e})",
        "msg.warn_preview": "Warning: could not extract RAR/7z preview ({e})",
        "msg.entries": "{n} entries ({size})",
        "msg.password_protected": " (password protected)",
        "msg.preview_unavailable": "Preview unavailable ({ext})",
        "msg.preview_read_error": "Could not load preview ({e})",
        "msg.preview_image_error": "Could not preview image ({e})",
        "msg.canceling": "Canceling extraction...",
        "msg.canceled": "Extraction canceled ({n} archive(s) done)",
        "msg.error_summary": "Errors in {n} archive(s)",
        "msg.error_prefix": "Error: {msg}",
        "msg.extract_done": "Extraction complete ({n} archive(s))",
        "msg.password_prompt": "{name} is password protected\nEnter the password:",
        "msg.compress_progress": "Compressing: {pct} ({cur}/{total}) - {name}",
        "msg.compress_done": "Compression complete",

        "ctx.extract": "Extract with kaito",
        "ctx.compress": "Compress with kaito",
        "ctx.installed": "Context menu registered",
        "ctx.removed": "Context menu removed",
    },
}

_current = "ja"


def set_language(lang: str) -> None:
    """現在の言語を設定する。未対応の言語は日本語にフォールバック"""
    global _current
    _current = lang if lang in LANGUAGES else "ja"


def get_language() -> str:
    """現在の言語コードを返す"""
    return _current


def tr(key: str) -> str:
    """キーに対応する現在言語の文字列を返す（欠落時は日本語、最後にキー自体）"""
    return STRINGS[_current].get(key, STRINGS["ja"].get(key, key))
