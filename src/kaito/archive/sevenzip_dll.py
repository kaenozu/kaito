"""src/kaito/archive/sevenzip_dll.py

同梱 bundled/7z.dll (7-Zip 26.02) の COM ライク API (IInArchive) を
ctypes から直接呼び出す読み取り系バインディング。

背景
----
kaito の読み取り系バックエンドは従来、ZIP は標準ライブラリ zipfile、
RAR/7z は 7z.exe CLI (subprocess) を使っていた。CLI は暗号化アーカイブの
パスワードをプロセス引数 (-p<password>) に渡すため、同一ユーザーの別プロセス
からコマンドラインを覗き見られる残存リスクがあった (SECURITY.md)。

本モジュールは tools/dll-poc/ で実証した IInArchive バインディングを本番向けに
昇格したもので、パスワードは ICryptoGetTextPassword (BSTR) によりプロセス内で
供給されるため、読み取り処理中に subprocess を一切生まない。

対象
----
  - list_archive / read_entry / extract / test_archive (読み取り系すべて)
  - フォーマット: zip / 7z / rar

非対象
------
  - IOutArchive (圧縮・更新) — 作成は引き続き zipfile / 7z.exe CLI が担う
  - 7z ヘッダー暗号化の展開は Open 時のパスワード供給で対応

26.02 の API 仕様 (ソース調査で確認済み)
---------------------------------------
  - CreateObject は CreateArchiver へのフォワーダ (シグネチャ不変)
  - フォーマット CLSID は {23170F69-40C1-278A-1000-0110<id>0000}
    (zip id=1 / 7z id=7)。旧 9.x の ...06000C0000 系は使えない
  - GetHandlerProperty2 の kClassID は VT_BSTR にバイナリ GUID (16 バイト)
  - 未認識アーカイブでは IInArchive::Open が S_FALSE (1) を返す
  - NOperationResult: kWrongPassword = 9 (9.x の 10 ではない)
  - PROPVARIANT の bstrVal は c_void_p で保持して wstring_at/string_at で読む
  - IInStream::Seek の newPosition は NULL で呼ばれることがある
"""

from __future__ import annotations

import ctypes
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

if sys.platform != "win32":
    raise ImportError("7z.dll 統合は Windows 専用です")

__all__ = [
    "SevenZipDllError",
    "DllOpenFailedError",
    "DllPasswordError",
    "DllExtractError",
    "SevenZipDll",
    "OpenedArchive",
    "ArchiveItem",
    "kOK",
    "kWrongPassword",
]

# ---------------------------------------------------------------------------
# HRESULT / 操作結果コード
# ---------------------------------------------------------------------------

S_OK = 0
S_FALSE = 1
E_NOINTERFACE = 0x80004002

# 7-Zip 26.02 の NArchive::NExtract::NOperationResult (IArchive.h)
kOK = 0
kUnsupportedMethod = 1
kDataError = 2
kCRCError = 3
kUnavailable = 4
kUnexpectedEnd = 5
kDataAfterEnd = 6
kIsNotArc = 7
kHeadersError = 8
kWrongPassword = 9

HRESULT = ctypes.c_long

# アーカイブ項目のプロパティID (7-Zip PropID.h)
kpidPath = 3
kpidIsDir = 6
kpidSize = 7
kpidPackSize = 8
kpidAttrib = 9
kpidMTime = 12
kpidEncrypted = 15
kpidSymLink = 64
kpidHardLink = 100

# アーカイブハンドラのプロパティID (7-Zip IArchive.h)
kHandlerName = 0
kHandlerClassID = 1
kHandlerExtension = 2

# PROPVARIANT の vt
VT_EMPTY = 0
VT_BSTR = 8
VT_BOOL = 11
VT_UI4 = 19
VT_UI8 = 21
VT_FILETIME = 64
VT_CLSID = 72


class SevenZipDllError(RuntimeError):
    """7z.dll 操作の失敗を表す基底例外。"""


class DllOpenFailedError(SevenZipDllError):
    """IInArchive::Open が S_OK 以外を返した。

    hresult == S_FALSE の場合は「アーカイブとして開けない」(未認識・破損・
    ヘッダー暗号化でパスワード不足) を意味する。呼び出し側が署名チェックで
    原因を切り分ける。
    """

    def __init__(self, message: str, hresult: int) -> None:
        super().__init__(message)
        self.hresult = hresult


