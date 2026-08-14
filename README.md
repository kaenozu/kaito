# kaito

Windows 10/11向けのZIP・RAR・7zアーカイブ閲覧／検査／展開／作成GUIです。

![Python](https://img.shields.io/badge/python-3.12+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## 主な機能

- ZIP・RAR・7zの一覧表示と展開
- ZIP・7zの作成（RAR作成は非対応）
- AES-256暗号化ZIPと暗号化7zの作成
- 複数アーカイブのドラッグ＆ドロップとキュー処理
- パスワード保護されたZIP・RAR・7zの展開
- テキスト／画像プレビュー
- 選択したファイル・フォルダーだけを展開
- 名前検索、glob検索、画像／文書／実行ファイル／大容量／暗号化フィルター
- 展開前の安全診断（危険パス、リンク、サイズ、圧縮率、実行ファイル、二重拡張子）
- 展開せずにCRC・データ整合性を検査
- アーカイブごとのパスワード管理（メモリ内のみ）
- 単一ルートを考慮した展開先選択と、既存フォルダー衝突時の安全な別名作成
- パストラバーサル、リンク、reparse pointの拒否
- エントリ数、単一ファイルサイズ、合計展開サイズ、圧縮率の制限
- 一時ステージングへの展開と、検証後の安全な移動
- 原子的なZIP／7z作成
- 処理中のキャンセルと7-Zip子プロセスの終了
- 個人パスとパスワードを除外した診断レポートのコピー
- 7-Zip 26.02の同梱とSHA-256整合性検証

## 対応形式

| 形式 | 一覧 | 整合性検査 | 展開 | 選択展開 | 作成 | 暗号化展開 | 暗号化作成 |
|---|---:|---:|---:|---:|---:|---:|---:|
| ZIP | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ AES-256 |
| RAR | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| 7z | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ AES-256 |

RARは展開専用です。`.rar`を出力先として指定しても、ZIPへ自動変換せず明示的に拒否します。

暗号化ZIPはAES-256を使用します。古いWindows標準展開機能など、AES ZIP非対応のソフトでは開けない場合があります。

## 動作要件

- Windows 10 / 11（64-bit）
- 別途7-Zipをインストールする必要はありません

ローカルで作成したEXEは同梱した固定バージョンの7-Zipだけを使用します。同梱ファイルが欠落または改変されている場合、システムに別の7-Zipがあっても処理を続行しません。

## ローカル利用

このアプリは個人利用を前提としており、公開Releaseや自動更新サービスは使用しません。バージョンは内部開発版の`0.12.0.dev0`です（公開バージョンはありません）。更新確認機能は提供しません（公開リリースが無いため）。

```powershell
uv lock --check
uv sync --frozen
uv run pyinstaller --clean --noconfirm build.spec
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" installer\kaito.iss
```

生成物は`dist/kaito.exe`と`dist/kaito-installer-*.exe`です。インストーラーは現在のユーザーだけにインストールし、管理者権限を必須としません。

## 基本操作

1. アーカイブを開くか、ウィンドウへドラッグ＆ドロップします。
2. 「安全診断」で展開前の注意点を確認します。
3. 必要に応じて検索・カテゴリフィルターで項目を絞り込みます。
4. 全体を展開するか、一覧から複数項目を選択して「選択を解凍」を押します。
5. ダウンロードやバックアップの破損確認には「整合性検査」を使用します。

圧縮時は暗号化の有無を選べます。パスワードは確認入力付きのマスクされたダイアログで受け取り、永続保存しません。暗号化アーカイブの展開パスワードもマスクして入力します。

## 開発環境

```powershell
# 取得とロックファイル検証・依存関係の同期
git clone https://github.com/kaenozu/kaito.git
cd kaito
uv lock --check
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
.\dist\kaito.exe --archive-smoke --json

# Inno Setup 6インストーラー
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" installer\kaito.iss
```

## 診断CLI

```powershell
kaito.exe --version
kaito.exe --self-test
kaito.exe --backend-info
kaito.exe --backend-info --json
kaito.exe --archive-smoke
kaito.exe --archive-smoke --json
kaito.exe --test-archive C:\path\archive.zip
kaito.exe --test-archive C:\path\archive.zip --json
kaito.exe --diagnostics
```

診断コマンドは`--output PATH`でコンソールなしEXEからファイルへ結果を保存できます。

`--backend-info --json`は、バックエンドの取得元、実行パス、バージョン、SHA-256、整合性判定を機械可読形式で出力します。

`--diagnostics`はOS、kaito、Python、7-Zip、安全上限だけを出力し、アーカイブの完全パス、エントリ名、パスワードは含めません。

## Windows GUI受け入れ

自動化された実ウィンドウ起動スモークと、手動確認の合格基準は[`docs/GUI_ACCEPTANCE.md`](docs/GUI_ACCEPTANCE.md)に記載しています。GUI関連PRでは`GUI acceptance` workflowが対象テスト、パッケージ作成、実ウィンドウ起動、スクリーンショット取得を実行します。

## アーキテクチャ

```text
src/kaito/
  __main__.py
  unzip.py
  settings.py
  diagnostics.py
  domain/
    models.py
    errors.py
  archive/
    service.py
    safety.py
    inspection.py
    zip_backend.py
    sevenzip_backend.py
  gui/
    unzip_app.py
    productivity.py
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
- AES-256 ZIPは古い展開ソフトと互換性がない場合があります
- 既存の同名ファイルを無確認で上書きしません
- 既定の安全上限を超えるアーカイブは展開しません
- 暗号化処理中の7-Zipプロセス引数露出リスクがあります
- ローカルの未署名ビルドではSmartScreen警告が表示される場合があります

## ライセンス

kaito本体はMIT Licenseです。第三者コンポーネントにはそれぞれのライセンスが適用されます。
