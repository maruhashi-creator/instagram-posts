"""Instagram 投稿キュー管理スクリプト（標準ライブラリのみ）

posts/queue/<投稿ID>/ に画像 (.jpg) と caption.txt を置くと、ID の昇順に 1 件ずつ投稿対象になる。
画像は GitHub に push し、コミット SHA 固定の raw URL を Instagram に渡す。

使い方:
  python scripts/post_queue.py check          キュー全件を検証（push しない）
  python scripts/post_queue.py next           次の投稿を検証 → push → 公開URLをJSONで出力
  python scripts/post_queue.py done <ID> <MEDIA_ID>
                                              投稿済みにして posts/posted/ へ移動し push
"""

import json
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "posts" / "queue"
POSTED = ROOT / "posts" / "posted"
LOG = ROOT / "posts" / "posted.jsonl"

MAX_CAPTION = 2200
MAX_HASHTAGS = 30
MAX_BYTES = 8 * 1024 * 1024
MIN_RATIO, MAX_RATIO = 4 / 5, 1.91  # 縦 4:5 〜 横 1.91:1
IMAGE_EXTS = {".jpg", ".jpeg"}


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{out.stderr.strip()}")
    return out.stdout.strip()


def jpeg_size(path: Path) -> tuple[int, int]:
    """JPEG の SOF マーカーから (幅, 高さ) を読む。JPEG でなければ例外。"""
    data = path.read_bytes()
    if data[:2] != b"\xff\xd8":
        raise ValueError("JPEG ではありません（PNG等は JPEG に変換してください）")
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
            i += 1 if marker == 0xFF else 2
            continue
        length = int.from_bytes(data[i + 2 : i + 4], "big")
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height = int.from_bytes(data[i + 5 : i + 7], "big")
            width = int.from_bytes(data[i + 7 : i + 9], "big")
            return width, height
        i += 2 + length
    raise ValueError("JPEG のサイズ情報が読めません")


def inspect(post_dir: Path) -> dict:
    """投稿フォルダを検証し、問題点のリストと内容を返す。"""
    errors = []
    images = sorted(p for p in post_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    others = [
        p.name for p in post_dir.iterdir()
        if p.is_file() and p.suffix.lower() not in IMAGE_EXTS and p.name != "caption.txt"
    ]
    if others:
        errors.append(f"対象外のファイルがあります: {', '.join(others)}（画像は .jpg のみ）")
    if not 1 <= len(images) <= 10:
        errors.append(f"画像は 1〜10 枚にしてください（現在 {len(images)} 枚）")

    for img in images:
        if img.stat().st_size > MAX_BYTES:
            errors.append(f"{img.name}: 8MB を超えています")
        try:
            w, h = jpeg_size(img)
            if w < 320:
                errors.append(f"{img.name}: 幅 {w}px は小さすぎます（320px 以上）")
            if not MIN_RATIO - 0.01 <= w / h <= MAX_RATIO + 0.01:
                errors.append(f"{img.name}: 縦横比 {w}x{h} は範囲外です（4:5〜1.91:1）")
        except ValueError as e:
            errors.append(f"{img.name}: {e}")

    caption_file = post_dir / "caption.txt"
    caption = caption_file.read_text(encoding="utf-8-sig").strip() if caption_file.exists() else ""
    if not caption:
        errors.append("caption.txt がない、または空です")
    if len(caption) > MAX_CAPTION:
        errors.append(f"キャプションが {len(caption)} 文字です（上限 {MAX_CAPTION}）")
    hashtags = re.findall(r"#\w+", caption)
    if len(hashtags) > MAX_HASHTAGS:
        errors.append(f"ハッシュタグが {len(hashtags)} 個です（上限 {MAX_HASHTAGS}）")

    return {"id": post_dir.name, "images": images, "caption": caption, "errors": errors}


def queued() -> list[Path]:
    return sorted(p for p in QUEUE.iterdir() if p.is_dir()) if QUEUE.exists() else []


def raw_base() -> str:
    url = git("remote", "get-url", "origin")
    m = re.search(r"github\.com[:/](.+?)/(.+?)(\.git)?$", url)
    if not m:
        raise SystemExit(f"origin が GitHub ではありません: {url}")
    return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}"


def assert_public(url: str) -> None:
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=30) as res:
        ctype = res.headers.get("Content-Type", "")
        if res.status != 200 or not ctype.startswith("image/jpeg"):
            raise SystemExit(f"公開URLを確認できません: {url} (status={res.status}, type={ctype})")


def emit(obj: dict) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_check() -> None:
    results = [inspect(p) for p in queued()]
    emit({
        "queued": len(results),
        "posts": [{"id": r["id"], "images": len(r["images"]), "errors": r["errors"]} for r in results],
    })
    if any(r["errors"] for r in results):
        sys.exit(1)


def cmd_next() -> None:
    posts = queued()
    if not posts:
        emit({"status": "empty", "message": "キューに投稿がありません"})
        return
    post = inspect(posts[0])
    if post["errors"]:
        emit({"status": "invalid", "id": post["id"], "errors": post["errors"]})
        sys.exit(1)

    rel = posts[0].relative_to(ROOT).as_posix()
    git("add", "--", rel)
    if git("status", "--porcelain", "--", rel):
        git("commit", "-m", f"queue: {post['id']}", "--", rel)
    git("push", "origin", "HEAD")
    sha = git("rev-parse", "HEAD")

    base = raw_base()
    urls = [f"{base}/{sha}/{rel}/{img.name}" for img in post["images"]]
    for u in urls:
        assert_public(u)

    emit({
        "status": "ready",
        "id": post["id"],
        "type": "photo" if len(urls) == 1 else "carousel",
        "image_urls": urls,
        "caption": post["caption"],
        "remaining_after_this": len(posts) - 1,
    })


def cmd_done(post_id: str, media_id: str) -> None:
    src = QUEUE / post_id
    if not src.is_dir():
        raise SystemExit(f"キューに {post_id} がありません")
    POSTED.mkdir(parents=True, exist_ok=True)
    git("mv", src.relative_to(ROOT).as_posix(), (POSTED / post_id).relative_to(ROOT).as_posix())
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "id": post_id,
            "media_id": media_id,
            "posted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, ensure_ascii=False) + "\n")
    git("add", "--", LOG.relative_to(ROOT).as_posix())
    git("commit", "-m", f"posted: {post_id} ({media_id})")
    git("push", "origin", "HEAD")
    emit({"status": "done", "id": post_id, "media_id": media_id, "remaining": len(queued())})


if __name__ == "__main__":
    match sys.argv[1:]:
        case ["check"]:
            cmd_check()
        case ["next"]:
            cmd_next()
        case ["done", post_id, media_id]:
            cmd_done(post_id, media_id)
        case _:
            print(__doc__)
            sys.exit(2)