class DllPasswordError(SevenZipDllError):
    """展開時にパスワードが正しくないと判明した (kWrongPassword)。"""


class DllExtractError(SevenZipDllError):
    """展開・テスト時にエラー操作結果コードが返された。"""

    def __init__(self, message: str, operation_result: int) -> None:
        super().__init__(message)
        self.operation_result = operation_result


# ---------------------------------------------------------------------------
# 基本型
# ---------------------------------------------------------------------------


class GUID(ctypes.Structure):
    """COM GUID (Windows の GUID と同じレイアウト)。"""

    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_uint8 * 8),
    ]

    @classmethod
    def from_string(cls, text: str) -> "GUID":
        parts = text.strip("{}").split("-")
        data4 = (ctypes.c_uint8 * 8)(*bytes.fromhex(parts[3] + parts[4]))
        return cls(int(parts[0], 16), int(parts[1], 16), int(parts[2], 16), data4)

    def copy(self) -> "GUID":
        result = GUID.__new__(GUID)
        ctypes.memmove(ctypes.byref(result), ctypes.byref(self), ctypes.sizeof(GUID))
        return result

    def __bytes__(self) -> bytes:
        return ctypes.string_at(ctypes.addressof(self), ctypes.sizeof(GUID))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, GUID) and bytes(self) == bytes(other)

    def __hash__(self) -> int:
        return hash(bytes(self))


# 7-Zip のインターフェース IID (7-Zip ソースの Interface.h / IArchive.h 準拠)
IID_IUnknown = GUID.from_string("{00000000-0000-0000-C000-000000000046}")
IID_IInArchive = GUID.from_string("{23170F69-40C1-278A-0000-000600600000}")
IID_IInStream = GUID.from_string("{23170F69-40C1-278A-0000-000300030000}")
IID_ISequentialOutStream = GUID.from_string("{23170F69-40C1-278A-0000-000300020000}")
IID_IArchiveOpenCallback = GUID.from_string("{23170F69-40C1-278A-0000-000600400000}")
IID_IArchiveExtractCallback = GUID.from_string("{23170F69-40C1-278A-0000-000600500000}")
IID_ICryptoGetTextPassword = GUID.from_string("{23170F69-40C1-278A-0000-000500100000}")


class FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", ctypes.c_uint32),
        ("dwHighDateTime", ctypes.c_uint32),
    ]


class PROPVARIANT(ctypes.Structure):
    """読み取りに必要な最小限の PROPVARIANT。"""

    class _Union(ctypes.Union):
        _fields_ = [
            ("lVal", ctypes.c_long),
            ("ulVal", ctypes.c_uint32),
            ("bVal", ctypes.c_ubyte),
            ("boolVal", ctypes.c_int16),
            ("pboolVal", ctypes.POINTER(ctypes.c_int16)),
            ("scode", ctypes.c_long),
            ("dblVal", ctypes.c_double),
            ("bstrVal", ctypes.c_void_p),
            ("punkVal", ctypes.c_void_p),
            ("puuid", ctypes.POINTER(GUID)),
            ("filetime", FILETIME),
            ("uhVal", ctypes.c_uint64),
        ]

    _fields_ = [
        ("vt", ctypes.c_uint16),
        ("wReserved1", ctypes.c_uint16),
        ("wReserved2", ctypes.c_uint16),
        ("wReserved3", ctypes.c_uint16),
        ("_union", _Union),
    ]


_ole32 = ctypes.WinDLL("ole32")
_oleaut32 = ctypes.WinDLL("oleaut32")
_oleaut32.SysAllocString.argtypes = [ctypes.c_wchar_p]
_oleaut32.SysAllocString.restype = ctypes.c_void_p
_oleaut32.SysFreeString.argtypes = [ctypes.c_void_p]
_ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]

_FILETIME_EPOCH_1601 = 11644473600 * 10_000_000


