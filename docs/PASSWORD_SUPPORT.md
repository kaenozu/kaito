# Password compatibility

kaito supports password-protected archives through the bundled 7-Zip backend, but password character support depends on the archive encryption scheme.

- **AES-256 ZIP / 7z:** Unicode passwords are supported by the modern encryption path.
- **Legacy ZipCrypto ZIP:** use **ASCII-only passwords** for interoperable creation and extraction.
- **non-ASCII ZipCrypto passwords:** not supported as a guaranteed compatibility contract. The legacy scheme does not define a portable password encoding, and bundled 7-Zip 26.02 on the Windows acceptance runner rejects a Japanese ZipCrypto creation password with `System ERROR: The parameter is incorrect.`

This limitation is specific to legacy ZipCrypto. It must not be generalized to AES-256 or 7z encryption.

The CI suite contains a strict ASCII ZipCrypto round-trip regression. If support for non-ASCII ZipCrypto becomes deterministic across the bundled backend and supported Windows environments, this compatibility boundary can be widened together with a strict regression fixture.
