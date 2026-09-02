"""アプリケーション全体の外観設定(文字サイズ・フォント)の永続化と適用。

設定は ``~/.jdf_editor/settings.json`` (GUIプリセットと同じディレクトリ)に
JSON で保存し、起動時に読み込んで QApplication 全体へスタイルシートで適用する。
"""
from __future__ import annotations

import json
import os

from PySide6.QtGui import QFontDatabase

SETTINGS_DIR = os.path.expanduser("~/.jdf_editor")
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings.json")

# 文字サイズプリセット (pt)。現行の見た目は「小」相当。
FONT_SIZES = {"small": 9, "medium": 11, "large": 13}
FONT_SIZE_LABELS = {
    "small": "小 (9pt)",
    "medium": "中 (11pt)",
    "large": "大 (13pt)",
}
DEFAULT_FONT_SIZE = "small"

# 日本語可読性の高い書体候補(優先順)。
# この中から QFontDatabase で実際に利用可能なものだけを選択肢に出す。
FONT_FAMILY_CANDIDATES = (
    "BIZ UDPGothic",
    "Noto Sans CJK JP",
    "Noto Sans JP",
    "Meiryo UI",
    "Yu Gothic UI",
    "IPAexゴシック",
    "Hiragino Sans",
)

# マップタブの区間番号(ショット番号)サイズ。実際の描画比率は tab_map 側で定義。
MAP_LABEL_SIZES = ("small", "medium", "large")
MAP_LABEL_SIZE_LABELS = {"small": "小", "medium": "中", "large": "大"}
DEFAULT_MAP_LABEL_SIZE = "medium"

DEFAULT_SETTINGS = {
    "font_size": DEFAULT_FONT_SIZE,
    "font_family": "",
    "map_label_size": DEFAULT_MAP_LABEL_SIZE,
}


def _normalize(data: dict) -> dict:
    """読み込んだ設定値を既知の範囲に正規化する(未知キーは既定値で補完)。"""
    settings = dict(DEFAULT_SETTINGS)
    if isinstance(data, dict):
        size = data.get("font_size")
        if size in FONT_SIZES:
            settings["font_size"] = size
        family = data.get("font_family")
        if isinstance(family, str):
            settings["font_family"] = family.strip()
        label_size = data.get("map_label_size")
        if label_size in MAP_LABEL_SIZES:
            settings["map_label_size"] = label_size
    return settings


def load_settings(path: str | None = None) -> dict:
    """settings.json を読み込む。無い/壊れている場合は既定値を返す。"""
    path = path or SETTINGS_PATH
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return _normalize(json.load(f))
        except (OSError, ValueError):
            pass  # 壊れた設定ファイルは無視して既定値
    return dict(DEFAULT_SETTINGS)


def save_settings(settings: dict, path: str | None = None) -> None:
    """settings.json に保存する(失敗時は静かに無視)。"""
    path = path or SETTINGS_PATH
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(_normalize(settings), f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def available_font_families() -> list[str]:
    """候補書体のうち、この環境で実際に利用可能なものだけを返す。"""
    installed = set(QFontDatabase.families())
    return [f for f in FONT_FAMILY_CANDIDATES if f in installed]


def apply_to_app(app, settings: dict) -> None:
    """設定をアプリケーション全体のスタイルシートとして即時適用する。

    ``* { font-family: ...; font-size: Npt; }`` 方式のため、
    既に生成済みのウィジェットにも効果が及ぶ。
    font_family が空ならフォントはシステム既定のままとし、サイズのみ指定する。
    """
    settings = _normalize(settings)
    size_pt = FONT_SIZES[settings["font_size"]]
    family = settings["font_family"]
    if family:
        # 指定書体が見つからない環境に備え、利用可能な候補をフォールバック列に並べる
        fallbacks = [f for f in available_font_families() if f != family]
        chain = ", ".join([f'"{family}"'] + [f'"{f}"' for f in fallbacks])
        css = f"* {{ font-family: {chain}; font-size: {size_pt}pt; }}"
    else:
        css = f"* {{ font-size: {size_pt}pt; }}"
    app.setStyleSheet(css)
