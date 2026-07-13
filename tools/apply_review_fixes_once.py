from __future__ import annotations

from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one match in {path}: found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def remove_legacy_context_menu_implementation() -> None:
    path = Path("src/kaito/gui/unzip_app.py")
    text = path.read_text(encoding="utf-8")
    import_marker = "from kaito.archive.service import ArchiveService\n"
    context_import = (
        "from kaito.context_menu import install_context_menu, uninstall_context_menu\n"
    )
    if context_import not in text:
        if text.count(import_marker) != 1:
            raise RuntimeError("ArchiveService import marker changed")
        text = text.replace(import_marker, import_marker + context_import, 1)

    start_marker = "\n_CONTEXT_EXTENSIONS = [\".zip\", \".rar\", \".7z\"]\n"
    end_marker = "\ndef _resolve_extract_dest(\n"
    start = text.find(start_marker)
    end = text.find(end_marker, start + 1)
    if start < 0 or end < 0 or end <= start:
        raise RuntimeError("legacy context-menu block markers changed")
    text = text[:start] + "\n" + text[end:]
    path.write_text(text, encoding="utf-8")


def require_loaded_archive_for_extraction_controls() -> None:
    path = Path("src/kaito/gui/productivity.py")
    old = '''    def _apply_safety_controls(self, enabled: bool = True) -> None:\n        blocked = self._safety_report is not None and not self._safety_report.can_extract\n        extraction_state = "normal" if enabled and not blocked else "disabled"\n        self.app._extract_btn.configure(state=extraction_state)\n        self._selected_button.configure(state=extraction_state)\n'''
    new = '''    def _apply_safety_controls(self, enabled: bool = True) -> None:\n        has_archive = (\n            self.app._current_archive_path is not None and bool(self.app._entries)\n        )\n        blocked = self._safety_report is not None and not self._safety_report.can_extract\n        extraction_state = (\n            "normal" if enabled and has_archive and not blocked else "disabled"\n        )\n        self.app._extract_btn.configure(state=extraction_state)\n        self._selected_button.configure(state=extraction_state)\n'''
    replace_once(path, old, new)


def remove_empty_coverage_table() -> None:
    path = Path("pyproject.toml")
    text = path.read_text(encoding="utf-8")
    text = text.replace("\n[tool.coverage.run]\n\n[tool.pyright]\n", "\n[tool.pyright]\n")
    path.write_text(text, encoding="utf-8")


def main() -> None:
    remove_legacy_context_menu_implementation()
    require_loaded_archive_for_extraction_controls()
    remove_empty_coverage_table()


if __name__ == "__main__":
    main()