def _filetime_to_datetime(ft: FILETIME) -> Optional[datetime]:
    """FILETIME (1601-01-01 からの 100ns 単位) を naive datetime に変換する。"""
    raw = (ft.dwHighDateTime << 32) | ft.dwLowDateTime
    if raw == 0:
        return None
    seconds = (raw - _FILETIME_EPOCH_1601) // 10_000_000
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def _co_initialize() -> None:
    """マルチスレッド COM を初期化する (既に初期化済みなら無視)。"""
    result = _ole32.CoInitializeEx(None, 0x0)  # COINIT_MULTITHREADED
    if result not in (S_OK, S_FALSE):
        if result != 0x80010106:  # RPC_E_CHANGED_MODE: 別モードで初期化済み → 無視
            raise SevenZipDllError(
                f"CoInitializeEx に失敗しました (0x{result & 0xFFFFFFFF:08X})"
            )


def _check_hr(hr: int, what: str) -> None:
    if hr < 0:
        raise SevenZipDllError(
            f"{what} が失敗しました (HRESULT=0x{hr & 0xFFFFFFFF:08X})"
        )


def _vtable_of(obj: int) -> Any:
    """COM オブジェクトポインタから vtable ポインタ配列を取得する。"""
    first = ctypes.cast(obj, ctypes.POINTER(ctypes.c_void_p))
    return ctypes.cast(first[0], ctypes.POINTER(ctypes.c_void_p))


def _com_call(
    vtbl: ctypes.Array,
    slot: int,
    argtypes: tuple,
    this: int,
    *args: object,
) -> int:
    """vtable の slot 番目の COM メソッドを呼び出す (x64 では呼び出し規約は共通)。"""
    fn = ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p, *argtypes)(vtbl[slot])
    return int(fn(this, *args))


def _free_propvariant(value: PROPVARIANT) -> None:
    """DLL が返した PROPVARIANT の動的メモリを解放する。"""
    if value.vt == VT_BSTR and value._union.bstrVal:
        _oleaut32.SysFreeString(value._union.bstrVal)
    elif value.vt == VT_CLSID and value._union.puuid:
        _ole32.CoTaskMemFree(value._union.puuid)


def _read_bstr_prop(value: PROPVARIANT) -> str:
    try:
        if value.vt == VT_BSTR and value._union.bstrVal:
            return ctypes.wstring_at(value._union.bstrVal) or ""
        return ""
    finally:
        _free_propvariant(value)


def _read_uint_prop(value: PROPVARIANT) -> int:
    if value.vt == VT_UI4:
        return int(value._union.ulVal)
    if value.vt == VT_UI8:
        return int(value._union.uhVal)
    return 0


def _read_bool_prop(value: PROPVARIANT) -> bool:
    if value.vt == VT_BOOL:
        return value._union.boolVal != 0
    if value.vt in (VT_UI4, VT_UI8):
        return _read_uint_prop(value) != 0
    return False


def _read_filetime_prop(value: PROPVARIANT) -> Optional[datetime]:
    try:
        if value.vt == VT_FILETIME:
            return _filetime_to_datetime(value._union.filetime)
        return None
    finally:
        _free_propvariant(value)


# ---------------------------------------------------------------------------
# Python 実装の COM オブジェクト (vtable はインスタンスごとに構築)
# ---------------------------------------------------------------------------


class _ComBody(ctypes.Structure):
    _fields_ = [
        ("lpVtbl", ctypes.POINTER(ctypes.c_void_p)),
    ]


