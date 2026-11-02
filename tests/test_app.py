import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["TERMHIGHLIGHT_DB"] = _tmp.name

import app as app_module  # noqa: E402


class TermHighlightTest(unittest.TestCase):
    def setUp(self):
        app_module.init_db()
        self.client = app_module.app.test_client()
        with app_module.app.app_context():
            conn = app_module.get_db()
            conn.execute("DELETE FROM terms")
            conn.commit()

    def add(self, term, meaning=""):
        return self.client.post("/terms", data={"term": term, "meaning": meaning})

    def terms_in_db(self):
        with app_module.app.app_context():
            return [dict(r) for r in app_module.list_terms(app_module.get_db())]

    def test_healthz(self):
        res = self.client.get("/healthz")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "ok")

    def test_index_empty_state(self):
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn("マイ用語集ハイライト", body)
        self.assertIn("まだ用語が登録されていません", body)
        self.assertIn("登録済みの用語（0件）", body)

    def test_add_term(self):
        res = self.add("自己調整学習", "学習者が自らの学習過程を調整すること")
        self.assertEqual(res.status_code, 302)
        rows = self.terms_in_db()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["term"], "自己調整学習")
        self.assertEqual(rows[0]["meaning"], "学習者が自らの学習過程を調整すること")
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn("自己調整学習", body)
        self.assertIn("登録済みの用語（1件）", body)

    def test_add_empty_term_ignored(self):
        self.client.post("/terms", data={"term": "  ", "meaning": "x"})
        self.assertEqual(self.terms_in_db(), [])

    def test_add_duplicate_term_updates_meaning(self):
        self.add("Flask", "古い意味")
        self.add("Flask", "PythonのWebフレームワーク")
        rows = self.terms_in_db()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["meaning"], "PythonのWebフレームワーク")

    def test_delete_term(self):
        self.add("削除対象", "意味")
        tid = self.terms_in_db()[0]["id"]
        res = self.client.post(f"/terms/{tid}/delete")
        self.assertEqual(res.status_code, 302)
        self.assertEqual(self.terms_in_db(), [])

    def test_delete_missing_term_404(self):
        res = self.client.post("/terms/9999/delete")
        self.assertEqual(res.status_code, 404)

    def test_highlight_single(self):
        html_out, found = app_module.highlight_text(
            "自己調整学習は大切です", [{"term": "自己調整学習", "meaning": "SRL"}]
        )
        self.assertEqual(html_out, "<mark>自己調整学習</mark>は大切です")
        self.assertEqual(found, [{"term": "自己調整学習", "meaning": "SRL"}])

    def test_highlight_multiple_and_repeated(self):
        terms = [
            {"term": "学習", "meaning": "学ぶこと"},
            {"term": "記録", "meaning": "書き留めること"},
        ]
        html_out, found = app_module.highlight_text("学習の記録と学習", terms)
        self.assertEqual(
            html_out, "<mark>学習</mark>の<mark>記録</mark>と<mark>学習</mark>"
        )
        # 見つかった用語一覧は出現順で重複なし
        self.assertEqual([f["term"] for f in found], ["学習", "記録"])

    def test_highlight_longest_term_wins(self):
        terms = [
            {"term": "学習", "meaning": "短い方"},
            {"term": "自己調整学習", "meaning": "長い方"},
        ]
        html_out, found = app_module.highlight_text("自己調整学習と学習", terms)
        self.assertEqual(html_out, "<mark>自己調整学習</mark>と<mark>学習</mark>")
        self.assertEqual([f["term"] for f in found], ["自己調整学習", "学習"])

    def test_highlight_no_terms_registered(self):
        html_out, found = app_module.highlight_text("ただの文章です", [])
        self.assertEqual(html_out, "ただの文章です")
        self.assertEqual(found, [])

    def test_highlight_no_match(self):
        html_out, found = app_module.highlight_text(
            "関係ない文章", [{"term": "自己調整学習", "meaning": "SRL"}]
        )
        self.assertEqual(html_out, "関係ない文章")
        self.assertEqual(found, [])

    def test_highlight_empty_text(self):
        html_out, found = app_module.highlight_text(
            "", [{"term": "学習", "meaning": "学ぶこと"}]
        )
        self.assertEqual(html_out, "")
        self.assertEqual(found, [])

    def test_highlight_escapes_html_in_text(self):
        html_out, found = app_module.highlight_text(
            "<script>alert(1)</script>と学習",
            [{"term": "学習", "meaning": "学ぶこと"}],
        )
        self.assertNotIn("<script>", html_out)
        self.assertIn("&lt;script&gt;", html_out)
        self.assertIn("<mark>学習</mark>", html_out)

    def test_highlight_escapes_html_in_term(self):
        html_out, found = app_module.highlight_text(
            "a<b>c", [{"term": "<b>", "meaning": "太字タグ"}]
        )
        self.assertEqual(html_out, "a<mark>&lt;b&gt;</mark>c")
        self.assertEqual(found[0]["term"], "<b>")

    def test_highlight_via_post_shows_meanings(self):
        self.add("自己調整学習", "学習者が自らの学習過程を調整すること")
        self.add("フィードバック", "結果を伝えて改善につなげること")
        body = self.client.post(
            "/highlight", data={"text": "自己調整学習にはフィードバックが効く"}
        ).get_data(as_text=True)
        self.assertIn("<mark>自己調整学習</mark>", body)
        self.assertIn("<mark>フィードバック</mark>", body)
        self.assertIn("学習者が自らの学習過程を調整すること", body)
        self.assertIn("見つかった用語（2件）", body)

    def test_highlight_via_post_escapes_input(self):
        body = self.client.post(
            "/highlight", data={"text": "<img src=x onerror=alert(1)>"}
        ).get_data(as_text=True)
        self.assertNotIn("<img src=x", body)
        self.assertIn("&lt;img", body)

    def test_term_and_meaning_escaped_in_list(self):
        self.add("<b>太字</b>", "<i>意味</i>")
        body = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("<b>太字</b>", body)
        self.assertIn("&lt;b&gt;太字&lt;/b&gt;", body)


if __name__ == "__main__":
    unittest.main()
