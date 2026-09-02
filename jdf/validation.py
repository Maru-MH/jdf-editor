"""値域バリデーション。LIMITS に制限値を集約(GUI からも参照)。

出典: ジョブデックファイル フォーマット仕様書 5.2.1 節(JBX-8100シリーズ)。
"""
from __future__ import annotations

import re

from .model import JobDeck, KIND_ARRAY

# ---------------- 制限値定数 ----------------
LIMITS = {
    "glmpos": {"x": (-115000.0, 85000.0), "y": (-85000.0, 85000.0)},
    "glmp": {"w": (0.0, 800.0), "l": (0.0, 190000.0)},  # l の実効下限は w/2
    "array": {
        "x": (-115000.0, 85000.0), "y": (-85000.0, 85000.0),
        "m": (1, 255), "n": (1, 255),
        "p": (0.0, 190000.0), "q": (0.0, 170000.0),
        "label": (1, 2000),
    },
    "assign": {"jk": (1, 255), "number": (1, 2000)},
    # テーブル名/PATH名: 英字始まり6文字以下の大文字英数字
    "name_re": re.compile(r"^[A-Z][A-Z0-9]{0,5}$"),
    "scale": {"sx": (0.934464, 1.065536), "sy": (0.934464, 1.065536)},
    "eos": {"mode": (1, 10), "cond_len": 63},
    "shot": {"s": (1, 2000)},
    "resist": {"s1": (0.010, 1000000.0), "s2": (0.010, 1000000.0)},
    "stdcur": {"c": (0.001, 300.0)},
    "modulat": {"r": (0, 1023), "v": (-99.9, 3200.0)},
    "spprm": {
        "ss": (1, 5),
        "sc": (0.5, 1.2),
        # EOS モード別 m1 制限表 (min, max) [μm]
        "m1": {1: (3.2, 32.0), 2: (1.6, 16.0), 3: (0.8, 8.0),
               4: (0.32, 3.2), 5: (0.16, 1.6), 6: (0.08, 0.8),
               7: (0.64, 6.4), 8: (0.4, 4.0), 9: (0.064, 0.64),
               10: (0.04, 0.4)},
    },
    "layer": {"n": (1, 99), "pseudo": (1, 2000), "filename_len": 63,
              "max_chips": 99},
    "deck": {"max_arrays": 2000, "max_modulats_per_layer": 1000,
             "max_nesting": 10},
    "job": {"d1": (2.0, 8.0), "d2": (-8.0, 8.0)},
}


def _rng(errors: list, name: str, v, lim, unit: str = ""):
    lo, hi = lim
    if not (lo <= v <= hi):
        errors.append(f"{name}: {v} が範囲外 [{lo}, {hi}]{unit}")