class _ComImpl:
    """Python で実装する COM オブジェクトの共通基盤。

    IUnknown 3 スロット + 派生インターフェース分の vtable をインスタンスごとに
    構築し、メソッドは self を捕捉した CFUNCTYPE コールバックとして登録する。
    """

    _slots: int = 3

    def __init__(self) -> None:
        self._vtbl_array = (ctypes.c_void_p * self._slots)()
        self._vtbl_refs: list[object] = []
        self._refcount = 1
        self._primary_iid = IID_IUnknown
        self._body = _ComBody()
        self._body.lpVtbl = ctypes.cast(
            self._vtbl_array, ctypes.POINTER(ctypes.c_void_p)
        )

    @property
    def ptr(self) -> int:
        value = ctypes.cast(ctypes.byref(self._body), ctypes.c_void_p).value
        assert value is not None
        return value

    def _register(self, slot: int, restype: Any, argtypes: tuple, impl: Any) -> None:
        fn = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(impl)
        self._vtbl_refs.append(fn)
        self._vtbl_array[slot] = ctypes.cast(fn, ctypes.c_void_p)

    def _install_iunknown(self, primary_iid: GUID) -> None:
        self._primary_iid = primary_iid
        self._register(
            0,
            HRESULT,
            (ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)),
            self._query_interface,
        )
        self._register(1, ctypes.c_uint32, (), self._add_ref)
        self._register(2, ctypes.c_uint32, (), self._release)

    # --- IUnknown ---
    def _query_interface(self, this: int, riid: int, ppv: int) -> int:
        iid = ctypes.cast(riid, ctypes.POINTER(GUID)).contents
        if iid in (IID_IUnknown, self._primary_iid):
            self._add_ref(this)
            ctypes.cast(ppv, ctypes.POINTER(ctypes.c_void_p))[0] = self.ptr
            return S_OK
        return E_NOINTERFACE

    def _add_ref(self, this: int) -> int:
        self._refcount += 1
        return self._refcount

    def _release(self, this: int) -> int:
        self._refcount = max(0, self._refcount - 1)
        return self._refcount


class FileInStream(_ComImpl):
    """IInStream: 7z.dll へアーカイブ本体を供給するファイル読み取りストリーム。"""

    _slots = 3 + 2  # IUnknown + Read + Seek

    def __init__(
        self, path: Path, cancel_check: Optional[Callable[[], None]] = None
    ) -> None:
        super().__init__()
        self._file = open(path, "rb")
        self._cancel_check = cancel_check
        self._install_iunknown(IID_IInStream)
        self._register(
            3,
            HRESULT,
            (ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)),
            self._read,
        )
        self._register(
            4,
            HRESULT,
            (ctypes.c_int64, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint64)),
            self._seek,
        )

    def _read(self, this: int, data: int, size: int, processed: int) -> int:
        if self._cancel_check is not None:
            self._cancel_check()
        chunk = self._file.read(size)
        if chunk:
            ctypes.memmove(data, chunk, len(chunk))
        if processed:
            ctypes.cast(processed, ctypes.POINTER(ctypes.c_uint32))[0] = len(chunk)
        return S_OK

    def _seek(self, this: int, offset: int, origin: int, new_position: int) -> int:
        self._file.seek(offset, origin)
        if new_position:
            ctypes.cast(new_position, ctypes.POINTER(ctypes.c_uint64))[0] = (
                self._file.tell()
            )
        return S_OK

    def close(self) -> None:
        self._file.close()


class _MemoryOutStream(_ComImpl):
    """ISequentialOutStream: 展開結果を bytearray に蓄積する。"""

    _slots = 3 + 1

    def __init__(self, sink: bytearray) -> None:
        super().__init__()
        self._sink = sink
        self._install_iunknown(IID_ISequentialOutStream)
        self._register(
            3,
            HRESULT,
            (ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)),
            self._write,
        )

    def _write(self, this: int, data: int, size: int, processed: int) -> int:
        if size:
            self._sink.extend(ctypes.string_at(data, size))
        ctypes.cast(processed, ctypes.POINTER(ctypes.c_uint32))[0] = size
        return S_OK


class _FileOutStream(_ComImpl):
    """ISequentialOutStream: 展開結果をファイルオブジェクトへ書き込む。"""

    _slots = 3 + 1

    def __init__(self, fileobj: object) -> None:
        super().__init__()
        self._write_file = fileobj.write  # type: ignore[attr-defined]
        self._install_iunknown(IID_ISequentialOutStream)
        self._register(
            3,
            HRESULT,
            (ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)),
            self._write,
        )

    def _write(self, this: int, data: int, size: int, processed: int) -> int:
        if size:
            self._write_file(ctypes.string_at(data, size))
        ctypes.cast(processed, ctypes.POINTER(ctypes.c_uint32))[0] = size
        return S_OK


