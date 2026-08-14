# 7z.dll 直接統合 PoC — 全バックエンド統一とパスワード露出の解消

> **これは PoC (Proof of Concept) です。プロダクションコードではありません。**
> 検証目的の実装であり、実バックエンドへの組み込みは行いません。

## 背景: 現行の課題

kaito の展開バックエンドは現在2系統に分かれています。

| フォーマット | バックエンド | パスワードの扱い |
|---|---|---|
| ZIP | Python 標準ライブラリ `zipfile` | プロセス内 (安全) |
| 7z / RAR | 同梱 `7z.exe` CLI (subprocess) | **プロセス引数 `-p<password>` (露出)** |

SECURITY.md に明記されている通り、7-Zip CLI 方式では Windows の同一ユーザーで
動く別プロセスからコマンドラインを読み取れるため、暗号化アーカイブの処理中に
パスワードが露出します。制限の適用 (SafetyLimits) やプレビュー上限の配線も
バックエンドごとに二重実装になっています。

## この PoC の主張

同梱の **`bundled/7z.dll` (26.02)** が公開する COM ライク API
(`IInArchive` / `IOutArchive`) を ctypes から直接呼び出せば:

1. **ZIP を含む全フォーマットを 1 つの DLL バックエンドに統一できる**
   (stdlib の `zipfile` パスも同じハンドラで処理可能)
2. **パスワードがプロセス引数に一切現れない**
   (パスワードはプロセス内の `ICryptoGetTextPassword` / `ICryptoGetTextPassword2`
   で供給)
3. **subprocess を生まない** (外部ツールの存在・パス解決・バージョン整合が不要)
4. **圧縮も同じ DLL で完結できる** — 平文 / AES-256 ZIP / 暗号化 7z /
   ヘッダー暗号化 7z (`-mhe=on` 相当) の作成を実証

## 検証結果 (Windows + bundled/7z.dll 26.02 で実測)

```
[2] 対比: 現行 CLI パスはパスワードをプロセス引数に渡す...
    [検出] 実行中のプロセスのコマンドラインにパスワードが露出:
        ...\7z.exe a -tzip -p*** -si ...
    → 現行の 7z.exe subprocess 方式では同一ユーザーの別プロセスから
      コマンドラインを覗ける (SECURITY.md の残存リスク)。

[3] 7z.dll (IInArchive) で暗号化アーカイブを開いて展開...
    ZIP (AES-256): 項目=['secret.txt'] 暗号化=[True] 展開=23B 一致=True
    7z (AES-256): 項目=['secret.txt'] 暗号化=[True] 展開=23B 一致=True

[4] 誤パスワードの拒否... [OK] 拒否されました

[5] DLL 操作中の subprocess 呼び出しを記録...
    [OK] DLL 操作中に subprocess 呼び出しゼロ (プロセスを生まない)

[6] 全プロセスのコマンドライン走査 (パスワード露出の有無)...
    [OK] 操作前: 露出ゼロ / 操作後: 露出ゼロ

[7] 7z.dll (IOutArchive) で圧縮...
    write-plain.zip:        項目=['dir1/file.txt', 'top.bin'] 一致=True
    write-enc.zip:          項目=['dir1/file.txt', 'top.bin'] 一致=True
    write-plain.7z:         項目=['dir1/file.txt', 'top.bin'] 一致=True
    write-enc.7z:           項目=['dir1/file.txt', 'top.bin'] 一致=True
    write-enc-headers.7z:   項目=['dir1/file.txt', 'top.bin'] 一致=True ヘッダー暗号化=ON
    [OK] 圧縮中の subprocess 呼び出しゼロ (パスワードはプロセス内供給)

[8] 圧縮後の全プロセス・コマンドライン走査...
    [OK] 圧縮後: 露出ゼロ
```

**要点**: 対比デモ (2) で CLI パスの露出を**実プロセスで観測**し、DLL パス
(3-8) では読み取り・書き込みとも subprocess ゼロ・コマンドライン露出ゼロを
実証しました。圧縮は ZIP (平文 / AES-256)・7z (平文 / 暗号化 / ヘッダー暗号化)
の5ケースすべてで往復検証 (作成 → DLL 読み取り → 内容一致) に成功しています。

## アーキテクチャ: 7z.dll の COM ライク API

7z.dll は COM と同じ vtable 方式の C++ インターフェースを公開します。

