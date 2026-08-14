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

同梱の **`bundled/7z.dll` (26.02)** が公開する COM ライク API (`IInArchive`) を
ctypes から直接呼び出せば:

1. **ZIP を含む全フォーマットを 1 つの DLL バックエンドに統一できる**
   (stdlib の `zipfile` パスも同じハンドラで処理可能)
2. **パスワードがプロセス引数に一切現れない**
   (パスワードはプロセス内の `ICryptoGetTextPassword` / BSTR で供給)
3. **subprocess を生まない** (外部ツールの存在・パス解決・バージョン整合が不要)

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
```

**要点**: 対比デモ (2) で CLI パスの露出を**実プロセスで観測**し、DLL パス
(3-6) では subprocess ゼロ・コマンドライン露出ゼロを実証しました。

## アーキテクチャ: 7z.dll の COM ライク API

7z.dll は COM と同じ vtable 方式の C++ インターフェースを公開します。

```
GetNumberOfFormats / GetHandlerProperty2
        │  (フォーマット名 → CLSID。kClassID は VT_BSTR にバイナリ GUID)
CreateObject (= CreateArchiver) ──► IInArchive
                                        │
   Open(IInStream, callback)            │ 一覧
   GetNumberOfItems / GetProperty ──────┼─► ArchiveItem (パス/サイズ/暗号化)
   Extract(indices, testMode, callback) │ 展開
                                        ▼
                       IArchiveExtractCallback ─┬─► ISequentialOutStream → メモリ
                                                 └─► ICryptoGetTextPassword → パスワード (プロセス内)
```

実装 (ctypes):

| コンポーネント | 役割 |
|---|---|
| `PROPVARIANT` | プロパティの受け渡し (BSTR / UI8 / BOOL) |
| `FileInStream` | `IInStream` 実装 — アーカイブ本体を DLL へ供給 |
| `_OpenCallback` | `IArchiveOpenCallback` — 開封時の進捗 (7z ヘッダー暗号化用にパスワード供給にも対応) |
| `_ExtractCallback` | `IArchiveExtractCallback` + `ICryptoGetTextPassword` — 展開とパスワード供給 |
| `_MemoryOutStream` | `ISequentialOutStream` — 展開結果をメモリへ蓄積 |

## 7z.dll 26.02 の API 仕様 (ソース・実測から判明した要点)

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

## パスワードの流れ: CLI vs DLL

```
現行 (CLI):   kaito → subprocess → 7z.exe -p<PASSWORD> archive.7z
                                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                   プロセス引数に露出 (他プロセスから観測可能)

PoC (DLL):    kaito → 7z.dll (同一プロセス)
                        └─ Extract 中に ICryptoGetTextPassword::CryptoGetTextPassword()
                           → BSTR (メモリ) でパスワードを供給
                           コマンドラインは存在しない
```

## 実行方法

```powershell
# 検証スクリプト (フィクスチャ作成 → 対比デモ → DLL 展開 → 露出スキャン)
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

## 既知の制限 (PoC のスコープ外)

- **圧縮・更新** (`IOutArchive`) は未実装 — 圧縮バックエンドの統合は次のステップ
- **7z ヘッダー暗号化** (`-mhe=on`) の展開は Open コールバック経由の対応を
  実装済みだが、テスト未実施
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
   (パスワードも同様にプロセス内)
3. **進捗・キャンセル** — `IArchiveExtractCallback` の SetTotal /
   SetCompleted で既存の進捗コールバックを駆動
4. **SafetyLimits の適用** — 一覧・展開の両方で共通のチェックを1系統に
5. **7z.dll の更新** — バンドル元を `7z2602-extra` (フルハンドラ) に変更し、
   エクスポート名の揺れ (`CreateObject` / `CreateArchiver`) を吸収するラッパーを用意

## 関連

- [SECURITY.md](../../SECURITY.md) — 現行の CLI パスワード露出リスクの記載
- `bundled/7zip-pinned.json` — 7z.dll / 7z.exe のピン留め定義 (単一管理)
- `src/kaito/archive/sevenzip_backend.py` — 現行 CLI バックエンド
- `src/kaito/archive/zip_backend.py` — 現行 stdlib ZIP バックエンド