class _CryptoPassword(_ComImpl):
    """ICryptoGetTextPassword: パスワードを BSTR で供給する (プロセス内のみ)。"""

    _slots = 3 + 1

    def __init__(self, password: Optional[str]) -> None:
        super().__init__()
        self._password = password
        self._install_iunknown(IID_ICryptoGetTextPassword)
        self._register(
            3,
            HRESULT,
            (ctypes.POINTER(ctypes.c_void_p),),
            self._crypto_get_text_password,
        )

    def _crypto_get_text_password(self, this: int, password_out: int) -> int:
        bstr = _oleaut32.SysAllocString(self._password or "")
        ctypes.cast(password_out, ctypes.POINTER(ctypes.c_void_p))[0] = bstr
        return S_OK


class _OpenCallback(_ComImpl):
    """IArchiveOpenCallback (+ ICryptoGetTextPassword: 7z ヘッダー暗号化用)。"""

    _slots = 3 + 2

    def __init__(
        self,
        password: Optional[str],
        cancel_check: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__()
        self._password = password
        self._cancel_check = cancel_check
        self._crypto = _CryptoPassword(password) if password is not None else None
        self._install_iunknown(IID_IArchiveOpenCallback)
        self._register(
            3,
            HRESULT,
            (ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64)),
            self._set_total,
        )
        self._register(
            4,
            HRESULT,
            (ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64)),
            self._set_completed,
        )

    def _set_total(self, this: int, files: int, bytes_: int) -> int:
        if self._cancel_check is not None:
            self._cancel_check()
        return S_OK

    def _set_completed(self, this: int, files: int, bytes_: int) -> int:
        if self._cancel_check is not None:
            self._cancel_check()
        return S_OK

    def _query_interface(self, this: int, riid: int, ppv: int) -> int:
        iid = ctypes.cast(riid, ctypes.POINTER(GUID)).contents
        if iid in (IID_IUnknown, IID_IArchiveOpenCallback):
            self._add_ref(this)
            ctypes.cast(ppv, ctypes.POINTER(ctypes.c_void_p))[0] = self.ptr
            return S_OK
        if self._crypto is not None and iid == IID_ICryptoGetTextPassword:
            self._crypto._add_ref(this)
            ctypes.cast(ppv, ctypes.POINTER(ctypes.c_void_p))[0] = self._crypto.ptr
            return S_OK
        return E_NOINTERFACE


class _ExtractCallback(_ComImpl):
    """IArchiveExtractCallback (+ ICryptoGetTextPassword)。

    単一/複数ファイルの展開・テストを受け持ち、操作結果コードを index 単位で
    記録する。fileobj が指定された場合はファイルへ、それ以外はメモリへ展開する。
    """

    _slots = (
        3 + 5
    )  # IUnknown + SetTotal/SetCompleted/GetStream/PrepareOperation/SetOperationResult

    def __init__(
        self,
        password: Optional[str],
        *,
        fileobj: Optional[object] = None,
        cancel_check: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__()
        self._password = password
        self._fileobj = fileobj
        self._cancel_check = cancel_check
        self._crypto = _CryptoPassword(password) if password is not None else None
        self.current = bytearray()
        self.results: dict[int, int] = {}
        self._out_stream: Optional[object] = None
        self._install_iunknown(IID_IArchiveExtractCallback)
        self._register(3, HRESULT, (ctypes.c_uint64,), self._set_total)
        self._register(
            4, HRESULT, (ctypes.POINTER(ctypes.c_uint64),), self._set_completed
        )
        self._register(
            5,
            HRESULT,
            (ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p), ctypes.c_int32),
            self._get_stream,
        )
        self._register(6, HRESULT, (ctypes.c_int32,), self._prepare_operation)
        self._register(7, HRESULT, (ctypes.c_int32,), self._set_operation_result)

    def _set_total(self, this: int, total: int) -> int:
        if self._cancel_check is not None:
            self._cancel_check()
        return S_OK

    def _set_completed(self, this: int, complete: int) -> int:
        if self._cancel_check is not None:
            self._cancel_check()
        return S_OK

    def _get_stream(
        self, this: int, index: int, out_stream: int, ask_extract_mode: int
    ) -> int:
        if ask_extract_mode == 0:  # kExtract = 展開 (テストモードでは 1)
            self.current = bytearray()
            if self._fileobj is not None:
                self._out_stream = _FileOutStream(self._fileobj)
            else:
                self._out_stream = _MemoryOutStream(self.current)
            self._out_stream._add_ref(this)  # type: ignore[attr-defined]
            ctypes.cast(out_stream, ctypes.POINTER(ctypes.c_void_p))[0] = (
                self._out_stream.ptr  # type: ignore[attr-defined]
            )
        else:
            ctypes.cast(out_stream, ctypes.POINTER(ctypes.c_void_p))[0] = 0
        return S_OK

    def _prepare_operation(self, this: int, ask_extract_mode: int) -> int:
        return S_OK

    def _set_operation_result(self, this: int, result: int) -> int:
        # 直前の GetStream で渡された index を覚えておく必要はなく、
        # 単一・明示インデックス呼び出しでは最後の結果を results に保持する。
        # 7z は index を渡さないため、順序はインデックス昇順とみなせる。
        self.results[len(self.results)] = int(result)
        return S_OK

    def _query_interface(self, this: int, riid: int, ppv: int) -> int:
        iid = ctypes.cast(riid, ctypes.POINTER(GUID)).contents
        if iid in (IID_IUnknown, IID_IArchiveExtractCallback):
            self._add_ref(this)
            ctypes.cast(ppv, ctypes.POINTER(ctypes.c_void_p))[0] = self.ptr
            return S_OK
        if self._crypto is not None and iid == IID_ICryptoGetTextPassword:
            self._crypto._add_ref(this)
            ctypes.cast(ppv, ctypes.POINTER(ctypes.c_void_p))[0] = self._crypto.ptr
            return S_OK
        return E_NOINTERFACE


