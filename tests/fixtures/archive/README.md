# アーカイブ固定フィクスチャ (tests/fixtures/archive/)

7z / 暗号化 ZIP の固定バイナリを uuencode したものです。テスト実行時に
`7z.exe` を起動しません (コンソール窓のポップアップ防止・外部依存ゼロ)。

## 内容

| フィクスチャ | 形式 | 内容 | パスワード |
|---|---|---|---|
| `normal.7z` | 7z (平文) | `hello.txt` = "Hello World" / `sub/file.txt` = "Nested file" | — |
| `encrypted.7z` | 7z (暗号化) | `secret.txt` = "Secret Data" | `secret123` |
| `japanese.7z` | 7z (平文) | `日本語.txt` = "Japanese filename test" | — |
| `dll-encrypted-aes.zip` | ZIP (AES-256) | `secret.txt` = "DLL PoC secret content\n" | `Kaito-Dll-Poc-2026!` |
| `dll-encrypted.7z` | 7z (暗号化) | `secret.txt` = "DLL PoC secret content\n" | `Kaito-Dll-Poc-2026!` |
| `dll-enc-headers.7z` | 7z (ヘッダー暗号化 `-mhe=on`) | `secret.txt` = "DLL PoC secret content\n" | `Kaito-Dll-Poc-2026!` |
| `aes-acceptance.zip` | ZIP (AES-256) | `secret.txt` = "AES ZIP secret\n" | `Kaito-Acceptance-2026!` |

## 再生成方法 (開発時のみ・テスト実行時は不要)

同梱の `bundled/7z.exe` (26.02) で再生成し、uuencode (CRLF) と SHA-256 を
更新します。再生成後は `tests/conftest.py` の `_decode_uu` 期待ハッシュも
合わせて更新してください。

```powershell
# 7z (平文)
7z.exe a normal.7z <src>/* -y -sccUTF-8
# 7z (暗号化)
7z.exe a -psecret123 encrypted.7z <src>/* -y -sccUTF-8
# 7z (ヘッダー暗号化)
7z.exe a -mhe=on -pKaito-Dll-Poc-2026! dll-enc-headers.7z <src>/* -y -sccUTF-8
# ZIP (AES-256)
7z.exe a -tzip -mem=AES256 -p<KASSWORD> <name>.zip <src>/* -y -sccUTF-8
```
