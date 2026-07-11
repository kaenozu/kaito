# kaito

ZIP / RAR / 7z アーカイブ解凍・圧縮GUIツール（Windows向け）

![Python](https://img.shields.io/badge/python-3.12+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## 特徴

- ZIP / RAR / 7z 形式の解凍に対応
- ZIP / 7z 形式の作成に対応
- ドラッグ＆ドロップ対応（複数ファイル同時ドロップ）
- パスワード保護アーカイブ対応（ZIP / 7z / RAR）
- バッチ解凍（キューに追加して一括実行）
- ファイル内容プレビュー（テキスト・画像）
- ダークモード切替（System / Light / Dark）
- 設定永続化
- アーカイブ爆弾対策（サイズ・エントリ数・圧縮率の上限チェック）
- パストラバーサル対策

## 対応形式

| 形式 | 一覧表示 | 展開 | 作成 | 暗号化展開 |
|------|---------|------|------|-----------|
| ZIP  | ✅      | ✅   | ✅   | ✅        |
| RAR  | ✅      | ✅   | ❌\* | ✅        |
| 7z   | ✅      | ✅   | ✅   | ✅        |

\* RAR作成はライセンス上の制約により対応していません。

## 要件

- **OS**: Windows 10 / 11（64bit）
- RAR / 7z形式の解凍には **7-Zip** のインストールが必要です
  - [https://7-zip.org/](https://7-zip.org/) からダウンロードできます
  - ZIP形式のみの場合は不要です

## インストール

### インストーラー版（推奨）

1. [Releases](https://github.com/kaenozu/kaito/releases) から最新のインストーラーをダウンロード
2. インストーラーを実行
3. インストール後、ファイルの右クリックメニューから「kaitoで解凍」が使用可能になります

### 手動ビルド

```bash
git clone https://github.com/kaenozu/kaito.git
cd kaito
uv sync
uv run kaito
```

## 使い方

```bash
# GUIを起動
uv run kaito

# ファイルを指定して起動
uv run kaito path/to/archive.zip

# コンテキストメニュー登録（インストーラー利用時は不要）
uv run kaito --install-context-menu

# コンテキストメニュー削除
uv run kaito --uninstall-context-menu
```

### GUI操作

1. アーカイブファイルをドラッグ＆ドロップ、または「開く」ボタンで選択
2. 展開先を指定（デフォルトはアーカイブ名のサブフォルダ）
3. 「解凍する」で解凍開始
4. 複数アーカイブは順次キューに追加され、一括解凍できます

## 開発

```bash
# 依存関係をインストール
uv sync

# テストを実行
uv run pytest

# リンターを実行
uv run ruff check src/

# 型チェックを実行
uv run pyright src/

# Windows EXEビルド
uv run pyinstaller build.spec

# インストーラービルド（Inno Setup が必要）
ISCC.exe installer\kaito.iss
```

## アーキテクチャ

```
src/kaito/
  __main__.py        # CLIエントリポイント
  unzip.py           # 後方互換用ラッパー
  settings.py        # 設定管理（JSON保存 + スキーマ検証）
  domain/
    models.py        # ドメインモデル（ArchiveEntry, ArchiveInfo）
    errors.py        # 例外定義（ArchiveError, UnsafeArchiveError 等）
  archive/
    service.py       # アーカイブ操作サービス（統一インターフェース）
    zip_backend.py   # ZIPバックエンド（標準zipfile利用）
    sevenzip_backend.py  # 7z/RARバックエンド（7-Zip CLI利用）
  gui/
    unzip_app.py     # メインGUI（CustomTkinter）
    settings_dialog.py  # 設定ダイアログ
```

## セキュリティ

kaitoは以下のセキュリティ機構を実装しています：

- **パストラバーサル対策**: アーカイブ内の全エントリのパスを展開前に検証
- **アーカイブ爆弾対策**: エントリ数・展開サイズ・圧縮率の上限チェック
- **パスワード漏洩防止**: パスワードはメモリのみ保持、設定ファイルに保存しません
- **外部ツール**: 7-Zip CLIを利用（パスワードはコマンドライン引数で安全に渡す）

## 依存関係

| パッケージ | バージョン | ライセンス | 用途 |
|-----------|-----------|-----------|------|
| customtkinter | >=5.2.2 | MIT | GUI |
| pillow | >=12.2.0 | MIT-CMU | 画像プレビュー |
| platformdirs | >=4.10.0 | MIT | 設定ディレクトリ |
| tkinterdnd2 | >=0.4.4.1 | MIT | ドラッグ＆ドロップ |

### 外部ツール（同梱せず、ユーザーインストール）

| ツール | バージョン | ライセンス | 用途 |
|-------|-----------|-----------|------|
| 7-Zip | 25.00+ | LGPL | RAR/7zの一覧・展開・作成 |

## 既知の制限

- RAR形式の作成はサポートしていません
- RAR/7zの処理には7-Zipのインストールが必要です
- ZIP暗号化はZipCrypto/AESに対応（展開のみ）
- 巨大なアーカイブ（10GB超）は展開前に警告されます

## ライセンス

MIT License

Copyright (c) 2026 kaenozu