# ---------------------------------------------------------------------------
# 7z.dll 本体と IInArchive (消費側)
# ---------------------------------------------------------------------------


class InArchive:
    """7z.dll が生成した IInArchive オブジェクトの Python ラッパー。"""

    def __init__(self, ptr: int) -> None:
        self._ptr = ptr
        self._vtbl = _vtable_of(ptr)
        self._opened = False

    def open(
        self,
        stream: FileInStream,
        open_callback: Optional[_OpenCallback] = None,
    ) -> int:
        """IInArchive::Open を呼び、生の HRESULT を返す (S_OK=0 / S_FALSE=1)。"""
        cb = open_callback.ptr if open_callback is not None else 0
        hr = _com_call(
            self._vtbl,
            3,
            (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p),
            self._ptr,
            stream.ptr,
            0,  # maxCheckStartPosition = NULL
            cb,
        )
        if hr == S_OK:
            self._opened = True
        return hr

    def close(self) -> None:
        if self._opened:
            _com_call(self._vtbl, 4, (), self._ptr)
            self._opened = False

    def get_number_of_items(self) -> int:
        num = ctypes.c_uint32()
        _com_call(
            self._vtbl,
            5,
            (ctypes.POINTER(ctypes.c_uint32),),
            self._ptr,
            ctypes.byref(num),
        )
        return int(num.value)

    def get_property(self, index: int, propid: int) -> PROPVARIANT:
        value = PROPVARIANT()
        _com_call(
            self._vtbl,
            6,
            (ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(PROPVARIANT)),
            self._ptr,
            index,
            propid,
            ctypes.byref(value),
        )
        return value

    def extract(
        self,
        indices: Optional[list[int]],
        count: int,
        test_mode: int,
        callback: _ExtractCallback,
    ) -> None:
        array = None
        if indices is not None:
            array = (ctypes.c_uint32 * count)(*indices)
        hr = _com_call(
            self._vtbl,
            7,
            (
                ctypes.POINTER(ctypes.c_uint32),
                ctypes.c_uint32,
                ctypes.c_int32,
                ctypes.c_void_p,
            ),
            self._ptr,
            array,
            count,
            test_mode,
            callback.ptr,
        )
        _check_hr(hr, "IInArchive::Extract")


def _attributes_indicate_link(attributes: int) -> bool:
    """Unix モード (上位 16bit) の S_IFLNK (0xA000) を判定する。"""
    unix_mode = (attributes >> 16) & 0xFFFF
    return (unix_mode & 0xF000) == 0xA000


