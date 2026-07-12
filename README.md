# kaito

Windows 10/11向けのZIP・RAR・7zアーカイブ閲覧／展開／作成GUIです。

![Python](https://img.shields.io/badge/python-3.12+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## 主な機能

- ZIP・RAR・7zの一覧表示と展開
- ZIP・7zの作成（RAR作成は非対応）
- 複数アーカイブのドラッグ＆ドロップとキュー処理
- パスワード保護されたZIP・RAR・7zの展開
- テキスト／画像プレビュー
- アーカイブごとのパスワード管理（メモリ内のみ）
- パストラバーサル、リンク、reparse pointの拒否
- エントリ数、単一ファイルサイズ、合計展開サイズ、圧縮率の制限
- 一時ステージングへの展開と、検証後の安全な移動
- 原子的なZIP／7z作成
- 処理中のキャンセルと7-Zip子プロセスの終了
- 7-Zip 26.02の同梱とSHA-256整合性検証

## 対応形式

| 形式 | 一覧 | 展開 | 作成 | 暗号化展開 | 暗号化作成 |
|---|---:|---:|---:|---:|---:|
| ZIP | ✅ | ✅ | ✅ | ✅ | ❌ |
| RAR | ✅ | ✅ | ❌ | ✅ | ❌ |
| 7z | ✅ | ✅ | ✅ | ✅ | ✅ |

RARは展開専用です。`.rar`を出力先として指定しても、ZIPへ自動変換せず明示的に拒否します。

## 動作要件

- Windows 10 / 11（64-bit）
- 別途7-Zipをインストールする必要はありません

配布EXEは同梱した固定バージョンの7-Zipだけを使用します。同梱ファイルが欠落または改変されている場合、システムに別の7-Zipがあっても処理を続行しません。

## インストール

1. GitHub Releasesから`kaito-installer-*.exe`を取得します。
2. インストーラーを実行します。
3. `.zip`、`.rar`、`.7z`の右クリックメニューから「kaitoで解凍」を使用できます。

インストーラーは現在のユーザーだけにインストールし、管理者権限を必須としません。

## 開発環境

```powershell
# 取得と依存関係の同期
git clone https://github.com/kaenozu/kaito.git
cd kaito
uv sync --frozen

# GUI起動
uv run kaito

# 品質ゲート
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -ra

# EXE
uv run pyinstaller --clean --noconfirm build.spec
.\dist\kaito.exe --self-test
.\dist\kaito.exe --backend-info --json

# Inno Setup 6インストーラー
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" installer\kaito.iss
```

## 診断CLI

```powershell
kaito.exe --version
kaito.exe --self-test
kaito.exe --backend-info
kaito.exe --backend-info --json
```

`--backend-info --json`は、バックエンドの取得元、実行パス、バージョン、SHA-256、整合性判定を機械可読形式で出力します。

## アーキテクチャ

```text
src/kaito/
  __main__.py
  unzip.py
  settings.py
  domain/
    models.py
    errors.py
  archive/
    service.py
    safety.py
    zip_backend.py
    sevenzip_backend.py
  gui/
    unzip_app.py
    settings_dialog.py
```

GUIは`ArchiveService`を通じてバックエンドを利用します。ZIPとRAR/7zはどちらも一時ディレクトリへ展開され、展開後の実ファイルツリーを検証してから最終出力先へ移動されます。

## セキュリティ

詳細は[`SECURITY.md`](SECURITY.md)を参照してください。

重要な残存リスクとして、7-Zip CLIの仕様上、暗号化アーカイブのパスワードは処理中のプロセス引数へ渡されます。kaitoはログ、例外、診断出力からパスワードを伏せ、永続保存もしませんが、同一Windowsユーザー権限の別プロセスから引数を参照される可能性までは排除できません。

## 同梱コンポーネント

kaitoは7-Zip 26.02の`7z.exe`と`7z.dll`を同梱します。

- ハッシュ: `bundled/SHA256SUMS`
- 完全なライセンス通知: `bundled/7-ZIP-LICENSE.txt`
- 第三者コンポーネント一覧: `THIRD_PARTY_NOTICES.md`

7z.dllにはGNU LGPL、BSD 2-Clause、BSD 3-Clause、およびunRAR制限の対象コードが含まれます。RAR圧縮アルゴリズムの再実装には使用しません。

## テストデータ

RAR E2Eテストには、固定コミットのlibarchive公式テストfixtureを使用しています。出典、ライセンス、uuencode入力とデコード後RARのSHA-256は`tests/fixtures/rar/`に記録されています。fixtureはリリース成果物には含まれません。

## 既知の制限

- RAR作成には対応しません
- 暗号化ZIPの作成には対応しません
- 既存の同名ファイルを無確認で上書きしません
- 既定の安全上限を超えるアーカイブは展開しません
- 暗号化処理中の7-Zipプロセス引数露出リスクがあります

## ライセンス

kaito本体はMIT Licenseです。第三者コンポーネントにはそれぞれのライセンスが適用されます。
