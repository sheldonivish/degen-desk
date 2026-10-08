#!/usr/bin/env python3
"""Telegram delivery for Markdown reports via the Telegram Bot API (stdlib only).

Commands
  tg.py whoami                         getMe: show the bot's @username (read-only)
  tg.py chats                          getUpdates: list chats the bot has seen (read-only)
  tg.py send [--chat ID] --file F.md [--thread N] [--dry-run] [--require TEXT]
  tg.py config [--chat ID] [--thread N|none] [--enable|--disable]   show/edit config.json

The bot token is read from the TELEGRAM_BOT_TOKEN environment variable only. It is
never printed, logged or written to disk; any error text is scrubbed of it.
Real sends require config.json "enabled": true (dry runs do not).
"""
import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.telegram.org"
TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
DEFAULT_CONFIG = Path(os.environ.get("TG_CONFIG", Path(__file__).resolve().parent / "config.json"))
DEFAULT_LIMIT = 4096          # Telegram: 1-4096 chars of message text after entity parsing
SAFE_SCHEMES = ("http://", "https://", "tg://")


# --------------------------------------------------------------------------- utils
def die(msg, code=1):
    print(f"error: {scrub(msg)}", file=sys.stderr)
    sys.exit(code)


def scrub(text):
    """Remove the token from any string before it is shown."""
    text = str(text)
    tok = os.environ.get(TOKEN_ENV, "")
    if tok:
        text = text.replace(tok, "<TOKEN>")
    return re.sub(r"bot\d{5,}:[A-Za-z0-9_-]{20,}", "bot<TOKEN>", text)


def u16len(s):
    return len(s.encode("utf-16-le")) // 2


TAG_RE = re.compile(r"<[^>]*>")


def visible(html_text):
    return html.unescape(TAG_RE.sub("", html_text))


def vlen(html_text):
    """Length Telegram counts: text after entity parsing, in UTF-16 code units."""
    return u16len(visible(html_text))


def well_formed(html_text):
    stack = []
    for m in re.finditer(r"<(/?)([a-z]+)[^>]*>", html_text):
        closing, name = m.group(1), m.group(2)
        if not closing:
            stack.append(name)
        elif not stack or stack.pop() != name:
            return False
    return not stack


# ------------------------------------------------------------ Markdown -> HTML
LINK_RE = re.compile(
    r"\[((?:[^\[\]\\]|\\.|\[[^\[\]]*\])*)\]"            # [text] (one level of nested [] allowed)
    r"\(\s*<?((?:[^\s()<>]|\([^\s()<>]*\))+)>?"         # (url  with balanced parens
    r"(?:\s+\"[^\"]*\")?\s*\)"                          #  optional "title")
)
CODE_RE = re.compile(r"(`+)(.+?)\1")
PH_RE = re.compile("\ue000(\\d+)\ue001")


def _escape(s):
    return html.escape(s, quote=False)


def _emphasis(s):
    s = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w*])__(?=\S)(.+?)(?<=\S)__(?![\w*])", r"<b>\1</b>", s)
    s = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", r"<s>\1</s>", s)
    # single-* italics only; _x_ is skipped on purpose (breaks @handles_like_this)
    s = re.sub(r"(?<![\w*\\])\*(?=[^\s*])(.+?)(?<=[^\s*\\])\*(?![\w*])", r"<i>\1</i>", s)
    return s