class ArchiveItem:
    """アーカイブ内の1エントリ (バックエンドへ渡す生情報)。"""

    __slots__ = (
        "index",
        "name",
        "is_dir",
        "size",
        "packed_size",
        "modified",
        "is_encrypted",
        "is_link",
        "attributes",
    )

    def __init__(
        self,
        index: int,
        name: str,
        is_dir: bool,
        size: int,
        packed_size: int,
        modified: Optional[datetime],
        is_encrypted: bool,
        is_link: bool,
        attributes: int,
    ) -> None:
        self.index = index
        self.name = name
        self.is_dir = is_dir
        self.size = size
        self.packed_size = packed_size
        self.modified = modified
        self.is_encrypted = is_encrypted
        self.is_link = is_link
        self.attributes = attributes

    def __repr__(self) -> str:
        kind = "dir" if self.is_dir else "link" if self.is_link else "file"
        encrypted = " enc" if self.is_encrypted else ""
        return (
            f"<ArchiveItem {self.index}: {self.name} "
            f"({kind}, {self.size}B, packed={self.packed_size}B{encrypted})>"
        )


class OpenedArchive:
    """開いたアーカイブ。stream / callback の寿命を保持しつつ操作を提供する。"""

    def __init__(
        self,
        archive: InArchive,
        stream: FileInStream,
        open_callback: Optional[_OpenCallback],
        cancel_check: Optional[Callable[[], None]] = None,
    ) -> None:
        self._archive = archive
        self._stream = stream
        self._open_callback = open_callback
        self._cancel_check = cancel_check

    def _check_cancelled(self) -> None:
        if self._cancel_check is not None:
            self._cancel_check()

    def list_items(self) -> list[ArchiveItem]:
        items: list[ArchiveItem] = []
        count = self._archive.get_number_of_items()
        for index in range(count):
            self._check_cancelled()
            name = _read_bstr_prop(self._archive.get_property(index, kpidPath))
            size = _read_uint_prop(self._archive.get_property(index, kpidSize))
            packed = _read_uint_prop(self._archive.get_property(index, kpidPackSize))
            is_dir = _read_bool_prop(self._archive.get_property(index, kpidIsDir))
            encrypted = _read_bool_prop(
                self._archive.get_property(index, kpidEncrypted)
            )
            attributes = _read_uint_prop(self._archive.get_property(index, kpidAttrib))
            modified = _read_filetime_prop(self._archive.get_property(index, kpidMTime))
            items.append(
                ArchiveItem(
                    index=index,
                    name=name,
                    is_dir=is_dir,
                    size=size,
                    packed_size=packed,
                    modified=modified,
                    is_encrypted=encrypted,
                    is_link=_attributes_indicate_link(attributes),
                    attributes=attributes,
                )
            )
        return items

    def extract_to_memory(self, index: int, password: Optional[str] = None) -> bytes:
        callback = _ExtractCallback(password, cancel_check=self._cancel_check)
        self._archive.extract([index], 1, 0, callback)
        self._raise_for_result(callback)
        return bytes(callback.current)

    def extract_to_file(
        self,
        index: int,
        fileobj: object,
        password: Optional[str] = None,
    ) -> None:
        callback = _ExtractCallback(
            password, fileobj=fileobj, cancel_check=self._cancel_check
        )
        self._archive.extract([index], 1, 0, callback)
        self._raise_for_result(callback)

    def test_indices(
        self, indices: list[int], password: Optional[str] = None
    ) -> list[int]:
        """テストモードで指定インデックスを展開し、操作結果コード列を返す。

        結果は渡したインデックスと同じ順序で返る (7z はインデックス昇順で
        SetOperationResult を呼ぶ)。
        """
        callback = _ExtractCallback(password, cancel_check=self._cancel_check)
        self._archive.extract(indices if indices else None, len(indices), 1, callback)
        return [callback.results[position] for position in range(len(indices))]

    @staticmethod
    def _raise_for_result(callback: _ExtractCallback) -> None:
        # 単一ファイル抽出では操作結果は位置 0 に記録される。
        result = callback.results.get(0)
        if result is None or result == kOK:
            return
        if result == kWrongPassword:
            raise DllPasswordError("パスワードが正しくありません (kWrongPassword)")
        raise DllExtractError(
            f"展開が失敗しました (operationResult={result})", operation_result=result
        )

    def close(self) -> None:
        self._archive.close()
        self._stream.close()

    def __enter__(self) -> "OpenedArchive":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        self.close()
        return False