```
GetNumberOfFormats / GetHandlerProperty2
        │  (フォーマット名 → CLSID。kClassID は VT_BSTR にバイナリ GUID)
CreateObject (= CreateArchiver) ──┬─► IInArchive
                                  │        │
                                  │   Open(IInStream, callback)            │ 一覧
                                  │   GetNumberOfItems / GetProperty ──────┼─► ArchiveItem (パス/サイズ/暗号化)
                                  │   Extract(indices, testMode, callback) │ 展開
                                  │        ▼
                                  │   IArchiveExtractCallback ─┬─► ISequentialOutStream → メモリ
                                  │                            └─► ICryptoGetTextPassword → パスワード (プロセス内)
                                  │
                                  └─► IOutArchive
                                           │
   SetProperties(x / em / he) ────────────┤ 圧縮オプション
   UpdateItems(IOutStream, count, cb) ────┤ 圧縮実行
                                           ▼
                        IArchiveUpdateCallback ─┬─► ISequentialInStream (ソース読み取り)
                                                └─► ICryptoGetTextPassword2 → パスワード (プロセス内)
```

実装 (ctypes):

| コンポーネント | 役割 |
|---|---|
| `PROPVARIANT` | プロパティの受け渡し (BSTR / UI8 / BOOL / FILETIME) |
| `FileInStream` | `IInStream` 実装 — アーカイブ本体や圧縮ソースを DLL へ供給 |
| `_OpenCallback` | `IArchiveOpenCallback` — 開封時の進捗 (7z ヘッダー暗号化用にパスワード供給にも対応) |
| `_ExtractCallback` | `IArchiveExtractCallback` + `ICryptoGetTextPassword` — 展開とパスワード供給 |
| `_MemoryOutStream` | `ISequentialOutStream` — 展開結果をメモリへ蓄積 |
| `_OutArchive` | `IOutArchive` — `SetProperties` / `UpdateItems` の呼び出し |
| `_FileOutStream` | `IOutStream` — 書き込み先ファイル (7z は `Seek`/`SetSize` を要求) |
| `_UpdateCallback` | `IArchiveUpdateCallback` + `ICryptoGetTextPassword2` — 圧縮とパスワード供給 |

## 7z.dll 26.02 の API 仕様 (ソース・実測から判明した要点)

### 読み取り系 (IInArchive)

- **`CreateObject` は `CreateArchiver` へのフォワーダ** (DllExports.cpp)。シグネチャは
  `CreateObject(const GUID *clsid, const GUID *iid, void **outObject)` のまま
- **フォーマット CLSID は旧形式と異なる**: 26.02 では
  `CLSID_CArchiveHandler = {23170F69-40C1-278A-1000-0110000000}` の
  `Data4[5]` にフォーマット ID を埋める。例: **zip = {23170F69-40C1-278A-1000-0110010000}**、
  **7z = {23170F69-40C1-278A-1000-0110070000}** (旧 9.x の `...06000C0000` 系は 26.02 では
  `CLASS_E_CLASSNOTAVAILABLE` になる)
- **`GetHandlerProperty2` の `kClassID` は VT_BSTR にバイナリ GUID (16 バイト)** を
  `SysAllocStringByteLen` で入れて返す (ArchiveExports.cpp の `SetPropGUID`)。名前から
  CLSID を動的解決するには BSTR 先頭 16 バイトを GUID として読む
- **`GetClassIDFromFormatIndex` は 26.02 の 7z.dll にエクスポートされていない**
- PROPVARIANT の `bstrVal` は ctypes の `c_wchar_p` にすると自動文字列変換で
  ポインタが壊れるため、**生ポインタ (`c_void_p`) で保持し `ctypes.wstring_at` /
  `ctypes.string_at` で読む**こと
- `IInStream::Seek` の `newPosition` と `Read` の `processedSize` は NULL で呼ばれる
  ことがあるため、書き込み前にガードする

### 書き込み系 (IOutArchive)

- **7z ハンドラは出力先に `IOutStream` (`Seek` + `SetSize` 付き) を要求**する。
  `ISequentialOutStream` のみ渡すと `E_NOTIMPL` になる (7zUpdate.cpp の実装確認済み)
- **圧縮オプションは `ISetProperties::SetProperties`** で渡す。プロパティ名は
  **7z = `x` (level) / `he` (ヘッダー暗号化)**、**zip = `x` / `em` (暗号化方式,
  `AES256`)**。値は PROPVARIANT (`VT_UI4` / `VT_BOOL` / `VT_BSTR`) で供給