def validate_deck(deck: JobDeck) -> list:
    """値域バリデーション。エラーメッセージのリストを返す(空=OK)。"""
    errors: list = []
    L = LIMITS

    # ---- JOB ----
    _rng(errors, "JOB 材料サイズ d1", deck.material_size, L["job"]["d1"], " inch")
    _rng(errors, "JOB 円形切り取り直径 d2", deck.circle_diameter, L["job"]["d2"], " inch")

    # ---- GLMPOS ----
    g = deck.glmpos
    for key in ("P", "Q", "R", "S"):
        x, y = g[key]
        _rng(errors, f"GLMPOS {key}.x", x, L["glmpos"]["x"], " μm")
        _rng(errors, f"GLMPOS {key}.y", y, L["glmpos"]["y"], " μm")
    if not (g["Q"][0] - g["P"][0] > 0):
        errors.append("GLMPOS: qx-px>0 を満たしません")
    if not (g["R"][1] - g["P"][1] > 0):
        errors.append("GLMPOS: ry-py>0 を満たしません")
    if not (g["P"][1] - g["S"][1] > 0):
        errors.append("GLMPOS: py-sy>0 を満たしません")

    # ---- GLMP ----
    if deck.glmp:
        w, l = deck.glmp
        _rng(errors, "GLMP w", w, L["glmp"]["w"], " μm")
        _rng(errors, "GLMP l", l, (w / 2, L["glmp"]["l"][1]), " μm")

    # ---- PATH 名 ----
    if deck.path_name and not L["name_re"].match(deck.path_name):
        errors.append(f"PATH名 '{deck.path_name}' は英字始まり6文字以下の大文字英数字ではありません")

    # ---- 配列定義 ----
    if len(deck.arrays) > L["deck"]["max_arrays"]:
        errors.append(f"配列定義数 {len(deck.arrays)} が上限 {L['deck']['max_arrays']} を超過")
    for i, a in enumerate(deck.arrays, 1):
        tag = f"配列{a.label}" if a.label is not None else f"配列#{i}"
        _rng(errors, f"{tag} x", a.x, L["array"]["x"], " μm")
        _rng(errors, f"{tag} y", a.y, L["array"]["y"], " μm")
        _rng(errors, f"{tag} m", a.m, L["array"]["m"])
        _rng(errors, f"{tag} n", a.n, L["array"]["n"])
        _rng(errors, f"{tag} p", a.p, L["array"]["p"], " μm")
        _rng(errors, f"{tag} q", a.q, L["array"]["q"], " μm")
        if a.label is not None:
            _rng(errors, f"{tag} ラベル", a.label, L["array"]["label"])
        for (j, k), cell in sorted(a.assigns.items()):
            if not (L["assign"]["jk"][0] <= j <= min(L["assign"]["jk"][1], a.m)):
                errors.append(f"{tag} ASSIGN: j={j} が配列の m={a.m} を超過")
            if not (L["assign"]["jk"][0] <= k <= min(L["assign"]["jk"][1], a.n)):
                errors.append(f"{tag} ASSIGN: k={k} が配列の n={a.n} を超過")
            _rng(errors, f"{tag} ASSIGN 番号", cell.number, L["assign"]["number"])
            if cell.table:
                if not L["name_re"].match(cell.table):
                    errors.append(f"{tag} ASSIGN テーブル名 '{cell.table}' が不正")
                elif not any(t.name == cell.table for t in deck.modulats):
                    errors.append(f"{tag} ASSIGN: 未定義の変調テーブル '{cell.table}'")

    # ---- レイヤー ----
    for layer in deck.layers:
        lt = f"LAYER {layer.number}"
        _rng(errors, f"{lt} 番号", layer.number, L["layer"]["n"])
        if len(layer.chips) > L["layer"]["max_chips"]:
            errors.append(f"{lt}: P コマンド数 {len(layer.chips)} が上限 "
                          f"{L['layer']['max_chips']} を超過")
        for chip in layer.chips:
            _rng(errors, f"{lt} P({chip.pseudo}) 擬似パターン番号",
                 chip.pseudo, L["layer"]["pseudo"])
            if len(chip.filename) > L["layer"]["filename_len"]:
                errors.append(f"{lt} P({chip.pseudo}): ファイル名が63文字超過")
            if chip.spprm:
                _validate_spprm(errors, lt, chip, layer.eos_mode)
        if layer.scale is not None:
            _rng(errors, f"{lt} SCALE sx", layer.scale[0], L["scale"]["sx"])
            _rng(errors, f"{lt} SCALE sy", layer.scale[1], L["scale"]["sy"])
        _rng(errors, f"{lt} EOS モード", layer.eos_mode, L["eos"]["mode"])
        if len(layer.eos_cond) > L["eos"]["cond_len"]:
            errors.append(f"{lt}: EOS 条件名が63文字超過")
        _rng(errors, f"{lt} SHOT 間引き s", layer.shot_s, L["shot"]["s"])
        _rng(errors, f"{lt} RESIST s1", layer.resist1, L["resist"]["s1"])
        _rng(errors, f"{lt} RESIST s2", layer.resist2, L["resist"]["s2"])
        _rng(errors, f"{lt} STDCUR", layer.stdcur, L["stdcur"]["c"], " nA")

    # ---- MODULAT(グローバル、各レイヤーに展開される) ----
    if len(deck.modulats) > L["deck"]["max_modulats_per_layer"]:
        errors.append(f"MODULAT 数 {len(deck.modulats)} がレイヤーあたり上限 "
                      f"{L['deck']['max_modulats_per_layer']} を超過")
    for t in deck.modulats:
        if not L["name_re"].match(t.name):
            errors.append(f"MODULAT テーブル名 '{t.name}' が不正")
        for r, v in t.pairs:
            _rng(errors, f"MODULAT {t.name} r", r, L["modulat"]["r"])
            _rng(errors, f"MODULAT {t.name} v", v, L["modulat"]["v"], " %")

    return errors


