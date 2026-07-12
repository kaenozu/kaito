# Windows実機受け入れ補助スクリプト

この文書は、`docs/WINDOWS_ACCEPTANCE_TEST.md`の手作業を置き換えるものではありません。成果物検証、テストデータ生成、環境採取、終了後クリーンアップ判定を再現可能にする補助手順です。

## 前提

- Windows 10またはWindows 11
- `feature/archive-redesign`をcheckoutしたリポジトリ
- GitHub Actionsの同一runから取得した`kaito-windows-verification` artifact
- PowerShell 7またはWindows PowerShell 5.1
- `uv`またはPython

CI runnerは管理者グループのアカウントです。CIでcurrent-userインストールは検証していますが、標準ユーザーアカウントで昇格なしにインストールできることは実機で別途確認してください。

## 1. artifactを展開する

空のディレクトリへ展開します。別runの成果物を混在させないでください。

```powershell
$ArtifactRoot = Join-Path $env:USERPROFILE 'Desktop\kaito-acceptance-artifact'
$WorkRoot = Join-Path $env:USERPROFILE 'Desktop\kaito 受け入れテスト'
$EvidenceRoot = Join-Path $env:USERPROFILE 'Desktop\kaito-acceptance-evidence'
```

GitHub CLIを使用する場合:

```powershell
gh run download <RUN_ID> `
  --repo kaenozu/kaito `
  --name kaito-windows-verification `
  --dir $ArtifactRoot
```

## 2. 成果物検証とテストデータ生成

リポジトリルートで実行します。

```powershell
./tools/prepare_acceptance.ps1 `
  -ArtifactRoot $ArtifactRoot `
  -RepositoryRoot . `
  -WorkRoot $WorkRoot `
  -EvidenceRoot $EvidenceRoot `
  -LargeFileSizeMB 128
```

このスクリプトは次を実行します。

- `artifacts/release-sha256.txt`とEXE／インストーラーのSHA-256・サイズを照合
- 非空の既存ディレクトリを誤って削除しないためのmarker確認
- 日本語、空白、絵文字、複数階層、空ディレクトリを含む入力データ生成
- テキスト・PNGプレビューデータ生成
- 通常ZIP、通常7z、暗号化ZIP、暗号化7z生成
- 固定libarchive fixtureから通常RAR、暗号化RAR、リンクRARをデコードし、SHA-256を確認
- 破損ZIP／7z／RAR、Windows大小文字衝突ZIP、重複エントリZIP、危険なWindows名ZIPを生成
- キャンセル用のランダムデータを生成
- 全テストデータのSHA-256を`test-data-sha256.txt`へ保存

テスト専用パスワード:

```text
ZIP/7z: Kaito-Acceptance-2026!
RAR:    12345678
```

個人用または業務用パスワードへ変更しないでください。

## 3. インストール前の証跡

```powershell
./tools/collect_acceptance_evidence.ps1 `
  -Phase Before `
  -RepositoryRoot . `
  -EvidenceRoot $EvidenceRoot `
  -WorkRoot $WorkRoot
```

次をJSONへ保存します。

- Windows version/build/architecture
- 現在ユーザーが管理者かどうか
- display DPIと画面情報
- Developer Mode
- Git branch、HEAD、working tree
- システム版7-Zip
- kaito／7zプロセス
- kaitoのレジストリキー
- kaito関連の一時ディレクトリ

## 4. GUI受け入れテスト

`docs/WINDOWS_ACCEPTANCE_TEST.md`を上から順に実施します。

テストデータは`$WorkRoot`以下にあります。

```text
source-data\
archives\
cancel-source\
TEST_DATA.md
```

`archives\link-entry.rar`、大小文字衝突、重複エントリ、危険なWindows名、破損アーカイブは成功させるデータではありません。安全に拒否されることを確認します。

## 5. アンインストール後の証跡と判定

実際に使用したインストール先を指定します。

```powershell
$InstallPath = 'C:\Users\<user>\AppData\Local\Programs\kaito'

./tools/collect_acceptance_evidence.ps1 `
  -Phase After `
  -RepositoryRoot . `
  -EvidenceRoot $EvidenceRoot `
  -WorkRoot $WorkRoot `
  -InstallPath $InstallPath
```

次のいずれかが残る場合、スクリプトは終了コード2で失敗します。

- `kaito.exe`プロセス
- kaitoのPyInstaller一時ディレクトリから起動した`7z.exe`
- kaitoのコンテキストメニュー／アンインストールレジストリ
- 指定したインストール先

システムに別途インストール済みの7-Zipプロセスは、kaito由来と判定できない限り自動FAILにはしません。JSONにはすべて記録されるため、手動でも確認してください。

## 6. Issue #6への報告

次を添付または記載します。

- `artifact-verification.json`
- `acceptance-preparation.json`
- `test-data-sha256.txt`
- `environment-before.json`
- `environment-after.json`
- 必須スクリーンショット
- FAIL／BLOCKEDの再現手順とログ
- GO／NO-GO判定

パスワード、個人情報、ユーザーディレクトリ内の不要なファイル一覧は公開Issueへ貼り付けないでください。
