"""parser の単体テスト。"""
import pytest

from jdf import parse_jdf, ParseError, KIND_ARRAY


MINIMAL = """\
JOB/W ,3,0
GLMPOS P=(-27600,450),Q=(30000,450),R=(-20400,22050),S=(-20400,-21150)
PATH PITCH
PEND
LAYER 1
END
"""


class TestLineSpanning:
    def test_glmp_next_line(self):
        """GLMP 単独行の次行の裸パラメータを結合。"""
        text = MINIMAL.replace("PATH PITCH", "GLMP\n3,500\nPATH PITCH")
        deck = parse_jdf(text)
        assert deck.glmp == [3, 500]

    def test_glmp_same_line(self):
        text = MINIMAL.replace("PATH PITCH", "GLMP    3,500\nPATH PITCH")
        deck = parse_jdf(text)
        assert deck.glmp == [3, 500]

    def test_eos_params_after_with_shot_between(self):
        """例1 LAYER1 形式: EOS の2行後(間に SHOT)の裸パラメータを結合。"""
        text = MINIMAL.replace(
            "LAYER 1",
            "LAYER 1\nEOS\n SHOT A,40\n3,'M_100_1000pA_2'")
        deck = parse_jdf(text)
        layer = deck.layers[0]
        assert layer.eos_mode == 3
        assert layer.eos_cond == "M_100_1000pA_2"
        assert layer.shot_s == 40

    def test_eos_params_before(self):
        """パラメータ行が EOS より前に来るケース。"""
        text = MINIMAL.replace(
            "LAYER 1", "LAYER 1\n2,'optstd3i'\nEOS")
        deck = parse_jdf(text)
        assert deck.layers[0].eos_mode == 2
        assert deck.layers[0].eos_cond == "optstd3i"

    def test_glmp_params_before(self):
        text = MINIMAL.replace("PATH PITCH", "3,500\nGLMP\nPATH PITCH")
        deck = parse_jdf(text)
        assert deck.glmp == [3, 500]


class TestComments:
    def test_header_comments(self):
        text = ";LINE1\n; LINE2\n" + MINIMAL
        deck = parse_jdf(text)
        assert deck.header_comments == ["LINE1", " LINE2"]

    def test_array_comment(self):
        text = MINIMAL.replace(
            "PEND", "1: ARRAY (1500,1,3000)/(2000,1,4000)      ; M\nAEND\nPEND")
        deck = parse_jdf(text)
        assert deck.arrays[0].comment == "M"

    def test_standalone_comment_discarded(self):
        """JOB 以降のスタンドアロンコメントは警告なしで静かにスキップ。"""
        text = MINIMAL.replace("PATH PITCH", ";SHOT MAP===\nPATH PITCH")
        deck = parse_jdf(text)
        assert deck.path_name == "PITCH"
        # 警告は記録されず、モデルにも影響しない
        assert not any("コメント" in w for w in deck.parse_warnings)
        assert deck.header_comments == []
        clean = parse_jdf(MINIMAL)
        assert [t.name for t in deck.modulats] == [t.name for t in clean.modulats]
        assert len(deck.layers) == len(clean.layers)

    def test_pend_comment_direct(self):
        """PEND;==== のようなコメント直結を許容。"""
        text = MINIMAL.replace("PEND", "PEND;========================================")
        deck = parse_jdf(text)
        assert deck is not None


class TestJobName:
    def test_job_name_line(self):
        text = ";header\nMaruyama\n" + MINIMAL
        deck = parse_jdf(text)
        assert deck.job_name == "Maruyama"
        assert deck.header_comments == ["header"]

    def test_no_job_name(self):
        deck = parse_jdf(MINIMAL)
        assert deck.job_name == ""

    def test_job_name_in_job_param(self):
        text = MINIMAL.replace("JOB/W ,3,0", "JOB/W 'JBNAME',3,0")
        deck = parse_jdf(text)
        assert deck.job_name == "JBNAME"


