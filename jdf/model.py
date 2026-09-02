"""JDF データモデル (JobDeck)。GUI・生成・解析で共有する唯一のデータ構造。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

KIND_CHIP = "P"    # チップ(擬似パターン番号)の割付
KIND_ARRAY = "A"   # 下位チップ配列定義の割付(ネスティング)


@dataclass
class AssignCell:
    """1配列点への割付。"""
    kind: str = KIND_CHIP        # "P" or "A"
    number: int = 1              # 擬似パターン番号 or 配列番号
    table: Optional[str] = None  # ショットタイム変調テーブル名

    def key(self) -> tuple:
        return (self.kind, self.number, self.table)


@dataclass
class ArrayDef:
    """ARRAY によるチップ配列定義。配列点(1,1)は最左上、j→右、k→下。"""
    label: Optional[int] = None  # 配列番号ラベル a(ネスティング用)
    x: float = 0.0               # 起点X [μm]
    m: int = 1                   # X方向点数
    p: float = 1000.0            # Xピッチ [μm]
    y: float = 0.0               # 起点Y [μm]
    n: int = 1                   # Y方向点数
    q: float = 1000.0            # Yピッチ [μm]
    comment: str = ""
    assigns: dict = field(default_factory=dict)  # {(j, k): AssignCell}
    # ---- 表示・編集補助(JDF 出力には影響しないアプリ内メタデータ) ----
    auto_origin: bool = False    # 起点座標の自動計算(中央配置)モード
    grid_on: bool = False        # マップの太線グリッド表示(デフォルトOFF=全細線)
    grid_x: int = 5              # X方向の太線間隔 [チップ数]
    grid_y: int = 5              # Y方向の太線間隔 [チップ数]

    def apply_auto_origin(self) -> None:
        """auto_origin が ON のとき、点数とピッチから起点座標を自動計算する。

        配列が材料中心に来るよう x=-(m-1)*p/2, y=(n-1)*q/2 とする。
        """
        if self.auto_origin:
            self.x = -(self.m - 1) * self.p / 2.0
            self.y = (self.n - 1) * self.q / 2.0

    def thick_columns(self) -> list:
        """太線を引く列境界の列番号リスト(左辺=1本目)。grid_on 時のみ。

        太線は配列点の境界に引く。左辺(列1の左)を1本目として
        grid_x チップごとに引く。返す値は「列 j の左側の境界」の j。
        """
        if not (self.grid_on and self.grid_x >= 1):
            return []
        return list(range(1, self.m + 1, self.grid_x))

    def thick_rows(self) -> list:
        """太線を引く行境界の行番号リスト(上辺=1本目)。grid_on 時のみ。"""
        if not (self.grid_on and self.grid_y >= 1):
            return []
        return list(range(1, self.n + 1, self.grid_y))

    def shot_of(self, j: int, k: int) -> Optional[tuple]:
        """配列点 (j,k) が属するショット (a,b) を返す。grid_on 以外は None。

        ショット(a,b): X方向 a 番目〜a+1 番目、Y方向 b 番目〜b+1 番目の
        太線に挟まれた領域 (a,b は 1 始まりの自然数)。
        """
        if not self.grid_on:
            return None
        a = (j - 1) // max(self.grid_x, 1) + 1 if self.grid_x >= 1 else None
        b = (k - 1) // max(self.grid_y, 1) + 1 if self.grid_y >= 1 else None
        if a is None or b is None:
            return None
        return (a, b)


@dataclass
class ChipDef:
    """レイヤー内の P コマンド(チップ)。"""
    pseudo: int = 1              # 擬似パターン番号
    filename: str = ""           # パターンデータファイル名
    spprm: Optional[list] = None  # 6フィールドの文字列リスト 例 ["8.0","","","","","1"]
    comment: str = ""


@dataclass
class ModulatTable:
    """ショットタイム変調テーブル。"""
    name: str = ""
    pairs: list = field(default_factory=list)  # [(r, v), ...]
    comment: str = ""


@dataclass
class Layer:
    number: int = 1
    scale: Optional[list] = None   # [sx, sy]
    chips: list = field(default_factory=list)      # [ChipDef]
    eos_mode: int = 2
    eos_cond: str = ""
    shot_s: int = 1                # SHOT A,s の間引き量
    resist1: float = 100.0
    resist2: float = 100.0
    stdcur: float = 1.0
    comment: str = ""


@dataclass
class JobDeck:
    job_name: str = ""                     # ジョブ名行(空=出力しない)
    header_comments: list = field(default_factory=list)  # 先頭コメント行( ';' 除く本文)
    wafer: bool = True                     # /W
    material_size: float = 3.0             # d1 [inch] (3 or 4)
    circle_diameter: float = 0.0           # d2 (0=切り取りなし)
    glmpos: dict = field(default_factory=lambda: {
        "P": [0.0, 0.0], "Q": [0.0, 0.0], "R": [0.0, 0.0], "S": [0.0, 0.0]})
    glmp: Optional[list] = None            # [w, l]
    path_name: str = "PITCH"
    arrays: list = field(default_factory=list)     # [ArrayDef]
    layers: list = field(default_factory=list)     # [Layer]
    modulats: list = field(default_factory=list)   # [ModulatTable] グローバル

    # ---------- JSON シリアライズ ----------
    def to_dict(self) -> dict:
        def arr(a: ArrayDef) -> dict:
            return {
                "label": a.label, "x": a.x, "m": a.m, "p": a.p,
                "y": a.y, "n": a.n, "q": a.q, "comment": a.comment,
                "auto_origin": a.auto_origin,
                "grid_on": a.grid_on, "grid_x": a.grid_x, "grid_y": a.grid_y,
                "assigns": [
                    {"j": j, "k": k, "kind": c.kind, "number": c.number, "table": c.table}
                    for (j, k), c in sorted(a.assigns.items())
                ],
            }
        return {
            "job_name": self.job_name,
            "header_comments": list(self.header_comments),
            "wafer": self.wafer,
            "material_size": self.material_size,
            "circle_diameter": self.circle_diameter,
            "glmpos": {k: list(v) for k, v in self.glmpos.items()},
            "glmp": list(self.glmp) if self.glmp else None,
            "path_name": self.path_name,
            "arrays": [arr(a) for a in self.arrays],
            "layers": [
                {"number": l.number,
                 "scale": list(l.scale) if l.scale else None,
                 "chips": [{"pseudo": c.pseudo, "filename": c.filename,
                            "spprm": list(c.spprm) if c.spprm else None,
                            "comment": c.comment} for c in l.chips],
                 "eos_mode": l.eos_mode, "eos_cond": l.eos_cond,
                 "shot_s": l.shot_s, "resist1": l.resist1, "resist2": l.resist2,
                 "stdcur": l.stdcur, "comment": l.comment}
                for l in self.layers
            ],
            "modulats": [{"name": t.name, "pairs": [list(p) for p in t.pairs],
                          "comment": t.comment} for t in self.modulats],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "JobDeck":
        deck = cls()
        deck.job_name = d.get("job_name", "")
        deck.header_comments = list(d.get("header_comments", []))
        deck.wafer = d.get("wafer", True)
        deck.material_size = d.get("material_size", 3.0)
        deck.circle_diameter = d.get("circle_diameter", 0.0)
        deck.glmpos = {k: list(v) for k, v in d.get("glmpos", deck.glmpos).items()}
        deck.glmp = list(d["glmp"]) if d.get("glmp") else None
        deck.path_name = d.get("path_name", "PITCH")
        for a in d.get("arrays", []):
            ad = ArrayDef(label=a.get("label"), x=a["x"], m=a["m"], p=a["p"],
                          y=a["y"], n=a["n"], q=a["q"], comment=a.get("comment", ""),
                          auto_origin=a.get("auto_origin", False),
                          grid_on=a.get("grid_on", False),
                          grid_x=a.get("grid_x", 5), grid_y=a.get("grid_y", 5))
            for c in a.get("assigns", []):
                ad.assigns[(c["j"], c["k"])] = AssignCell(c["kind"], c["number"], c.get("table"))
            deck.arrays.append(ad)
        for l in d.get("layers", []):
            ly = Layer(number=l.get("number", 1),
                       scale=list(l["scale"]) if l.get("scale") else None,
                       eos_mode=l.get("eos_mode", 2), eos_cond=l.get("eos_cond", ""),
                       shot_s=l.get("shot_s", 1), resist1=l.get("resist1", 100.0),
                       resist2=l.get("resist2", 100.0), stdcur=l.get("stdcur", 1.0),
                       comment=l.get("comment", ""))
            for c in l.get("chips", []):
                ly.chips.append(ChipDef(c["pseudo"], c.get("filename", ""),
                                        list(c["spprm"]) if c.get("spprm") else None,
                                        c.get("comment", "")))
            deck.layers.append(ly)
        for t in d.get("modulats", []):
            deck.modulats.append(ModulatTable(t["name"], [tuple(p) for p in t.get("pairs", [])],
                                              t.get("comment", "")))
        return deck