def inline(text, emphasis=True, links=True):
    """Convert one line of inline Markdown to Telegram HTML. Output is always well-formed."""
    ph = []

    def keep(fragment):
        ph.append(fragment)
        return f"\ue000{len(ph) - 1}\ue001"

    text = text.replace("\ue000", "").replace("\ue001", "")
    text = CODE_RE.sub(lambda m: keep(f"<code>{_escape(m.group(2).strip())}</code>"), text)

    def link(m):
        label, url = m.group(1), m.group(2).strip()
        label_html = inline(PH_RE.sub(lambda p: visible(ph[int(p.group(1))]), label),
                            emphasis=emphasis, links=False) or _escape(url)
        if not url.lower().startswith(SAFE_SCHEMES):
            return keep(f"{label_html} ({_escape(url)})")
        return keep(f'<a href="{html.escape(url, quote=True)}">{label_html}</a>')

    if links:
        text = LINK_RE.sub(link, text)
    text = re.sub(r"\\([\\`*_{}\[\]()#+\-.!~>|])", lambda m: keep(_escape(m.group(1))), text)
    out = _escape(text)
    if emphasis:
        out = _emphasis(out)
    while PH_RE.search(out):
        out = PH_RE.sub(lambda m: ph[int(m.group(1))], out)
    if not well_formed(out):          # mis-nested emphasis: keep links/code, drop * emphasis
        out = inline_plain(text, ph)
    return out


def inline_plain(text, ph):
    """Fallback when emphasis would mis-nest: keep links/code, drop * emphasis."""
    out = _escape(text)
    while PH_RE.search(out):
        out = PH_RE.sub(lambda m: ph[int(m.group(1))], out)
    return out


HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
ORDERED_RE = re.compile(r"^(\s*)(\d{1,9})[.)]\s+(.*)$")
HR_RE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def _indent_level(spaces):
    return len(spaces.replace("\t", "    ")) // 2


def md_to_blocks(md):
    """Return a list of blocks; each block is a list of units (well-formed HTML strings).

    Blocks are separated by a blank line in the output. A unit is the smallest piece the
    splitter will keep together: a paragraph line, a heading, or a top-level list item
    together with its nested sub-items.
    """
    md = re.sub(r"<!--.*?-->", "", md.replace("\r\n", "\n"), flags=re.S)
    blocks, cur = [], []        # cur: list of [kind, html]
    code = None
    quote = []

    def flush_quote():
        if quote:
            cur.append(["quote", "<blockquote>" + "\n".join(quote) + "</blockquote>"])
            quote.clear()

    def flush():
        flush_quote()
        if cur:
            blocks.append([dict(kind=k, html=h) for k, h in cur])
            cur.clear()

    for raw in md.split("\n"):
        line = raw.rstrip()
        if code is not None:
            if FENCE_RE.match(line):
                cur.append(["pre", "<pre>" + _escape("\n".join(code)) + "</pre>"])
                code = None
            else:
                code.append(raw)
            continue
        if FENCE_RE.match(line):
            flush_quote()
            code = []
            continue
        if not line.strip():
            flush()
            continue
        if line.lstrip().startswith(">"):
            quote.append(inline(re.sub(r"^\s*>\s?", "", line)))
            continue
        flush_quote()
        m = HEADING_RE.match(line)
        if m:
            flush()
            text = re.sub(r"</?b>", "", inline(m.group(2)))
            blocks.append([dict(kind="heading", html=f"<b>{text}</b>")])
            continue
        if HR_RE.match(line):
            flush()
            blocks.append([dict(kind="hr", html="———")])
            continue
        if line.lstrip().startswith("|") and line.rstrip().endswith("|"):
            if TABLE_SEP_RE.match(line):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            cur.append(["para", " · ".join(inline(c) for c in cells if c)])
            continue
        m = BULLET_RE.match(line)
        if m and not HR_RE.match(line):
            lvl = _indent_level(m.group(1))
            body = inline(m.group(2))
            if lvl == 0 or not cur or cur[-1][0] not in ("item", "subitem"):
                cur.append(["item", f"• {body}"] if lvl == 0 else ["item", f"    ◦ {body}"])
            else:
                cur[-1][1] += "\n" + "    " * (lvl - 1) + f"    ◦ {body}"
            continue
        m = ORDERED_RE.match(line)
        if m:
            lvl = _indent_level(m.group(1))
            body = f"{m.group(2)}. {inline(m.group(3))}"
            if lvl > 0 and cur and cur[-1][0] == "item":
                cur[-1][1] += "\n" + "    " * lvl + body
            else:
                cur.append(["item", body])
            continue
        if cur and cur[-1][0] == "item" and raw[:1] in (" ", "\t"):
            cur[-1][1] += " " + inline(line.strip())        # lazy continuation of a list item
            continue
        cur.append(["para", inline(line.strip())])
    if code is not None:                                    # unclosed fence
        cur.append(["pre", "<pre>" + _escape("\n".join(code)) + "</pre>"])
    flush()
    return blocks


