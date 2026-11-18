# -*- coding: utf-8 -*-
"""子句切分、候选词与字符 n-gram。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from text import candidate_terms, char_ngrams, normalize_name, segments


class TextFeatureTests(unittest.TestCase):
    def test_segments_keep_chinese_clauses(self):
        self.assertEqual(
            segments("技术制图 比例；第1部分：字体"),
            ["技术制图", "比例", "第1部分", "字体"],
        )

    def test_segments_normalize_width_and_case(self):
        self.assertEqual(segments("ＡＢＣ　标准"), ["abc", "标准"])

    def test_candidate_terms_include_substrings_and_ascii(self):
        terms = candidate_terms("六角头螺栓 HB 123")
        self.assertIn("六角头螺栓", terms)
        self.assertIn("螺栓", terms)
        self.assertIn("六角", terms)
        self.assertIn("hb", terms)

    def test_candidate_terms_keep_alphanumeric_codes(self):
        self.assertIn("2a12", candidate_terms("2A12铝合金板材"))
        self.assertIn("h6132", candidate_terms("H61-32铜合金"))
        self.assertIn("lan", candidate_terms("L-AN全合成油"))
        self.assertIn("1cr18ni9ti", candidate_terms("1Cr18Ni9Ti 不锈钢棒"))

    def test_candidate_terms_do_not_join_punctuated_codes(self):
        terms = candidate_terms("液压油（L-HL、L-HM、L-HV）")
        self.assertIn("lhl", terms)
        self.assertIn("lhm", terms)
        self.assertNotIn("lhllhm", terms)
        self.assertNotIn("lhllhmlhv", terms)

    def test_candidate_terms_respect_length_bounds(self):
        terms = candidate_terms("一二三四五六七")
        self.assertTrue(terms)
        for term in terms:
            self.assertGreaterEqual(len(term), 2)
            self.assertLessEqual(len(term), 6)

    def test_candidate_terms_clamp_invalid_bounds(self):
        self.assertIn("钢", candidate_terms("钢板", min_length=0, max_length=1))

    def test_candidate_terms_live_in_normalized_space(self):
        name = "H61-32铜合金 2A12板材"
        normalized = normalize_name(name)
        for term in candidate_terms(name):
            self.assertIn(term, normalized)

    def test_char_ngrams_remove_spaces_and_punctuation(self):
        grams = char_ngrams("六角头 螺栓")
        self.assertIn("六角", grams)
        self.assertIn("螺栓", grams)
        self.assertIn("六角头", grams)

    def test_char_ngrams_respect_sizes_argument(self):
        self.assertEqual(char_ngrams("abc", sizes=(3,)), ["abc"])
        self.assertEqual(char_ngrams("abc", sizes=(0, 3)), ["abc"])

    def test_empty_and_short_inputs(self):
        self.assertEqual(candidate_terms(""), [])
        self.assertEqual(char_ngrams("钢"), [])

    def test_candidate_terms_exclude_punctuation_and_pure_digits(self):
        terms = candidate_terms("金属材料（板材） HB 123")
        self.assertIn("金属材料", terms)
        self.assertIn("板材", terms)
        self.assertIn("hb", terms)
        self.assertNotIn("123", terms)
        for term in terms:
            self.assertFalse(
                any(char in term for char in "，,。.;；、:：-—_/\\()（）"),
                term,
            )


if __name__ == "__main__":
    unittest.main()
