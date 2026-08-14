# 圧縮機能 + コンテキストメニュー設計（実装済み）

> ステータス: **実装済み**。当初計画（`unzip.py` への `create_archive()` 追加・`patoolib` 使用）は v0.10.1 で廃止され、現在はサービス層＋同梱7-Zip構成です。本稿は 2026-07-14 に現行アーキテクチャへ追従して改訂しました。

## 概要

kaito の圧縮機能（ZIP/7z の作成）と Windows 右クリックコンテキストメニュー統合の設計です。RAR は**作成非対応**（ライセンス上の制約。一覧・展開のみ）。`.rar` を出力先に指定した場合、ZIP へ自動変換せず `UnsupportedFormatError` で明示的に拒否します。

## アーキテクチャ（現行実装）

### 1. 圧縮サービス層

- `ArchiveService.create(CompressionOptions)` が形式別バックエンドへ振り分ける
- `CompressionOptions`: `sources: list[Path]` / `output_path: Path` / `compression_level` (0–9) / `password` / `on_progress`
- `.zip` → `ZipBackend.create`（`zipfile` 標準ライブラリ、`ZIP_DEFLATED`）
  - パスワード付き ZIP は `SevenZipBackend.create` へ委譲し **AES-256**（`-mem=AES256`）で作成。ZipCrypto は使用しない
- `.7z` → `SevenZipBackend.create`（同梱7-Zip CLI。パスワード時は `-mhe=on` でヘッダーも暗号化）
- **原子的作成**: 出力先ディレクトリ内の一時ファイルへ作成 → 全エントリを再読込して検証（ZIP: `_verify_archive` / 7z: `7z t`）→ `os.replace` で確定。失敗時は一時ファイルを削除し、中途半端な出力を残さない

### 2. 圧縮の安全対策

- 既存出力ファイルの**無断上書き拒否**: サービス層 `create()` と、Explorer 右クリック経由の `--compress` ガード（`_existing_context_compression_output`）の二重で担保
- リンク / reparse point の圧縮拒否（`_validate_sources` / `_iter_source_items` が再帰中も検査）
- Windows 展開で衝突する**名前重複の事前検出**（`find_duplicate_names`、大文字小文字正規化）
- 自己包含の検出（出力先が圧縮対象に含まれる場合を拒否、`check_self_contained`）
- 選択した**空フォルダーは ZIP 内に保持**（`_write_directory`）

### 3. GUI 圧縮 UI（`gui/unzip_app.py`）

- 「圧縮」ボタン、およびアーカイブ未読込時のファイル/フォルダー D&D で圧縮モードへ
- バックグラウンドスレッドで実行し、進捗表示・キャンセル・処理中終了時の競合回避に対応（`test_gui_concurrency` で担保）

### 4. CLI / エントリポイント（`__main__.py`）

- `kaito.exe <archive>` — 解凍 UI（現行通り）
- `kaito.exe --compress <path>` — 圧縮 UI。既定出力は `<stem>.zip`。**既存ファイルと衝突した場合は処理を開始せず**ネイティブメッセージで通知
- `kaito.exe --install-context-menu` / `--uninstall-context-menu` — 登録 / 削除
- 診断出力用の `--output PATH` は診断コマンド（`--version` など）でのみ有効

### 5. コンテキストメニュー（`context_menu.py`）

- `winreg` で **HKCU 直下**に登録（管理者権限不要・ユーザー単位）
- `.zip` / `.rar` / `.7z` → `Software\Classes\SystemFileAssociations\<ext>\shell\`
  - `kaito_extract`（"kaitoで解凍"）→ `kaito.exe "%1"`
  - `kaito_test`（"kaitoで整合性を検査"）→ `kaito.exe --test-archive "%1"`
- `*` / `Directory` → `...\shell\kaito_compress`（"kaitoで圧縮"）→ `kaito.exe --compress "%1"`
- アンインストールはキーを再帰削除（過去にアクセス権不足のバグがあり修正済み。履歴は CHANGELOG 参照）
- 当初計画していたメニューアイコン設定は現行実装では行わない

### 6. テスト

- `tests/test_compression_collisions.py` — 名前衝突（同一名・大文字小文字違い）と既存出力の上書き拒否
- `tests/test_entrypoint_guards.py` — `--compress` の既存出力ガード（4件）
- `tests/test_productivity_services.py` / `tests/test_integration.py` — 作成 → 一覧 → プレビュー → 展開の E2E（AES ZIP 含む）
- `tests/test_unzip_app.py` — `--install-context-menu` / `--uninstall-context-menu` のルーティング
- `tests/test_context_menu.py` — レジストリ操作のモック単体テスト（12件）: 登録キー16件（3拡張子×2アクション + 2ルート×1アクション、各 `\command` サブキー込み）/ ラベルとコマンドの書き分け / 再帰削除の順序とエラー握りつぶし / winreg 不在ガード / exe パス解決（開発・frozen・フォールバック）

**実装済み（v0.12.0 開発版以降）**: コンテキストメニュー本体（`context_menu.py` のレジストリ操作）のモック単体テストを `tests/test_context_menu.py` に実装しました（winreg をモックし実レジストリには触れません）。登録・削除ロジックは上記テストで、CLI ルーティングと CI のインストーラー E2E（`tools/test_installer.ps1`）と合わせて担保しています。

## 残課題・制約

- 暗号化 ZIP / 7z の作成パスワードは 7-Zip CLI の仕様上、プロセス引数へ渡る（kaito はログ・例外・診断から伏せる。詳細は SECURITY.md）
- RAR 作成は引き続き非対応