def md_to_html(md):
    return "\n\n".join("\n".join(u["html"] for u in b) for b in md_to_blocks(md))


# ------------------------------------------------------------------- splitting
ATOM_RE = re.compile(r"<[^>]*>|&(?:#\d+|#x[0-9a-fA-F]+|[a-zA-Z]+);|[\ud800-\udbff][\udc00-\udfff]|.", re.S)


def hard_split(unit, limit):
    """Tag-aware split of one oversized HTML unit. Prefers newlines, then spaces, and
    never breaks inside an <a> unless a single link is longer than the limit. Tags open at
    a break are closed at the end of the piece and reopened at the start of the next."""
    atoms = ATOM_RE.findall(unit)
    pieces, stack = [], []
    buf, width = [], 0
    best_nl = best_sp = None   # (index in buf, stack snapshot)

    def emit(cut, snap):
        head, tail = buf[:cut], buf[cut:]
        text = "".join(head).rstrip()
        text += "".join(f"</{re.match(r'<([a-z]+)', t).group(1)}>" for t in reversed(snap))
        pieces.append(text)
        return list(snap) + [a for a in tail]

    for atom in atoms:
        if atom.startswith("<") and len(atom) > 1:
            if atom.startswith("</"):
                if stack:
                    stack.pop()
            else:
                stack.append(atom)
            buf.append(atom)
            continue
        w = u16len(html.unescape(atom))
        if width + w > limit:
            choice = best_nl or best_sp
            if choice is None:              # no safe break point: cut right here
                choice = (len(buf), list(stack))
            cut, snap = choice
            rest = emit(cut, snap)
            if choice is not best_nl:       # space break: drop leading spaces of the rest
                while len(rest) > len(snap) and rest[len(snap)].isspace():
                    rest.pop(len(snap))
            buf = rest
            width = vlen("".join(buf))
            best_nl = best_sp = None
        buf.append(atom)
        width += w
        in_link = any(t.startswith("<a") for t in stack)
        if atom == "\n" and not in_link:
            best_nl = (len(buf), list(stack))
        elif atom.isspace() and not in_link:
            best_sp = (len(buf), list(stack))
    if buf:
        pieces.append("".join(buf).strip())
    return [p for p in pieces if visible(p).strip()]