class SevenZipDll:
    """bundled/7z.dll の読み取り系ハンドラ (IInArchive) へのエントリポイント。"""

    def __init__(self, dll_path: Path) -> None:
        _co_initialize()
        self._dll = ctypes.CDLL(str(dll_path))
        self._dll.GetNumberOfFormats.argtypes = [ctypes.POINTER(ctypes.c_uint32)]
        self._dll.GetNumberOfFormats.restype = HRESULT
        self._dll.GetHandlerProperty2.argtypes = [
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.POINTER(PROPVARIANT),
        ]
        self._dll.GetHandlerProperty2.restype = HRESULT
        self._dll.CreateObject.argtypes = [
            ctypes.POINTER(GUID),
            ctypes.POINTER(GUID),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self._dll.CreateObject.restype = HRESULT

    def find_handler_clsid(self, handler_name: str) -> GUID:
        """フォーマット名 (例: "zip" / "7z" / "rar") からハンドラの CLSID を取得する。

        7-Zip 26.02 では kClassID が VT_BSTR に「バイナリ GUID」(16 バイト) を
        入れて返す (ArchiveExports.cpp の SetPropGUID → SysAllocStringByteLen)。
        """
        count = ctypes.c_uint32()
        _check_hr(
            self._dll.GetNumberOfFormats(ctypes.byref(count)),
            "GetNumberOfFormats",
        )
        for index in range(int(count.value)):
            name_pv = PROPVARIANT()
            hr = self._dll.GetHandlerProperty2(
                index, kHandlerName, ctypes.byref(name_pv)
            )
            if hr != S_OK:
                continue
            fmt_name = ""
            if name_pv.vt == VT_BSTR and name_pv._union.bstrVal:
                fmt_name = ctypes.wstring_at(name_pv._union.bstrVal) or ""
                _free_propvariant(name_pv)
            if fmt_name.lower() != handler_name.lower():
                continue
            clsid_pv = PROPVARIANT()
            hr2 = self._dll.GetHandlerProperty2(
                index, kHandlerClassID, ctypes.byref(clsid_pv)
            )
            if hr2 != S_OK or clsid_pv.vt != VT_BSTR or not clsid_pv._union.bstrVal:
                raise SevenZipDllError(
                    f"handler '{handler_name}' の CLSID を取得できません"
                )
            clsid = GUID()
            ctypes.memmove(
                ctypes.byref(clsid),
                clsid_pv._union.bstrVal,
                ctypes.sizeof(GUID),
            )
            _free_propvariant(clsid_pv)
            return clsid
        raise SevenZipDllError(f"handler '{handler_name}' が見つかりません")

    def open_archive(
        self,
        path: Path,
        handler_name: str,
        password: Optional[str] = None,
        cancel_check: Optional[Callable[[], None]] = None,
    ) -> OpenedArchive:
        """アーカイブを開く。

        IInArchive::Open が S_OK 以外の場合は DllOpenFailedError を送出する
        (hresult 属性に生値を保持。S_FALSE は「アーカイブとして開けない」)。
        """
        clsid = self.find_handler_clsid(handler_name)
        archive_ptr = ctypes.c_void_p()
        _check_hr(
            self._dll.CreateObject(
                ctypes.byref(clsid),
                ctypes.byref(IID_IInArchive),
                ctypes.byref(archive_ptr),
            ),
            "CreateObject(IInArchive)",
        )
        if not archive_ptr.value:
            raise SevenZipDllError("CreateObject が NULL を返しました")
        archive = InArchive(archive_ptr.value)
        stream = FileInStream(path, cancel_check=cancel_check)
        open_cb = (
            _OpenCallback(password, cancel_check=cancel_check)
            if password is not None
            else None
        )
        try:
            hr = archive.open(stream, open_cb)
        except SevenZipDllError:
            stream.close()
            raise
        if hr != S_OK:
            archive.close()
            stream.close()
            raise DllOpenFailedError(
                f"IInArchive::Open が失敗しました (HRESULT=0x{hr & 0xFFFFFFFF:08X})",
                hresult=hr,
            )
        return OpenedArchive(archive, stream, open_cb, cancel_check=cancel_check)
