# 圧縮機能 + コンテキストメニュー設計

## 概要
kaito に圧縮機能（ZIP/RAR/7z）と Windows 右クリックコンテキストメニュー統合を追加する。

## アーキテクチャ

### 1. `unzip.py` — `create_archive()` 追加
- `sources: list[Path]`（圧縮対象）, `output: Path`（出力先）, `on_progress: ProgressCallback`
- ZIP: `zipfile.ZipFile` + `ZIP_DEFLATED`
- RAR/7z: `patoolib.create_archive()`
- エラー時は `RuntimeError` を送出

### 2. GUI (`unzip_app.py`) — 圧縮UI
- 「圧縮」ボタンを `bottom_frame` に追加（「解凍実行」の隣）
- クリック → `filedialog.askopenfilenames()` または `askdirectory()` で対象選択
- → `filedialog.asksaveasfilename()` で出力先 + 形式選択
- → バックグラウンドスレッドで圧縮実行 → 進捗表示
- D&D: アーカイブ未読込時のファイル/フォルダドロップ → 圧縮モード

### 3. CLI引数
- `kaito.exe <archive>` — 現行通り（解凍UI）
- `kaito.exe --compress <path>` — 圧縮UI
- `kaito.exe --install-context-menu` — コンテキストメニュー登録
- `kaito.exe --uninstall-context-menu` — コンテキストメニュー削除

### 4. コンテキストメニュー（Windows Registry）
- 登録:
  - `.zip` / `.rar` / `.7z` → "kaitoで解凍" → `kaito.exe "%1"`
  - `*` / `Directory` → "kaitoで圧縮" → `kaito.exe --compress "%1"`
- アイコン: `kaito.exe` のアイコンを各メニューに設定
- 登録・削除は同梱の `.reg` ファイル出力 または 直接Registry操作

### 5. テスト
- `create_archive()` の単体テスト（ZIPのみ）
- コンテキストメニュー登録/削除のテスト（モック）
- GUIの圧縮ボタンテスト