def split_blocks(blocks, limit=DEFAULT_LIMIT):
    """Pack blocks into messages of at most `limit` visible chars.

    Preference order: whole sections (heading + its blocks) > whole blocks (paragraphs,
    lists) > units (one list item with its sub-items) > tag-aware hard split.
    A heading is never left as the last thing in a message."""
    chunks = []
    cur = []          # list of (separator, html, kind)

    def cur_html(parts):
        return "".join(sep + h for sep, h, _ in parts).strip("\n")

    def fits(sep, html_text, kind="x"):
        return vlen(cur_html(cur + [(sep, html_text, kind)])) <= limit

    def flush():
        nonlocal cur
        carry = []
        while len(cur) > 1 and cur[-1][2] == "heading":
            carry.insert(0, cur.pop())
        if cur:
            chunks.append(cur_html(cur))
        cur = [("\n\n" if i else "", h, k) for i, (_, h, k) in enumerate(carry)]

    def add(sep_if_cur, html_text, kind):
        cur.append((sep_if_cur if cur else "", html_text, kind))

    def flush_then_add(html_text, kind):
        """Start a new message with html_text. flush() may carry a heading over; if heading +
        text no longer fit, hard-split the text so the first piece fits after the heading."""
        nonlocal cur
        flush()
        if fits("\n\n" if cur else "", html_text):
            return add("\n\n", html_text, kind)
        room = limit - vlen(cur_html(cur)) - 2
        pieces = hard_split(html_text, room) if room > 0 else []
        if not pieces:                      # heading alone fills the message: send it as is
            chunks.append(cur_html(cur))
            cur = []
            pieces = hard_split(html_text, limit) if vlen(html_text) > limit else [html_text]
        for i, piece in enumerate(pieces):
            if i and not fits("\n", piece):
                flush()
            add("\n\n" if i == 0 else "\n", piece, kind)

    def pack_block(block):
        block_html = "\n".join(u["html"] for u in block)
        kind = block[-1]["kind"]
        if fits("\n\n" if cur else "", block_html):
            return add("\n\n", block_html, kind)
        # does not fit: if the message is already half full and the block fits on its own,
        # start a new message rather than splitting the block
        if cur and vlen(block_html) <= limit and vlen(cur_html(cur)) >= limit // 2:
            return flush_then_add(block_html, kind)
        for i, unit in enumerate(block):
            pieces = [unit["html"]] if vlen(unit["html"]) <= limit else hard_split(unit["html"], limit)
            for j, piece in enumerate(pieces):
                sep = "\n\n" if (i == 0 and j == 0) else "\n"
                if not fits(sep if cur else "", piece):
                    flush_then_add(piece, unit["kind"])
                    continue
                add(sep, piece, unit["kind"])

    sections = []
    for block in blocks:
        if block[0]["kind"] == "heading" or not sections:
            sections.append([])
        sections[-1].append(block)
    for section in sections:
        sec_html = "\n\n".join("\n".join(u["html"] for u in b) for b in section)
        kind = section[-1][-1]["kind"]
        if fits("\n\n" if cur else "", sec_html):
            add("\n\n", sec_html, kind)
        elif cur and vlen(sec_html) <= limit:
            flush_then_add(sec_html, kind)
        else:
            for block in section:
                pack_block(block)
    if cur:
        chunks.append(cur_html(cur))
    return [c for c in chunks if c.strip()]


def convert(md, limit=DEFAULT_LIMIT):
    chunks = split_blocks(md_to_blocks(md), limit)
    for c in chunks:
        assert well_formed(c), "internal error: malformed HTML chunk"
        assert vlen(c) <= limit, "internal error: chunk over limit"
    return chunks


# -------------------------------------------------------------------- Bot API
class TgError(Exception):
    def __init__(self, code, description, parameters=None):
        super().__init__(f"{code}: {description}")
        self.code, self.description, self.parameters = code, description, parameters or {}


def token():
    tok = os.environ.get(TOKEN_ENV, "").strip()
    if not tok:
        die(f"{TOKEN_ENV} is not set. Save the @BotFather token through the secret form first.")
    return tok