class TestArrayAssign:
    def test_labeled_array(self):
        text = MINIMAL.replace(
            "PEND", "12: ARRAY (500,3,1000)/(4250,14,250)\nAEND\nPEND")
        deck = parse_jdf(text)
        assert deck.arrays[0].label == 12
        assert deck.arrays[0].m == 3
        assert deck.arrays[0].n == 14

    def test_range_assign_expansion(self):
        """範囲指定 (21-22,21-22) は4セルに展開。"""
        text = MINIMAL.replace(
            "PEND",
            "ARRAY (-36900,42,1800)/(36900,42,1800)\n"
            "ASSIGN P(3)-> ((21-22,21-22),S225)\nAEND\nPEND")
        deck = parse_jdf(text)
        a = deck.arrays[0]
        assert len(a.assigns) == 4
        for jk in [(21, 21), (22, 21), (21, 22), (22, 22)]:
            assert a.assigns[jk].number == 3
            assert a.assigns[jk].table == "S225"

    def test_assign_no_table(self):
        text = MINIMAL.replace(
            "PEND",
            "ARRAY (1500,1,3000)/(2000,1,4000)\n"
            "ASSIGN P(1) -> (1,1)\nAEND\nPEND")
        deck = parse_jdf(text)
        cell = deck.arrays[0].assigns[(1, 1)]
        assert cell.number == 1
        assert cell.table is None

    def test_assign_later_wins(self):
        """同一配列点への複数割付は後着優先。"""
        text = MINIMAL.replace(
            "PEND",
            "ARRAY (0,2,100)/(0,2,100)\n"
            "ASSIGN P(1)-> (1,1)\n"
            "ASSIGN P(2)-> (1,1)\nAEND\nPEND")
        deck = parse_jdf(text)
        assert deck.arrays[0].assigns[(1, 1)].number == 2

    def test_assign_array_kind(self):
        text = MINIMAL.replace(
            "PEND",
            "ARRAY (-34500,23,3000)/(24000,14,4000)\n"
            "ASSIGN A(3)-> ((12,1),S11B)\nAEND\nPEND")
        deck = parse_jdf(text)
        cell = deck.arrays[0].assigns[(12, 1)]
        assert cell.kind == KIND_ARRAY
        assert cell.number == 3

    def test_assign_star(self):
        text = MINIMAL.replace(
            "PEND",
            "ARRAY (0,3,100)/(0,2,100)\n"
            "ASSIGN P(1)-> ((*,1),T1)\nAEND\nPEND")
        deck = parse_jdf(text)
        assert len(deck.arrays[0].assigns) == 3


class TestModulat:
    def test_modulat_merge_across_layers(self):
        """同名テーブルは最初の出現のみ採用。"""
        text = MINIMAL.replace(
            "LAYER 1\nEND",
            "LAYER 1\nS11M: MODULAT((0,300)) ; MARK\n"
            "LAYER 2\nS11M: MODULAT((0,999))\nEND")
        deck = parse_jdf(text)
        assert len(deck.modulats) == 1
        assert deck.modulats[0].pairs == [(0, 300)]
        assert deck.modulats[0].comment == "MARK"


class TestRobustness:
    def test_unknown_command_skipped(self):
        text = MINIMAL.replace("PEND", "FOOBAR 1,2,3\nPEND")
        deck = parse_jdf(text)
        assert any("未知コマンド" in w for w in deck.parse_warnings)

    def test_missing_job(self):
        with pytest.raises(ParseError):
            parse_jdf("PATH PITCH\nPEND\nEND\n")

    def test_missing_end(self):
        with pytest.raises(ParseError):
            parse_jdf("JOB/W ,3,0\nPATH PITCH\nPEND\n")

    def test_spprm_attached_to_chip(self):
        text = MINIMAL.replace(
            "LAYER 1", "LAYER 1\n P(3) 'PAN01A_M1.v30'\n  SPPRM 8.0,,,,,1")
        deck = parse_jdf(text)
        chip = deck.layers[0].chips[0]
        assert chip.pseudo == 3
        assert chip.filename == "PAN01A_M1.v30"
        assert chip.spprm == ["8.0", "", "", "", "", "1"]

    def test_scale_single_value(self):
        text = MINIMAL.replace("LAYER 1", "LAYER 1\nSCALE 1.0099")
        deck = parse_jdf(text)
        assert deck.layers[0].scale == [1.0099, 1.0099]


class TestCleanComment:
    def test_decoration_comment_discarded(self):
        """`;-----` のような装飾のみのインラインコメントは破棄。"""
        from jdf import parse_jdf
        text = ("JOB ,4,0\n"
                "LAYER 1 ;---------------------------------------------------\n"
                "P(1) 'A.v30' ;==\n"
                "S11M: MODULAT((0,1)) ; --- ---\n"
                "END\n")
        deck = parse_jdf(text)
        assert deck.layers[0].comment == ""
        assert deck.layers[0].chips[0].comment == ""
        assert deck.modulats[0].comment == ""

    def test_real_comment_kept(self):
        """装飾を含むが実内容のあるコメントは保持。"""
        from jdf import parse_jdf
        text = ("JOB ,4,0\n"
                "ARRAY (0,1,1000)/(0,1,1000) ; - M1 -\n"
                "AEND\nEND\n")
        deck = parse_jdf(text)
        assert deck.arrays[0].comment == "- M1 -"
