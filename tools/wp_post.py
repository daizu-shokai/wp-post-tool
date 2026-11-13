#!/usr/bin/env python3
"""だいず商会 WordPress投稿ツール（標準ライブラリのみ）

使い方:
  python tools/wp_post.py --test                 接続テスト（ログインできるか確認）
  python tools/wp_post.py --test-draft           テスト用の下書きを1本作る
  python tools/wp_post.py articles/xxx.md        記事ファイルを「下書き」で投稿
      --title "タイトル"   （省略時は1行目の # 見出しを使う）
      --update 123         既存の投稿ID 123 を上書き更新（下書きのまま）
      --featured images/eyecatch.png   アイキャッチ画像を設定
  python tools/wp_post.py --upload images/xxx.png   画像を1枚アップロードしてURLを表示

記事中の ![説明](images/xxx.png) のようなローカル画像は、自動でアップロードしてURLに置き換える。

安全のため、このツールは常に「下書き(draft)」で送る。公開は社長が管理画面で行う。
"""
import argparse, base64, html, json, os, re, sys, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    env_path = ROOT / ".env"
    if not env_path.exists():
        sys.exit(f"[NG] {env_path} がありません。.env.example をコピーして作ってください。")
    env = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("WP_URL", "WP_USER", "WP_APP_PASSWORD"):
        if not env.get(k) or "ここに" in env[k]:
            sys.exit(f"[NG] .env の {k} が未設定です。")
    env["WP_URL"] = env["WP_URL"].rstrip("/")
    if not env["WP_URL"].startswith("https://"):
        sys.exit("[NG] WP_URL が https:// ではありません。ログイン情報が平文で流れるため送信を中止しました。")
    return env


def api(env, method, path, data=None):
    url = f"{env['WP_URL']}/wp-json/wp/v2{path}"
    token = base64.b64encode(f"{env['WP_USER']}:{env['WP_APP_PASSWORD']}".encode()).decode()
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "daizu-shokai-wp-post/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        if e.code == 401 and "rest_not_logged_in" in detail:
            hint = ("認証ヘッダーがWordPressまで届いていない（パスワード違いではない）。"
                    ".htaccess 先頭に `SetEnvIf Authorization \"(.*)\" HTTP_AUTHORIZATION=$1` "
                    "または `CGIPassAuth On` を追加して再テスト。")
            sys.exit(f"[NG] HTTP {e.code} {method} {path}\n{hint}\n{detail}")
        hint = {
            401: "ユーザー名かアプリケーションパスワードが違う可能性（incorrect_password / invalid_username）。",
            403: "WAF・国外アクセス制限・セキュリティプラグインに止められた可能性。"
                 "エックスサーバーの『WordPressセキュリティ設定』とCloudSecure WP Securityを確認。",
            404: "URLが違うか、REST APIが無効化されている可能性。",
        }.get(e.code, "")
        sys.exit(f"[NG] HTTP {e.code} {method} {path}\n{hint}\n{detail}")
    except urllib.error.URLError as e:
        sys.exit(f"[NG] 接続できません: {e.reason}（URL・ネット接続・SSL反映待ちを確認）")


MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml"}