def _validate_spprm(errors: list, lt: str, chip, eos_mode: int):
    """SPPRM の m1(EOSモード別)/ss を検査。空フィールドはスキップ。"""
    fields = list(chip.spprm) + [""] * 6
    m1s, m2s, scs, sss = fields[0], fields[1], fields[4], fields[5]
    if m1s:
        try:
            m1 = float(m1s)
            lim = LIMITS["spprm"]["m1"].get(eos_mode)
            if lim:
                _rng(errors, f"{lt} P({chip.pseudo}) SPPRM m1(EOS{eos_mode})",
                     m1, lim, " μm")
        except ValueError:
            errors.append(f"{lt} P({chip.pseudo}) SPPRM m1 が数値でない: {m1s!r}")
    if m2s and m1s:
        try:
            if float(m2s) > float(m1s):
                errors.append(f"{lt} P({chip.pseudo}) SPPRM: m2 が m1 を超過")
        except ValueError:
            pass
    if scs:
        try:
            _rng(errors, f"{lt} P({chip.pseudo}) SPPRM sc",
                 float(scs), LIMITS["spprm"]["sc"])
        except ValueError:
            errors.append(f"{lt} P({chip.pseudo}) SPPRM sc が数値でない: {scs!r}")
    if sss:
        try:
            _rng(errors, f"{lt} P({chip.pseudo}) SPPRM ss",
                 int(sss), LIMITS["spprm"]["ss"])
        except ValueError:
            errors.append(f"{lt} P({chip.pseudo}) SPPRM ss が整数でない: {sss!r}")


def validate_nesting(deck: JobDeck) -> list:
    """配列ネスティングの検査: 階層>10・循環参照・存在しない配列番号。"""
    errors: list = []
    by_label = {}
    for a in deck.arrays:
        if a.label is None:
            continue
        if a.label in by_label:
            errors.append(f"配列ラベル {a.label} が重複しています")
        by_label[a.label] = a

    graph: dict = {}
    for label, a in by_label.items():
        refs = set()
        for cell in a.assigns.values():
            if cell.kind != KIND_ARRAY:
                continue
            if cell.number not in by_label:
                errors.append(f"配列 {label}: 存在しない配列番号 A({cell.number}) への参照")
            elif cell.number == label:
                errors.append(f"配列 {label}: 自己参照による循環")
            else:
                refs.add(cell.number)
        graph[label] = refs

    max_depth = LIMITS["deck"]["max_nesting"]
    depth: dict = {}
    visiting: set = set()

    def dfs(label: int, path: list) -> int:
        if label in depth:
            return depth[label]
        if label in visiting:
            cycle = " -> ".join(str(x) for x in path + [label])
            errors.append(f"配列の循環参照を検出: {cycle}")
            return 0
        visiting.add(label)
        d = 1
        for child in graph.get(label, ()):
            d = max(d, 1 + dfs(child, path + [label]))
        visiting.discard(label)
        depth[label] = d
        return d

    for label in graph:
        d = dfs(label, [])
        if d > max_depth:
            errors.append(f"配列 {label}: ネスティング {d} 階層が上限 "
                          f"{max_depth} を超過")
    return errors
