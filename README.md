# wp-post-tool

Claude Code などのAIエージェントから、WordPressへ記事を **下書きで** 投稿するための小さなツールです。
Pythonの標準ライブラリだけで動きます（追加インストール不要）。

だいず商会（AI社員6人でブログを運営する実験）で実際に使っているものを公開しています。
作った経緯とつまずきは、ブログ記事にまとめています → [【実録】エックスサーバー契約からClaude CodeでWordPressに下書き投稿できるまで](https://daizu-shokai.com/2026/11/13/%e3%80%90%e5%ae%9f%e9%8c%b2%e3%80%91%e3%82%a8%e3%83%83%e3%82%af%e3%82%b9%e3%82%b5%e3%83%bc%e3%83%90%e3%83%bc%e5%a5%91%e7%b4%84%e3%81%8b%e3%82%89claude-code%e3%81%a7wordpress%e3%81%ab%e4%b8%8b%e6%9b%b8/)

## できること

- `--test`：WordPressにログインできるか確認する
- `--test-draft`：テスト用の下書きを1本作る
- Markdownの記事を下書きで投稿する（見出し・段落・箇条書き・表・コードブロック・太字・リンク・画像）
- 1行の `<!-- メモ -->` は投稿しない（制作メモを本文に残せる）
- 記事中のローカル画像 `![説明](images/xxx.png)` を自動でアップロードし、URLに置き換える
- `--featured` でアイキャッチ画像を設定する

## 安全のための設計

- **必ず下書き（draft）で送ります。** 公開は人が管理画面で行う前提です。
- **`https://` 以外のURLには送信しません。** ログイン情報（Basic認証）が平文で流れるのを防ぐためです。
- 接続には、管理者ではなく **「投稿者」権限の専用ユーザー** のアプリケーションパスワードを使うことをおすすめします。

## 必要なもの

- Python 3.8 以上
- WordPress 5.6 以上（アプリケーションパスワード機能）
- HTTPSで公開されているサイト

## 使い方

### 1. アプリケーションパスワードを発行する

WordPress管理画面の「ユーザー」→「プロフィール」→「アプリケーションパスワード」で発行します。
表示されるのは一度だけなので、控えておいてください。

### 2. `.env` を作る

`.env.example` をコピーして `.env` にし、サイトのURL・ユーザー名・アプリケーションパスワードを書きます。

### 3. 実行する

```
python tools/wp_post.py --test                      # 接続テスト
python tools/wp_post.py --test-draft                # テスト下書きを1本作る
python tools/wp_post.py articles/post.md            # 記事を下書きで投稿（1行目の「# 」がタイトル）
python tools/wp_post.py articles/post.md --title "タイトル" --featured images/eyecatch.png
python tools/wp_post.py articles/post.md --update 123   # 既存の下書きID 123 を上書き
python tools/wp_post.py --upload images/xxx.png     # 画像だけアップロード
```

## Claude Code で使うときのおすすめ設定

AIにパスワードの中身を読ませないよう、`.claude/settings.json` で `.env` の読み取りを禁止しておくと安心です。

```json
{
  "permissions": { "deny": ["Read(./.env)"] }
}
```

※ ファイルの読み取りは止まりますが、このツールが内部で `.env` を読むことは止まりません（意図どおりの動作です）。

## よくあるエラー

| 表示 | 原因と対処 |
|---|---|
| `HTTP 401` `rest_not_logged_in` | 認証ヘッダーがWordPressまで届いていません（パスワード違いではない）。`.htaccess` の先頭に `SetEnvIf Authorization "(.*)" HTTP_AUTHORIZATION=$1` を追加してください。エックスサーバーで実際に起きました。 |
| `HTTP 401` `incorrect_password` / `invalid_username` | ユーザー名かアプリケーションパスワードが違います。 |
| `HTTP 403` | サーバーのWAF、国外アクセス制限、セキュリティプラグインに止められています。 |
| 画像アップロードで失敗（SVG） | WordPressは初期設定でSVGを受け付けません。PNGに変換してください。 |

## 制限

- Markdownの変換は最小限です（入れ子のリストなどには未対応）。複雑なレイアウトは `.html` ファイルを渡すと、そのまま送ります。
- カテゴリ・タグの設定には未対応です。

## ライセンス

MIT License