def upload_media(env, path, alt=""):
    """画像をメディアライブラリにアップロードし、(id, url) を返す。"""
    path = Path(path)
    if not path.is_absolute():
        path = (ROOT / path) if (ROOT / path).exists() else path.resolve()
    if not path.exists():
        sys.exit(f"[NG] 画像が見つかりません: {path}")
    mime = MIME.get(path.suffix.lower())
    if not mime:
        sys.exit(f"[NG] 対応していない画像形式です: {path.suffix}（png/jpg/gif/webp）")
    url = f"{env['WP_URL']}/wp-json/wp/v2/media"
    token = base64.b64encode(f"{env['WP_USER']}:{env['WP_APP_PASSWORD']}".encode()).decode()
    from urllib.parse import quote
    req = urllib.request.Request(url, data=path.read_bytes(), method="POST", headers={
        "Authorization": f"Basic {token}",
        "Content-Type": mime,
        # WordPressは filename*= 形式を受け付けないため、filename="..." で送る（日本語名はURLエンコード）
        "Content-Disposition": f'attachment; filename="{quote(path.name)}"',
        "User-Agent": "daizu-shokai-wp-post/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        hint = "SVGはWordPressの初期設定では受け付けない。PNGに変換して再試行。" if mime == "image/svg+xml" else ""
        sys.exit(f"[NG] 画像アップロード失敗 HTTP {e.code}: {path.name}\n{hint}\n{detail}")
    if alt:
        api(env, "POST", f"/media/{res['id']}", {"alt_text": alt})
    print(f"[OK] 画像アップロード: ID={res['id']} {res['source_url']}")
    return res["id"], res["source_url"]


_IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")


def upload_local_images(env, md, base_dir):
    """Markdown中のローカル画像をアップロードしてURLに置き換える。同じ画像は1回だけ送る。"""
    done = {}
    def rep(m):
        alt, src = m.group(1), m.group(2)
        if src.startswith(("http://", "https://")):
            return m.group(0)
        p = (base_dir / src).resolve()
        if not p.exists():
            p = (ROOT / src).resolve()
        if str(p) not in done:
            done[str(p)] = upload_media(env, p, alt)[1]
        return f"![{alt}]({done[str(p)]})"
    return _IMG_RE.sub(rep, md)


def inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    s = re.sub(r"!\[([^\]]*)\]\((https?://[^)\s]+)\)", r'<img src="\2" alt="\1">', s)
    s = re.sub(r"(?<!!)\[(.+?)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', s)
    return s


def md_to_html(md):
    """最低限のMarkdown変換（見出し・段落・箇条書き・番号リスト・太字・リンク・コード・引用）。
    .html ファイルを渡した場合は変換しない。"""
    out, para, lst, code, table = [], [], None, None, []
    def flush():
        nonlocal para, lst, table
        if para:
            out.append("<p>" + "<br>".join(inline(p) for p in para) + "</p>"); para = []
        if lst:
            out.append(f"</{lst}>"); lst = None
        if table:
            rows = [[c.strip() for c in r.strip().strip("|").split("|")] for r in table
                    if not re.fullmatch(r"\s*\|?[\s:|-]+\|?\s*", r)]
            head, body = rows[0], rows[1:]
            out.append("<figure class=\"wp-block-table\"><table><thead><tr>"
                       + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body)
                       + "</tbody></table></figure>")
            table = []
    for line in md.splitlines():
        # コードブロック（```）はそのまま <pre><code> に入れる
        if code is not None:
            if line.strip().startswith("```"):
                out.append("<pre class=\"wp-block-code\"><code>" + html.escape("\n".join(code), quote=False) + "</code></pre>")
                code = None
            else:
                code.append(line)
            continue
        if line.strip().startswith("```"):
            flush(); code = []; continue
        # 1行のHTMLコメント（制作メモ）は投稿しない
        if re.fullmatch(r"\s*<!--.*-->\s*", line):
            continue
        # 表
        if line.lstrip().startswith("|"):
            if para or lst: flush()
            table.append(line); continue
        elif table:
            flush()
        m_h = re.match(r"^(#{2,6})\s+(.*)", line)
        m_ul = re.match(r"^\s*[-*]\s+(.*)", line)
        m_ol = re.match(r"^\s*\d+\.\s+(.*)", line)
        if not line.strip():
            flush()
        elif m_h:
            flush(); n = len(m_h.group(1)); out.append(f"<h{n}>{inline(m_h.group(2))}</h{n}>")
        elif m_ul or m_ol:
            tag = "ul" if m_ul else "ol"
            if para: flush()
            if lst != tag:
                if lst: out.append(f"</{lst}>")
                out.append(f"<{tag}>"); lst = tag
            out.append(f"<li>{inline((m_ul or m_ol).group(1))}</li>")
        elif re.fullmatch(r"\s*!\[[^\]]*\]\(https?://[^)\s]+\)\s*", line):
            flush(); out.append(f"<figure>{inline(line.strip())}</figure>")
        elif line.startswith(">"):
            flush(); out.append(f"<blockquote><p>{inline(line.lstrip('> '))}</p></blockquote>")
        else:
            if lst: flush()
            para.append(line)
    if code is not None:
        out.append("<pre class=\"wp-block-code\"><code>" + html.escape("\n".join(code), quote=False) + "</code></pre>")
    flush()
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="だいず商会 WordPress投稿ツール")
    ap.add_argument("file", nargs="?")
    ap.add_argument("--title")
    ap.add_argument("--update", type=int)
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--test-draft", action="store_true")
    ap.add_argument("--upload", metavar="IMAGE")
    ap.add_argument("--featured", metavar="IMAGE")
    a = ap.parse_args()
    env = load_env()

    if a.test:
        me = api(env, "GET", "/users/me?context=edit")
        print(f"[OK] ログイン成功: {me.get('name')}（権限: {', '.join(me.get('roles', []))}）")
        return

    if a.upload:
        upload_media(env, a.upload)
        return

    if a.test_draft:
        title, content = "【接続テスト】Claude Codeからの下書き", (
            "<p>この下書きは、だいず商会のClaude Codeから自動で投稿されました。確認できたら削除してください。</p>")
    else:
        if not a.file:
            ap.error("記事ファイルを指定してください")
        p = Path(a.file)
        text = p.read_text(encoding="utf-8")
        title = a.title
        if not title:
            m = re.match(r"^#\s+(.+)", text)
            if not m:
                sys.exit("[NG] タイトルがありません。--title を付けるか、1行目を『# タイトル』にしてください。")
            title, text = m.group(1).strip(), text[m.end():].lstrip()
        if p.suffix.lower() in (".html", ".htm"):
            content = text
        else:
            text = upload_local_images(env, text, p.resolve().parent)
            content = md_to_html(text)

    payload = {"title": title, "content": content, "status": "draft"}
    if a.featured:
        payload["featured_media"] = upload_media(env, a.featured)[0]
    res = api(env, "POST", f"/posts/{a.update}" if a.update else "/posts", payload)
    print(f"[OK] 下書き保存: ID={res['id']} 「{res['title']['raw'] if 'raw' in res['title'] else title}」")
    print(f"     編集画面: {env['WP_URL']}/wp-admin/post.php?post={res['id']}&action=edit")


if __name__ == "__main__":
    main()
