"""マイ用語集ハイライト termhighlight

自分用用語集に登録した単語とその意味を覚えておき、文章を貼り付けると
登録済みの用語が文章中でハイライト（<mark>）表示され、あわせて
見つかった用語の意味一覧が示される、個人用の読解補助ツール。
外部 API は使わず、用語は SQLite に保存する。単一ファイル Flask + SQLite。
"""
import html
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, g, jsonify, redirect, render_template_string, request, url_for, abort

app = Flask(__name__)
JST = ZoneInfo("Asia/Tokyo")
DB_PATH = os.environ.get("TERMHIGHLIGHT_DB", os.path.join(os.path.dirname(__file__), "termhighlight.db"))

NOTE = "無料プランでは SQLite のデータが再デプロイ等で消える場合があります。大事な用語集は別途メモしておいてください。"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS terms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term TEXT NOT NULL UNIQUE,
            meaning TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        """
    )
    db.commit()
    db.close()


def now_str():
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M")


def list_terms(db):
    return db.execute("SELECT * FROM terms ORDER BY term").fetchall()


def highlight_text(text, terms):
    """文章中の用語を <mark> でハイライトした HTML と、見つかった用語の一覧を返す。

    terms は {"term": ..., "meaning": ...} の辞書（または sqlite3.Row）の列。
    各位置で最長の用語から照合するので、長い用語が優先され、部分的な
    二重マッチは起きない。本文は必ず HTML エスケープしてから組み立てる。
    """
    words = sorted({t["term"] for t in terms if t["term"]}, key=len, reverse=True)
    meanings = {t["term"]: t["meaning"] for t in terms}
    if not text:
        return "", []
    if not words:
        return html.escape(text), []
    out = []
    matched = []
    i = 0
    while i < len(text):
        hit = None
        for w in words:
            if text.startswith(w, i):
                hit = w
                break
        if hit is not None:
            out.append(f"<mark>{html.escape(hit)}</mark>")
            if hit not in matched:
                matched.append(hit)
            i += len(hit)
        else:
            out.append(html.escape(text[i]))
            i += 1
    found = [{"term": w, "meaning": meanings.get(w, "")} for w in matched]
    return "".join(out), found


INDEX = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>マイ用語集ハイライト</title>
<style>body{font-family:sans-serif;max-width:720px;margin:2em auto;padding:0 1em}
textarea{width:100%}mark{background:#fff176;padding:0 .1em}
.result{background:#f9f9f4;border:1px solid #ddd;padding:1em;border-radius:6px;white-space:pre-wrap}
.note{background:#fff3cd;border:1px solid #d9b84a;padding:.8em;border-radius:6px}</style>
</head><body>
<h1>マイ用語集ハイライト</h1>
<p>自分用の用語集に単語と意味を登録しておくと、文章を貼り付けたときに登録済みの用語がハイライトされ、意味も一緒に確認できます。</p>
<p class="note">{{ note }}</p>

<h2>用語を登録する</h2>
<form method="post" action="{{ url_for('add_term') }}">
  <label>用語 <input type="text" name="term" required placeholder="例：自己調整学習"></label><br>
  <label>意味 <input type="text" name="meaning" size="50" placeholder="例：学習者が自らの学習過程を調整すること"></label><br>
  <button type="submit">登録する</button>
</form>

<h2>登録済みの用語（{{ terms|length }}件）</h2>
<ul>
{% for t in terms %}
<li><strong>{{ t.term }}</strong>：{{ t.meaning }}
  <form method="post" action="{{ url_for('delete_term', tid=t.id) }}" style="display:inline"><button>削除</button></form></li>
{% else %}<li>まだ用語が登録されていません</li>{% endfor %}
</ul>

<h2>文章をハイライトする</h2>
<form method="post" action="{{ url_for('highlight') }}">
  <textarea name="text" rows="8" placeholder="ここに文章を貼り付けてください">{{ input_text }}</textarea><br>
  <button type="submit">ハイライトする</button>
</form>

{% if result_html is not none %}
<h2>結果</h2>
<div class="result">{{ result_html|safe }}</div>
<h3>見つかった用語（{{ found|length }}件）</h3>
<ul>
{% for f in found %}
<li><strong>{{ f.term }}</strong>：{{ f.meaning }}</li>
{% else %}<li>登録済みの用語は見つかりませんでした</li>{% endfor %}
</ul>
{% endif %}
</body></html>"""


def base_context(db):
    return {
        "note": NOTE,
        "terms": list_terms(db),
        "input_text": "",
        "result_html": None,
        "found": [],
    }


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/")
def index():
    db = get_db()
    return render_template_string(INDEX, **base_context(db))


@app.route("/terms", methods=["POST"])
def add_term():
    term = (request.form.get("term") or "").strip()
    meaning = (request.form.get("meaning") or "").strip()
    if term:
        db = get_db()
        db.execute(
            "INSERT INTO terms(term, meaning, created_at) VALUES(?, ?, ?) "
            "ON CONFLICT(term) DO UPDATE SET meaning = excluded.meaning",
            (term, meaning, now_str()),
        )
        db.commit()
    return redirect(url_for("index"))


@app.route("/terms/<int:tid>/delete", methods=["POST"])
def delete_term(tid):
    db = get_db()
    row = db.execute("SELECT id FROM terms WHERE id = ?", (tid,)).fetchone()
    if row is None:
        abort(404)
    db.execute("DELETE FROM terms WHERE id = ?", (tid,))
    db.commit()
    return redirect(url_for("index"))


@app.route("/highlight", methods=["POST"])
def highlight():
    text = request.form.get("text", "")
    db = get_db()
    terms = list_terms(db)
    result_html, found = highlight_text(text, terms)
    ctx = base_context(db)
    ctx["input_text"] = text
    ctx["result_html"] = result_html
    ctx["found"] = found
    return render_template_string(INDEX, **ctx)


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
