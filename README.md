# Instagram 自動投稿

Instagram MCP サーバー（[@luminarylane/instagram-mcp-server](https://github.com/luminarylane/instagram-mcp-server) v1.6.10）を使い、
`posts/queue/` に置いた投稿を Claude のスケジュールタスクで 1 件ずつ自動投稿する。

## 仕組み

```
posts/queue/<投稿ID>/01.jpg + caption.txt
        │  ① python scripts/post_queue.py next   … 検証 → GitHub に push → 公開URLを出力
        ▼
raw.githubusercontent.com/<repo>/<commit SHA>/...   ← Instagram はここから画像を取得
        │  ② MCP ツール ig_publish_photo / ig_publish_carousel
        ▼
Instagram に公開
        │  ③ python scripts/post_queue.py done <投稿ID> <media_id>
        ▼
posts/posted/<投稿ID>/ へ移動、posts/posted.jsonl に記録
```

Instagram Graph API はローカルファイルを受け付けず「公開URLの画像」しか投稿できないため、
このリポジトリを GitHub の **公開リポジトリ** にして画像置き場にしている。
キューに入れた画像・キャプションは投稿前でも GitHub 上で誰でも閲覧できる点に注意。

## 投稿の追加

1. `posts/queue/` に投稿ID のフォルダを作る。**フォルダ名の昇順に投稿される**ので
   `2026-10-14_01` のように日付を頭に付けるのがおすすめ。
2. フォルダに以下を置く。
   - 画像: `01.jpg`（2〜10 枚ならカルーセル投稿。`01.jpg`, `02.jpg` … の順に並ぶ）
   - `caption.txt`: キャプション（UTF-8、2200 文字・ハッシュタグ 30 個まで）
3. 確認: `python scripts/post_queue.py check`

画像の条件: JPEG のみ / 8MB 以下 / 幅 320px 以上 / 縦横比 4:5（縦長）〜 1.91:1（横長）。
おすすめは 1080×1350（4:5）か 1080×1080（1:1）。

## 初期設定（アクセストークン）

前提: Instagram がプロアカウント（ビジネス/クリエイター）で Facebook ページと連携済み。

1. [Meta for Developers](https://developers.facebook.com/apps/) でアプリを作成し、製品「Instagram」
   （Facebook ログインによる API 設定）を追加する。アプリは開発モードのままで、自分（アプリ管理者）の
   アカウントへの投稿は可能。
2. [グラフAPIエクスプローラ](https://developers.facebook.com/tools/explorer/) で作成したアプリを選び、
   次の権限でユーザーアクセストークンを発行する:
   `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`, `business_management`
3. [アクセストークンデバッガー](https://developers.facebook.com/tools/debug/accesstoken/) で
   そのトークンを「アクセストークンを延長」して長期ユーザートークンにする。
4. グラフAPIエクスプローラで長期トークンを使い、以下を実行する。
   - `me/accounts` → 対象ページの `access_token`（**ページアクセストークン。期限なし**）と `id`
   - `<ページID>?fields=instagram_business_account` → `instagram_business_account.id`（17桁前後の数字）
5. Windows の環境変数（ユーザー）に登録する。
   「スタート」→「環境変数を編集」で次の 2 つを追加する（コマンド履歴にトークンを残さないため GUI 推奨）。
   - `INSTAGRAM_ACCESS_TOKEN` = 手順4のページアクセストークン
   - `INSTAGRAM_BUSINESS_ACCOUNT_ID` = 手順4の instagram_business_account.id
6. Claude デスクトップアプリを再起動する（環境変数の再読み込みのため）。

トークンは `.mcp.json` が `${INSTAGRAM_ACCESS_TOKEN}` として環境変数から読み込むため、
リポジトリには一切書かれない。

## スケジュール投稿

Claude デスクトップアプリのスケジュールタスクで、このフォルダを作業ディレクトリとして次の手順を実行する。
アプリが起動している間のみ実行される。

```
1. python scripts/post_queue.py next を実行する。
   - status が "empty" なら何もせず「キューが空」と報告して終了。
   - status が "invalid" ならエラー内容を報告して終了（投稿しない）。
2. status が "ready" なら、出力の caption を一字一句変えずに使って投稿する。
   - type が "photo" → mcp__instagram__ig_publish_photo（imageUrl = image_urls[0]）
   - type が "carousel" → mcp__instagram__ig_publish_carousel（items = image_urls の順）
3. 投稿に成功したら python scripts/post_queue.py done <id> <返ってきた media id> を実行する。
   失敗したら done は実行せず、エラー内容を報告する（次回同じ投稿を再試行する）。
```

## ファイル

| パス | 役割 |
|---|---|
| `.mcp.json` | Instagram MCP サーバーの登録（Claude Code / デスクトップの Code タブ用） |
| `.claude/settings.json` | MCP サーバーの有効化と、自動投稿に必要なツールの実行許可 |
| `scripts/post_queue.py` | キューの検証・push・投稿済み処理（標準ライブラリのみ） |
| `posts/queue/` | 投稿待ち |
| `posts/posted/`, `posts/posted.jsonl` | 投稿済みと履歴 |
