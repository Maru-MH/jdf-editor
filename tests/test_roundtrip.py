"""実例ファイルのラウンドトリップテスト。

parse -> generate -> parse -> generate で2回目と1回目の出力が一致(冪等)
すること、および主要パラメータが元ファイルと一致することを検証する。
"""
from pathlib import Path

import pytest

from jdf import parse_jdf, generate_jdf

_SAMPLES = Path(__file__).resolve().parent.parent / "samples"
EXAMPLE1 = str(_SAMPLES / "example1.jdf")
EXAMPLE2 = str(_SAMPLES / "example2.jdf")
EXAMPLE3 = str(_SAMPLES / "example3.jdf")

# 例ファイルから事前確認した主要パラメータ期待値
EXPECTED = {
    EXAMPLE1: {
        "job_name": "Maruyama",
        "glmpos": {"P": [-27600, 450], "Q": [30000, 450],
                   "R": [-20400, 22050], "S": [-20400, -21150]},
        "arrays": 2,
        "cells": 264,
        "layers": 5,
        "chips": 75,
        "modulats": ["S11M", "S225"],
    },
    EXAMPLE2: {
        "job_name": "",
        "glmpos": {"P": [-18000, -21000], "Q": [18000, 23000],
                   "R": [-18000, 23000], "S": [18000, -21000]},
        "arrays": 17,
        "cells": 335,
        "layers": 4,
        "chips": 54,
        "modulats": ["S11M", "S11A", "S11B", "S12", "S13", "S14"],
    },
    EXAMPLE3: {
        "job_name": "",
        "glmpos": {"P": [-27650, -2850], "Q": [27600, -2850],
                   "R": [-14650, 21150], "S": [-14650, -26850]},
        "arrays": 17,
        "cells": 148,
        "layers": 5,
        "chips": 28,
        "modulats": ["S11M", "S11A", "S12", "S13", "S14", "S15"],
    },
}


@pytest.fixture(params=[EXAMPLE1, EXAMPLE2, EXAMPLE3],
                ids=["example1", "example2", "example3"])
def example(request):
    return request.param


def test_idempotent(example):
    """parse->generate->parse->generate で出力が一致する。"""
    deck1 = parse_jdf(open(example).read())
    out1 = generate_jdf(deck1)
    deck2 = parse_jdf(out1)
    out2 = generate_jdf(deck2)
    assert out1 == out2


def test_key_parameters(example):
    """主要パラメータが元ファイルと一致する。"""
    exp = EXPECTED[example]
    deck = parse_jdf(open(example).read())
    assert deck.job_name == exp["job_name"]
    assert deck.glmpos == exp["glmpos"]
    assert len(deck.arrays) == exp["arrays"]
    assert sum(len(a.assigns) for a in deck.arrays) == exp["cells"]
    assert len(deck.layers) == exp["layers"]
    assert sum(len(l.chips) for l in deck.layers) == exp["chips"]
    assert [t.name for t in deck.modulats] == exp["modulats"]


def test_roundtrip_preserves_params(example):
    """再 parse したモデルの主要パラメータが変わらない。"""
    deck1 = parse_jdf(open(example).read())
    deck2 = parse_jdf(generate_jdf(deck1))
    assert deck1.glmpos == deck2.glmpos
    assert deck1.glmp == deck2.glmp
    assert len(deck1.arrays) == len(deck2.arrays)
    assert (sum(len(a.assigns) for a in deck1.arrays)
            == sum(len(a.assigns) for a in deck2.arrays))
    assert len(deck1.layers) == len(deck2.layers)
    assert [t.name for t in deck1.modulats] == [t.name for t in deck2.modulats]
    for l1, l2 in zip(deck1.layers, deck2.layers):
        assert l1.eos_mode == l2.eos_mode
        assert l1.eos_cond == l2.eos_cond
        assert l1.shot_s == l2.shot_s
        assert l1.stdcur == l2.stdcur
        assert l1.scale == l2.scale


def test_example3_structure():
    """example3 固有の構造: ラベル付き配列・トップレベル CHIP 配列の A 割付。"""
    deck = parse_jdf(open(EXAMPLE3).read())
    labeled = [a for a in deck.arrays if a.label is not None]
    unlabeled = [a for a in deck.arrays if a.label is None]
    assert len(deck.arrays) == 17
    assert len(labeled) == 14          # 1:〜14: のネスティング用配列
    assert len(unlabeled) == 3         # M / AFM_Y / CHIP(無コメント)
    assert [a.label for a in labeled] == list(range(1, 15))
    # トップレベル CHIP 配列(3番目・無ラベル)は A(1)〜A(14) のみ割付
    chip = unlabeled[2]
    assert len(chip.assigns) == 71
    assert {c.kind for c in chip.assigns.values()} == {"A"}
    assert {c.number for c in chip.assigns.values()} == set(range(1, 15))
    # CHIP 配列の全セルにテーブル(S12〜S15)が指定されている
    assert {c.table for c in chip.assigns.values()} == {"S12", "S13", "S14", "S15"}
    # ラベル付き配列内の割付はテーブル未指定(例: 配列1 は P(3)/P(4))
    a1 = labeled[0]
    assert len(a1.assigns) == 5
    assert all(c.table is None for c in a1.assigns.values())
    assert {c.number for c in a1.assigns.values()} == {3, 4}


def test_generated_structure(example):
    """生成結果の構造: 共通部 → レイヤー部 → END。"""
    deck = parse_jdf(open(example).read())
    lines = generate_jdf(deck).splitlines()
    assert lines[0].startswith(";")            # ヘッダコメント
    assert lines[-1] == "END"
    job_i = next(i for i, l in enumerate(lines) if l.startswith("JOB"))
    glmpos_i = next(i for i, l in enumerate(lines) if l.startswith("GLMPOS"))
    path_i = next(i for i, l in enumerate(lines) if l.startswith("PATH"))
    pend_i = next(i for i, l in enumerate(lines) if l.startswith("PEND"))
    layer_i = next(i for i, l in enumerate(lines) if l.startswith("LAYER"))
    assert job_i < glmpos_i < path_i < pend_i < layer_i
    # MODULAT は各レイヤー末尾に全テーブル
    # (空行・セパレータ・セクション名コメントを除外してから位置検証)
    content = [l for l in lines if l.strip() and not l.lstrip().startswith(";")]
    n_mod = len(deck.modulats)
    for i, l in enumerate(content):
        if l.startswith("LAYER"):
            j = i + 1
            while not content[j].startswith(("LAYER", "END")):
                j += 1
            assert all("MODULAT" in x for x in content[j - n_mod:j])


def test_generated_comments_not_in_header(example):
    """生成物のセパレータ/セクション名コメントが再 parse で
    header_comments に混入しない(JOB より前に装飾を置かないため)。"""
    deck1 = parse_jdf(open(example).read())
    deck2 = parse_jdf(generate_jdf(deck1))
    assert deck2.header_comments == deck1.header_comments
    # セパレータ等のスタンドアロンコメントは警告も出さない
    assert deck2.parse_warnings == []
