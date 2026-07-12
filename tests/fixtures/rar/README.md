# RAR test fixtures

These RAR fixtures come from the official [libarchive](https://github.com/libarchive/libarchive) test suite at the fixed commit below.

- Repository: `https://github.com/libarchive/libarchive`
- Commit: `da33bf2d713d05f482a08a4f26aa6e0331444579`
- License: see `LICENSE.libarchive`
- Transformation: the committed files remain in their original uuencoded form. Tests decode them with Python's `binascii.a2b_uu` and verify the decoded SHA-256 before use.

| Local uu file | Upstream path | uu SHA-256 | Decoded RAR SHA-256 | Purpose |
|---|---|---|---|---|
| `test_read_format_rar_subblock.rar.uu` | `libarchive/test/test_read_format_rar_subblock.rar.uu` | `cadc9188981382fb25762128fdaf9b9b62d4cb5a0fe0838e3b16013b80f160d3` | `e871277670529329cc2c06f178ced453c560d03fd26c76614f42ef9c06b50af0` | Normal RAR listing and extraction; contains `test.txt` |
| `test_read_format_rar.rar.uu` | `libarchive/test/test_read_format_rar.rar.uu` | `d1e75b4120995bce82fc4e72ebf8b80d18ea69fa34ac62de383b8393f92afa09` | `d421b86f6290aefad61b2a36737253b2b30fe27c156bd95abfc230f24fe0307e` | Link detection and rejection; contains `testlink -> test.txt` plus nested files/directories |
| `test_read_format_rar_encryption_data.rar.uu` | `libarchive/test/test_read_format_rar_encryption_data.rar.uu` | `be268313b305b8bb048621d657e76b4f32289cd3ab59a99805698ad03b39b587` | `84ba9afcf0673aab0d1421d931e76a19294b12117483879c4b58598d3d71e83e` | Data-encrypted RAR containing `foo.txt` and `bar.txt`; password `12345678` |
| `test_read_format_rar_noeof.rar.uu` | `libarchive/test/test_read_format_rar_noeof.rar.uu` | not used by the active tests | `b42c3bdfd96eac9c3ab336b04b3b65d01a26aca099de4fae2b7d77372b83b4cc` | Reserved for truncated/end-marker compatibility tests |

The fixture files are not application assets and are never included in release builds.
