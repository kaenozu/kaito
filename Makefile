# kaito — tools/ の検査スクリプト一括実行
#
# make check は CI（.github/workflows/verify.yml）と同一コマンド
# （uv run --frozen python tools/check_all.py）で tools/ の検査を一式実行する。
# 依存を変更した場合は先に uv sync を実行する（--frozen のため）。
# make が無い環境でも tools/check_all.py を直接実行できる。
#
# 使い方:
#   make                # 全検査を順に実行（check と同じ）
#   make check          # CI と同一コマンドで全検査を実行
#   make check-mock-i18n     # モック I18N 辞書が i18n.py と一致しているか
#   make check-mock-theme    # モック CSS 変数が theme.py トークンと一致しているか
#   make check-mock-render   # モック CSS が実アプリ描画（スクリーンショット解析）と一致しているか
#   make check-font-audit    # 全 CTk ウィジェットのフォント実測値を検証（Tk 必要）
#
# 個別ターゲットはローカル開発用（uv run python で自動同期）。
# check-mock-render / check-font-audit は実 Tk ウィンドウと画面キャプチャを使う。
# キャプチャ不可環境では実描画/インク計測が N/A に自動降格し、判定は決定的な項目に基づく。

.PHONY: check check-mock-i18n check-mock-theme check-mock-render check-font-audit

.DEFAULT_GOAL := check

# CI（verify.yml）と同一コマンド。実 Tk ウィンドウ（topmost）が一瞬表示される
check:
	uv run --frozen python tools/check_all.py

check-mock-i18n:
	uv run python tools/gen_mock_i18n.py --check

check-mock-theme:
	uv run python tools/check_mock_theme.py

check-mock-render:
	uv run python tools/check_mock_render.py --no-html

check-font-audit:
	uv run python tools/font_audit.py --no-html
