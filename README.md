# kaito

ZIP/RAR/7z 解凍GUIツール

![Python](https://img.shields.io/badge/python-3.12+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## 特徴

- ZIP / RAR / 7z 形式に対応（RAR/7z は `patool` 経由）
- ドラッグ＆ドロップ対応、複数ファイル同時ドロップ
- パスワード保護アーカイブ対応（ZIP）
- バッチ解凍（キューに追加して一括実行）
- ファイル内容プレビュー（テキスト・画像）
- ダークモード切替（System / Light / Dark）
- 設定永続化（テーマ、展開先、最近使ったファイル）
- 解凍履歴（最近使ったファイルのクイック選択）

## インストール

```bash
pip install kaito
```

またはリポジトリをクローンして:

```bash
uv sync
```

## 使い方

```bash
# GUI起動
uv run kaito

# ファイルを指定して起動
uv run kaito path/to/archive.zip
```

### GUI操作

1. ファイルをドラッグ＆ドロップ、または「参照」ボタンで選択
2. 展開先を指定（デフォルトはアーカイブ名のフォルダ）
3. 「解凍実行」で解凍開始

## 開発

```bash
# 依存関係インストール
uv sync

# テスト実行
uv run pytest --cov=src/kaito

# リンター
uv run ruff check src/

# 型チェック
uv run pyright src/
```

## ライセンス

MIT
