"""GUI 共有コンテキスト (AppContext)。

全タブで共有する JobDeck モデルと変更通知シグナルを保持する。
"""
from __future__ import annotations

import os

from PySide6.QtCore import QObject, Signal

from jdf.model import JobDeck


class AppContext(QObject):
    """アプリケーション共有コンテキスト。

    - deck: 編集中のジョブデックモデル
    - presets_path: GLMPOS プリセット JSON の保存先
    - changed: モデル変更通知(引数は編集元タブ or None)
    """

    changed = Signal(object)  # 編集元タブ(or None)

    def __init__(self, presets_path: str | None = None):
        super().__init__()
        self.deck: JobDeck = JobDeck()
        if presets_path is None:
            default_dir = os.path.expanduser("~/.jdf_editor")
            os.makedirs(default_dir, exist_ok=True)
            presets_path = os.path.join(default_dir, "glmpos_presets.json")
        else:
            os.makedirs(os.path.dirname(os.path.abspath(presets_path)),
                        exist_ok=True)
        self.presets_path: str = presets_path

    def notify_changed(self, source):
        """モデル変更を通知。source は編集元タブ(再帰防止で自身を除外する)。"""
        self.changed.emit(source)