- **ディレクトリ名の末尾区切りは付けない** — ハンドラが区切りを補完する
  (読み取り側は Windows では `\` を返すため `/` に正規化が必要)
- **ヘッダー暗号化 7z はパスワードなしで開くと一覧が空**になる (エラーではなく
  0 項目。7-Zip の仕様どおり)。読み取り側は Open コールバック経由でパスワードを供給。
  この経路は tests/test_dll_poc.py の Open コールバック検証テストで固定済み
  (データ暗号化のみの 7z は Open 中に要求しないことも対比検証)
- ソースストリーム (`ISequentialInStream`) は DLL が `Release` しても Python 側の
  ファイルハンドルは閉じないため、**書き込み後にコールバック側で明示的に close**
  する必要がある (ハンドルリーク防止)

## パスワードの流れ: CLI vs DLL

```
現行 (CLI):   kaito → subprocess → 7z.exe -p<PASSWORD> archive.7z
                                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                   プロセス引数に露出 (他プロセスから観測可能)

PoC (DLL):    kaito → 7z.dll (同一プロセス)
                        ├─ Extract 中に ICryptoGetTextPassword::CryptoGetTextPassword()
                        ├─ Update  中に ICryptoGetTextPassword2::CryptoGetTextPassword2()
                        │    → BSTR (メモリ) でパスワードを供給
                        └─ コマンドラインは存在しない
```

## 実行方法

```powershell
# 検証スクリプト (フィクスチャ作成 → 対比デモ → DLL 展開 → 圧縮 → 露出スキャン)
python tools/dll-poc/poc_verify.py

# pytest (Windows + bundled/7z.dll がある環境でのみ実行)
python -m pytest tests/test_dll_poc.py -v
```

### `poc_verify.py` の検証項目

1. 暗号化 ZIP (AES-256) / 7z を `IInArchive` で開き、一覧・展開 (内容一致)
2. 誤パスワードの拒否
3. DLL 操作中に `subprocess` 呼び出しゼロ (プロセスを生まない)
4. 操作前後の全プロセス・コマンドライン走査でパスワード露出ゼロ
5. 対比: 現行 CLI パスは `-p<password>` をプロセス引数に渡すことを実演
   (`7z.exe a -si` で stdin を開いたままブロックさせ、走査で検出)
6. `IOutArchive` で圧縮 — 平文 / AES-256 ZIP / 暗号化 7z / ヘッダー暗号化 7z を
   作成し、DLL 読み取りで往復検証 (5ケース)
7. 圧縮中の `subprocess` 呼び出しゼロ + 圧縮後のコマンドライン走査で露出ゼロ

## 既知の制限 (PoC のスコープ外)

- **更新** (`UpdateItems` による既存アーカイブへの追記・削除) は未実装 —
  新規作成のみ実証 (更新は `GetUpdateItemInfo` の既存インデックス指定で実現可能)
- **RAR の書き込み**は対象外 (7-Zip は RAR 書き込み非対応のため、読み取り専用)
- メモリ展開のみ (ファイルへの直接展開は `ISequentialOutStream` を
  ファイルストリームに差し替えるだけで実現可能)
- エラー詳細 (CRC / データ破損) の区別は operationResult で判定可能だが、
  本 PoC では大分類のみ
- 単一プロセス内のパスワード保持であるため、同一プロセスを共有するコードからは
  参照可能 (CLI 方式の「同一ユーザーの別プロセス」より攻撃面は大幅に縮小)

## 次のステップ (実バックエンド統合への道)

1. **`ArchiveBackend` の読み取り系を DLL に統一** — `list_archive` /
   `read_entry` を `SevenZipDll` ベースに置き換え、stdlib `zipfile` パスを廃止
2. **`IOutArchive` で圧縮を統一** — `CompressionOptions` を DLL に配線
   (平文 / パスワード付き / AES-256 / ヘッダー暗号化は PoC で実証済み)
3. **進捗・キャンセル** — `IArchiveExtractCallback` / `IArchiveUpdateCallback` の
   SetTotal / SetCompleted で既存の進捗コールバックを駆動
4. **SafetyLimits の適用** — 一覧・展開・圧縮の両方で共通のチェックを1系統に
5. **7z.dll の更新** — バンドル元を `7z2602-extra` (フルハンドラ) に変更し、
   エクスポート名の揺れ (`CreateObject` / `CreateArchiver`) を吸収するラッパーを用意

## 関連

- [SECURITY.md](../../SECURITY.md) — 現行の CLI パスワード露出リスクの記載
- `bundled/7zip-pinned.json` — 7z.dll / 7z.exe のピン留め定義 (単一管理)
- `src/kaito/archive/sevenzip_backend.py` — 現行 CLI バックエンド
- `src/kaito/archive/zip_backend.py` — 現行 stdlib ZIP バックエンド