def call(method, params=None, timeout=30):
    url = f"{API}/bot{token()}/{method}"
    data = json.dumps(params or {}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            raise TgError(e.code, scrub(f"HTTP {e.code}")) from None
    except urllib.error.URLError as e:
        raise TgError(0, scrub(f"network error: {e.reason}")) from None
    if not body.get("ok"):
        raise TgError(body.get("error_code", 0), scrub(body.get("description", "unknown error")),
                      body.get("parameters"))
    return body["result"]


def call_with_retry(method, params, max_429=5, max_net=2):
    n429 = nnet = 0
    while True:
        try:
            return call(method, params)
        except TgError as e:
            if e.code == 429 and n429 < max_429:
                n429 += 1
                wait = int(e.parameters.get("retry_after", 5)) + 1
                print(f"rate limited (429), retrying in {wait}s", file=sys.stderr)
                time.sleep(min(wait, 300))
                continue
            if (e.code == 0 or e.code >= 500) and nnet < max_net:
                nnet += 1
                time.sleep(2 * nnet)
                continue
            raise


# ------------------------------------------------------------------- config
def load_config(path):
    cfg = {"chat_id": None, "thread_id": None, "enabled": False}
    if Path(path).exists():
        cfg.update(json.loads(Path(path).read_text()))
    return cfg


def save_config(path, cfg):
    Path(path).write_text(json.dumps(cfg, indent=2) + "\n")


# ------------------------------------------------------------------ commands
def cmd_whoami(a):
    me = call("getMe")
    print(f"@{me.get('username')}  (id {me.get('id')}, name {me.get('first_name')!r})")
    print(f"can_join_groups={me.get('can_join_groups')}  "
          f"can_read_all_group_messages={me.get('can_read_all_group_messages')} (False = privacy mode on)")


def cmd_chats(a):
    try:
        updates = call("getUpdates", {"limit": 100, "timeout": 0, "allowed_updates": [
            "message", "edited_message", "channel_post", "edited_channel_post",
            "my_chat_member", "chat_member"]})
    except TgError as e:
        if e.code == 409:
            die("a webhook is set for this bot, so getUpdates is unavailable. "
                "Find the chat id from your webhook logs, or remove the webhook.")
        raise
    seen = {}
    for u in updates:
        for key in ("message", "edited_message", "channel_post", "edited_channel_post",
                    "my_chat_member", "chat_member"):
            obj = u.get(key)
            if not obj or "chat" not in obj:
                continue
            c = obj["chat"]
            title = c.get("title") or " ".join(x for x in (c.get("first_name"), c.get("last_name")) if x) \
                or c.get("username") or ""
            info = seen.setdefault(c["id"], dict(id=c["id"], type=c.get("type"), title=title,
                                                 username=c.get("username"), status=None, threads=set()))
            info["title"] = title or info["title"]
            if key == "my_chat_member":
                info["status"] = obj.get("new_chat_member", {}).get("status")
            if obj.get("message_thread_id") and obj.get("is_topic_message"):
                info["threads"].add(obj["message_thread_id"])
            if obj.get("migrate_to_chat_id"):
                info["status"] = f"migrated -> {obj['migrate_to_chat_id']}"
    if not seen:
        print("No chats seen in the last 24h. Add the bot to the group/channel (or DM it), "
              "post a message there (in groups with privacy mode on, send a /command such as "
              "/start@<botname>), then run this again.")
        return
    print(f"{'chat_id':>16}  {'type':<10}  {'bot status':<14}  title")
    for c in seen.values():
        extra = f"  @{c['username']}" if c["username"] else ""
        threads = f"  topics seen: {sorted(c['threads'])}" if c["threads"] else ""
        print(f"{c['id']:>16}  {c['type']:<10}  {str(c['status'] or '-'):<14}  {c['title']}{extra}{threads}")


def cmd_config(a):
    cfg = load_config(a.config)
    changed = False
    if a.chat is not None:
        cfg["chat_id"] = int(a.chat) if re.fullmatch(r"-?\d+", a.chat) else a.chat
        changed = True
    if a.thread is not None:
        cfg["thread_id"] = None if a.thread.lower() in ("none", "null", "") else int(a.thread)
        changed = True
    if a.enable or a.disable:
        if a.enable and cfg.get("chat_id") is None:
            die("set a chat id before enabling")
        cfg["enabled"] = bool(a.enable)
        changed = True
    if changed:
        save_config(a.config, cfg)
    print(json.dumps(cfg, indent=2))


def cmd_send(a):
    md = Path(a.file).read_text(encoding="utf-8")
    if a.require and a.require.lower() not in md.lower():
        die(f"report does not contain required text {a.require!r}; not sending")
    cfg = load_config(a.config)
    chat = a.chat if a.chat is not None else cfg.get("chat_id")
    thread = a.thread if a.thread is not None else (cfg.get("thread_id") if a.chat is None else None)
    chunks = convert(md, a.limit)

    if a.dry_run:
        print(f"# dry run: {len(chunks)} message(s) -> chat {chat!r} thread {thread!r} "
              f"(config enabled={cfg.get('enabled')}); nothing sent")
        for i, c in enumerate(chunks, 1):
            print(f"\n===== chunk {i}/{len(chunks)} · {vlen(c)} visible chars (limit {a.limit}) "
                  f"· {len(c)} raw HTML chars · well-formed={well_formed(c)} =====")
            print(c)
        return

    if not cfg.get("enabled"):
        die(f"sending is disabled in {a.config} (enabled=false). Enable it only after the owner "
            "has approved the destination.")
    if chat is None:
        die("no chat id: pass --chat or set chat_id in config.json")
    if a.chat is not None and cfg.get("chat_id") is not None and str(a.chat) != str(cfg["chat_id"]) \
            and not a.allow_other_chat:
        die("--chat differs from the approved chat_id in config.json; pass --allow-other-chat "
            "only if the owner approved this destination too")

    ids, plain_fallbacks = [], 0
    for i, c in enumerate(chunks, 1):
        params = {"chat_id": chat, "text": c, "parse_mode": "HTML",
                  # modern form of disable_web_page_preview=true (Bot API 7.0+)
                  "link_preview_options": {"is_disabled": True}}
        if thread:
            params["message_thread_id"] = int(thread)
        try:
            try:
                msg = call_with_retry("sendMessage", params)
            except TgError as e:
                if e.code == 400 and "parse" in e.description.lower():
                    plain_fallbacks += 1          # never lose a report over formatting
                    params.pop("parse_mode")
                    params["text"] = visible(c)
                    msg = call_with_retry("sendMessage", params)
                else:
                    raise
        except TgError as e:
            hint = ""
            mig = e.parameters.get("migrate_to_chat_id")
            if mig:
                hint = f" The group was upgraded to a supergroup: new chat id {mig}. Update config.json."
            elif e.code == 403:
                hint = " The bot is not in that chat, was removed, or (channels) is not an admin."
            elif e.code == 400 and "chat not found" in e.description.lower():
                hint = " Check the chat id (groups/channels are negative, supergroups start -100)."
            elif e.code == 400 and "thread" in e.description.lower():
                hint = " Check the topic thread id."
            print(json.dumps({"ok": False, "sent_message_ids": ids, "failed_chunk": i,
                              "chunks": len(chunks), "error": scrub(str(e))}))
            die(f"send failed on chunk {i}/{len(chunks)}: {e}.{hint}", code=2)
        ids.append(msg["message_id"])
        print(f"sent chunk {i}/{len(chunks)} -> message_id {msg['message_id']}", file=sys.stderr)
        if i < len(chunks):
            time.sleep(a.delay)
    print(json.dumps({"ok": True, "chat_id": chat, "thread_id": thread, "message_ids": ids,
                      "chunks": len(chunks), "plain_text_fallbacks": plain_fallbacks}))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("whoami")
    sub.add_parser("chats")
    c = sub.add_parser("config")
    c.add_argument("--chat")
    c.add_argument("--thread")
    g = c.add_mutually_exclusive_group()
    g.add_argument("--enable", action="store_true")
    g.add_argument("--disable", action="store_true")
    s = sub.add_parser("send")
    s.add_argument("--chat")
    s.add_argument("--file", required=True)
    s.add_argument("--thread", type=int)
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--require", help="refuse to send unless the report contains this text")
    s.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    s.add_argument("--delay", type=float, default=1.5, help="seconds between chunks")
    s.add_argument("--allow-other-chat", action="store_true")
    a = p.parse_args(argv)
    try:
        {"whoami": cmd_whoami, "chats": cmd_chats, "send": cmd_send, "config": cmd_config}[a.cmd](a)
    except TgError as e:
        die(str(e), code=2)
    except Exception as e:  # never let a traceback carry the token
        die(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
