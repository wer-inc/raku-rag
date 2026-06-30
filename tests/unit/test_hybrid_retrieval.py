import unittest

from raku_rag.core.hybrid_retrieval import lexical_match_score, lexical_query_terms


class TestHybridRetrievalLexical(unittest.TestCase):
    def test_lexical_terms_keep_short_equipment_codes_and_cjk_bigrams(self) -> None:
        terms = set(
            lexical_query_terms(
                "モータ M8 端子台の締付トルクと、基礎ボルト M16 の締付トルクを教えて"
            )
        )

        self.assertIn("m8", terms)
        self.assertIn("m16", terms)
        self.assertIn("トル", terms)
        self.assertIn("締付", terms)

    def test_japanese_threshold_question_matches_demo_quality_standard(self) -> None:
        query = "めっき部品のキズ、打痕、バリの合否判定しきい値を短く整理して"
        matching = (
            "外観欠陥判定基準書 QJC-0088。キズは長さ0.5mm以下、"
            "打痕は直径0.3mm以下、バリは高さ0.1mm以下を合格とする。"
        )
        unrelated = "圧力容器の耐圧試験は水圧試験で実施し、保持時間は30分とする。"

        self.assertGreater(lexical_match_score(query, matching), 0.7)
        self.assertEqual(lexical_match_score(query, unrelated), 0.0)


if __name__ == "__main__":
    unittest.main()
