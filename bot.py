import asyncio
import logging
import os
import json
from html import escape

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery, ChatJoinRequest, InlineKeyboardButton, MessageEntity,
    InlineKeyboardMarkup, Message, FSInputFile
)
from dotenv import load_dotenv

from database import Database

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "data/bot.sqlite3")
MEDIA_DIR = os.getenv("MEDIA_DIR", "data/media")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing in .env")
if not OWNER_ID:
    raise RuntimeError("OWNER_ID is missing in .env")

os.makedirs(MEDIA_DIR, exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("join-verifier")
db = Database(DB_PATH)

# Backward-compatible migration: keep the existing database.py unchanged
# and add an invite URL column for private/request-to-join channels.
def ensure_channel_invite_column():
    with db.conn() as c:
        cols = {row["name"] for row in c.execute("PRAGMA table_info(channels)").fetchall()}
        if "invite_url" not in cols:
            c.execute("ALTER TABLE channels ADD COLUMN invite_url TEXT DEFAULT ''")


db.init()
ensure_channel_invite_column()
dp = Dispatcher()

def is_admin(uid): return uid == OWNER_ID or db.is_admin(uid)

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Join Links", callback_data="channels"),
         InlineKeyboardButton(text="👥 Verified Users", callback_data="verified")],
        [InlineKeyboardButton(text="👤 Admins", callback_data="admins"),
         InlineKeyboardButton(text="📊 Stats", callback_data="stats")],
        [InlineKeyboardButton(text="✏️ Welcome", callback_data="edit_welcome"),
         InlineKeyboardButton(text="✏️ Verified Msg", callback_data="edit_verified")],
        [InlineKeyboardButton(text="🎨 Premium UI", callback_data="premium_ui"),
         InlineKeyboardButton(text="📢 Broadcast", callback_data="broadcast")],
    ])

def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Back", callback_data="home")]
    ])

async def auth_msg(m):
    if not is_admin(m.from_user.id):
        await m.answer("⛔ Admin access required.")
        return False
    return True

async def auth_cb(c):
    if not is_admin(c.from_user.id):
        await c.answer("Admin access required.", show_alert=True)
        return False
    return True


def stored_entities(key):
    # Kept for backward compatibility with older DBs.
    raw = db.get_settings().get(key, "[]")
    try:
        return [MessageEntity.model_validate(x) for x in json.loads(raw)]
    except Exception:
        return []


def _utf16_boundaries(text: str):
    """Map Telegram UTF-16 offsets to Python string indices."""
    out = [0]
    total = 0
    for i, ch in enumerate(text):
        total += len(ch.encode("utf-16-le")) // 2
        out.append(total)
    return out


def _entity_tag(entity, inner):
    t = entity.type
    if t == "bold": return f"<b>{inner}</b>"
    if t == "italic": return f"<i>{inner}</i>"
    if t == "underline": return f"<u>{inner}</u>"
    if t == "strikethrough": return f"<s>{inner}</s>"
    if t == "spoiler": return f"<tg-spoiler>{inner}</tg-spoiler>"
    if t == "code": return f"<code>{inner}</code>"
    if t == "pre": return f"<pre>{inner}</pre>"
    if t == "text_link" and entity.url:
        return f'<a href="{escape(entity.url, quote=True)}">{inner}</a>'
    if t == "text_mention" and entity.user:
        return f'<a href="tg://user?id={entity.user.id}">{inner}</a>'
    if t == "custom_emoji" and entity.custom_emoji_id:
        # Telegram requires the custom-emoji entity to wrap exactly one
        # regular emoji alternative. The incoming message already contains it.
        return f'<tg-emoji emoji-id="{escape(str(entity.custom_emoji_id), quote=True)}">{inner}</tg-emoji>'
    return inner


def message_to_html(message):
    """Convert Telegram formatting entities to Bot API HTML.

    This is important for Premium/custom emoji: the custom emoji ID is
    converted to <tg-emoji emoji-id="...">...</tg-emoji> and therefore does
    not get lost when the bot sends the saved message later.
    """
    text = message.text or message.caption or ""
    entities = message.entities or message.caption_entities or []
    if not entities:
        return text

    bounds = _utf16_boundaries(text)
    events = {}
    for e in entities:
        start_u = e.offset
        end_u = e.offset + e.length
        if start_u not in bounds or end_u not in bounds:
            continue
        a = bounds.index(start_u)
        b = bounds.index(end_u)
        events.setdefault(a, []).append(("open", e))
        events.setdefault(b, []).append(("close", e))

    # Build nested tags from the original text. Longer entities open first;
    # shorter entities close first, which keeps nesting valid.
    out = []
    for i in range(len(text) + 1):
        if i in events:
            closes = [e for kind, e in events[i] if kind == "close"]
            opens = [e for kind, e in events[i] if kind == "open"]
            for e in sorted(closes, key=lambda x: x.length):
                # closing tag is produced by wrapping an empty string
                tag = _entity_tag(e, "")
                if e.type == "bold": out.append("</b>")
                elif e.type == "italic": out.append("</i>")
                elif e.type == "underline": out.append("</u>")
                elif e.type == "strikethrough": out.append("</s>")
                elif e.type == "spoiler": out.append("</tg-spoiler>")
                elif e.type == "code": out.append("</code>")
                elif e.type == "pre": out.append("</pre>")
                elif e.type in ("text_link", "text_mention"): out.append("</a>")
                elif e.type == "custom_emoji": out.append("</tg-emoji>")
            for e in sorted(opens, key=lambda x: -x.length):
                if e.type == "bold": out.append("<b>")
                elif e.type == "italic": out.append("<i>")
                elif e.type == "underline": out.append("<u>")
                elif e.type == "strikethrough": out.append("<s>")
                elif e.type == "spoiler": out.append("<tg-spoiler>")
                elif e.type == "code": out.append("<code>")
                elif e.type == "pre": out.append("<pre>")
                elif e.type == "text_link" and e.url: out.append(f'<a href="{escape(e.url, quote=True)}">')
                elif e.type == "text_mention" and e.user: out.append(f'<a href="tg://user?id={e.user.id}">')
                elif e.type == "custom_emoji" and e.custom_emoji_id: out.append(f'<tg-emoji emoji-id="{escape(str(e.custom_emoji_id), quote=True)}">')
        if i < len(text):
            out.append(escape(text[i]))
    return "".join(out)


@dp.message(Command("start"))
async def start(m):
    s = db.get_settings()
    template = s.get("welcome_html") or s.get("welcome_message", "Hello {first_name}! Please submit your join request.")
    text = template.format(first_name=escape(m.from_user.first_name or "there"), user_id=m.from_user.id)
    kb = merge_keyboards(channel_buttons(), build_buttons(s.get("welcome_buttons", "")))
    photo = s.get("welcome_photo", "")
    if photo:
        try:
            await m.answer_photo(FSInputFile(photo), caption=text, reply_markup=kb)
            return
        except Exception:
            log.exception("welcome photo failed")
    await m.answer(text, reply_markup=kb)


def build_buttons(raw):
    """Accept unlimited buttons separated by ';' OR new lines."""
    rows = []
    for item in raw.replace("\r", "").replace("\n", ";").split(";"):
        if "|" not in item:
            continue
        label, url = item.split("|", 1)
        label, url = label.strip(), url.strip()
        if label and url:
            rows.append([InlineKeyboardButton(text=label, url=url)])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def channel_buttons():
    """Unlimited private Request-to-Join links; no channel IDs needed."""
    raw = db.get_settings().get("join_links", "") or ""
    return build_buttons(raw)


def merge_keyboards(*keyboards):
    rows = []
    for kb in keyboards:
        if kb:
            rows.extend(kb.inline_keyboard)
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


@dp.message(Command("admin"))
async def admin(m):
    if await auth_msg(m):
        await m.answer("👑 Admin Panel", reply_markup=admin_kb())

@dp.callback_query(F.data == "home")
async def home(c):
    if await auth_cb(c): 
        await c.message.edit_text("👑 Admin Panel", reply_markup=admin_kb()); await c.answer()

@dp.callback_query(F.data == "premium_ui")
async def premium_ui(c):
    if not await auth_cb(c): return
    s = db.get_settings()
    text = (
        "🎨 <b>Premium UI Composer</b>\n\n"
        "Welcome message:\n"
        f"{escape(s.get('welcome_message',''))}\n\n"
        f"Welcome photo: {'✅' if s.get('welcome_photo') else '❌'}\n"
        f"Buttons: {'✅' if s.get('welcome_buttons') else '❌'}\n"
        f"Join links: {'✅' if s.get('join_links') else '❌'}\n\n"
        "Use the edit buttons below. HTML formatting is supported.\n"
        "Premium/custom emoji can be pasted where Telegram permits it. "
        "The bot sends the resulting text/caption without modifying your manual channel moderation."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Set Welcome Text", callback_data="edit_welcome")],
        [InlineKeyboardButton(text="🖼️ Set Welcome Photo", callback_data="welcome_photo")],
        [InlineKeyboardButton(text="🔗 Set Join Links", callback_data="join_links")],
        [InlineKeyboardButton(text="🔘 Set Buttons", callback_data="welcome_buttons")],
        [InlineKeyboardButton(text="📝 Set Verified Text", callback_data="edit_verified")],
        [InlineKeyboardButton(text="🖼️ Set Verified Photo", callback_data="verified_photo")],
        [InlineKeyboardButton(text="🔘 Set Verified Buttons", callback_data="verified_buttons")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="home")]
    ])
    await c.message.edit_text(text, reply_markup=kb); await c.answer()

@dp.callback_query(F.data == "edit_welcome")
async def edit_welcome(c):
    if not await auth_cb(c): return
    db.set_state(c.from_user.id, "welcome_text")
    await c.message.answer("Send your formatted welcome message. Use Telegram bold/italic/custom emoji or HTML tags like <b>Bold</b> and <tg-emoji emoji-id=\"ID\">😀</tg-emoji>."); await c.answer()

@dp.callback_query(F.data == "edit_verified")
async def edit_verified(c):
    if not await auth_cb(c): return
    db.set_state(c.from_user.id, "verified_text")
    await c.message.answer("Send verified text/caption. Placeholders: {first_name}, {user_id}."); await c.answer()

@dp.callback_query(F.data == "welcome_photo")
async def welcome_photo(c):
    if not await auth_cb(c): return
    db.set_state(c.from_user.id, "welcome_photo")
    await c.message.answer("Send the welcome photo. The photo will be stored locally on the VPS."); await c.answer()

@dp.callback_query(F.data == "verified_photo")
async def verified_photo(c):
    if not await auth_cb(c): return
    db.set_state(c.from_user.id, "verified_photo")
    await c.message.answer("Send the verified photo."); await c.answer()

@dp.callback_query(F.data == "join_links")
async def join_links(c):
    if not await auth_cb(c): return
    db.set_state(c.from_user.id, "join_links")
    await c.message.answer(
        "🔗 <b>Set Join Request Links</b>\n\n"
        "Multiple private channels supported. One per line:\n\n"
        "<code>🔒 Channel 1|https://t.me/+LINK1</code>\n"
        "<code>🔒 Channel 2|https://t.me/+LINK2</code>\n"
        "<code>🔒 Channel 3|https://t.me/+LINK3</code>\n\n"
        "No Chat ID needed. Give the bot Admin + Invite Users via Link in every channel."
    )
    await c.answer()

@dp.callback_query(F.data == "welcome_buttons")
async def welcome_buttons(c):
    if not await auth_cb(c): return
    db.set_state(c.from_user.id, "welcome_buttons")
    await c.message.answer("Send multiple buttons, one per line:\nJoin Channel 1|https://t.me/+LINK1\nJoin Channel 2|https://t.me/+LINK2\nClaim|https://example.com"); await c.answer()

@dp.callback_query(F.data == "verified_buttons")
async def verified_buttons(c):
    if not await auth_cb(c): return
    db.set_state(c.from_user.id, "verified_buttons")
    await c.message.answer("Send multiple buttons, one per line:\nJoin Channel 1|https://t.me/+LINK1\nJoin Channel 2|https://t.me/+LINK2\nClaim|https://example.com"); await c.answer()

@dp.message()
async def router(m: Message, bot: Bot):
    uid = m.from_user.id
    if not is_admin(uid): return
    state = db.get_state(uid)
    if not state: return

    if state.endswith("_photo"):
        if not m.photo:
            await m.answer("Please send a photo.")
            return
        photo = m.photo[-1]
        dest = os.path.join(MEDIA_DIR, f"{state}_{uid}.jpg")
        await bot.download(photo, destination=dest)
        db.set_setting(state, dest)
        db.clear_state(uid)
        await m.answer("✅ Photo saved.", reply_markup=admin_kb())
        return

    value = m.text or ""
    if state == "welcome_text":
        db.set_setting("welcome_message", value)
        db.set_setting("welcome_html", message_to_html(m))
        db.clear_state(uid)
        await m.answer("✅ Welcome text + custom emoji entities saved.", reply_markup=admin_kb())
    elif state == "verified_text":
        db.set_setting("verified_message", value)
        db.set_setting("verified_html", message_to_html(m))
        db.clear_state(uid)
        await m.answer("✅ Verified text + custom emoji entities saved.", reply_markup=admin_kb())
    elif state in ("welcome_buttons", "verified_buttons"):
        db.set_setting(state, value); db.clear_state(uid)
        await m.answer("✅ Buttons updated. Multiple buttons supported.", reply_markup=admin_kb())
    elif state == "join_links":
        db.set_setting("join_links", value); db.clear_state(uid)
        await m.answer("✅ Join links saved. Multiple private channels supported.", reply_markup=admin_kb())
    elif state == "await_channel":
        try:
            # Format: CHANNEL_ID | INVITE_URL
            # Optional public username can be used as title: @channelusername | https://t.me/...
            parts = [x.strip() for x in value.split("|", 1)]
            cid = int(parts[0])
            invite_url = parts[1] if len(parts) == 2 else ""
            chat = await bot.get_chat(cid)

            with db.conn() as c:
                c.execute(
                    """INSERT INTO channels(chat_id,title,invite_url) VALUES(?,?,?)
                       ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, invite_url=excluded.invite_url""",
                    (cid, chat.title or str(cid), invite_url)
                )
            db.clear_state(uid)
            if invite_url:
                await m.answer(
                    f"✅ Channel added/updated.\n\n📢 {escape(chat.title or str(cid))}\n🔗 Join link saved.",
                    reply_markup=admin_kb()
                )
            else:
                await m.answer(
                    f"✅ Channel added: {escape(chat.title or str(cid))}.\n\n"
                    "⚠️ If this is a private channel, add its request-to-join invite link too:\n"
                    "<code>-1001234567890 | https://t.me/+XXXX</code>",
                    reply_markup=admin_kb()
                )
        except Exception as e:
            await m.answer(f"Could not add channel: {escape(str(e))}")
    elif state == "await_admin":
        try:
            db.add_admin(int(value.strip())); db.clear_state(uid)
            await m.answer("✅ Admin added.", reply_markup=admin_kb())
        except ValueError: await m.answer("Invalid numeric Telegram user ID.")
    elif state == "await_broadcast":
        db.clear_state(uid); users = db.list_verified(100000); sent=failed=0
        for u in users:
            try: await bot.send_message(u["user_id"], value); sent += 1
            except Exception: failed += 1
        await m.answer(f"📢 Broadcast finished.\nSent: {sent}\nFailed: {failed}", reply_markup=admin_kb())

@dp.callback_query(F.data == "stats")
async def stats(c):
    if not await auth_cb(c): return
    s=db.stats()
    await c.message.edit_text(
        f"📊 <b>Stats</b>\n\n👥 Verified: <b>{s['verified']}</b>\n"
        f"📢 Channels: <b>{s['channels']}</b>\n👤 Admins: <b>{s['admins']}</b>\n"
        f"📨 Join requests: <b>{s['requests']}</b>", reply_markup=back_kb())
    await c.answer()

@dp.callback_query(F.data == "verified")
async def verified(c):
    if not await auth_cb(c): return
    rows=db.list_verified(50)
    text="👥 <b>Verified Users</b>\n\n"+("\n".join(f"• <code>{r['user_id']}</code> {escape(r['name'] or '')}" for r in rows) if rows else "No verified users.")
    await c.message.edit_text(text, reply_markup=back_kb()); await c.answer()

@dp.callback_query(F.data == "channels")
async def channels(c):
    if not await auth_cb(c): return
    s = db.get_settings()
    raw = s.get("join_links", "") or ""
    links = [x.strip() for x in raw.replace("\r", "").replace("\n", ";").split(";") if x.strip()]
    text = "🔗 <b>Join Request Links</b>\n\n"
    text += "\n".join(f"• {escape(x)}" for x in links) if links else "No join links configured."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Add / Edit Join Links", callback_data="join_links")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="home")]
    ])
    await c.message.edit_text(text, reply_markup=kb)
    await c.answer()

@dp.callback_query(F.data == "admins")
async def admins(c):
    if not await auth_cb(c): return
    rows=db.list_admins(); buttons=[]
    if c.from_user.id == OWNER_ID:
        for r in rows: buttons.append([InlineKeyboardButton(text=f"🗑 Remove {r['user_id']}", callback_data=f"deladmin:{r['user_id']}")])
        buttons.append([InlineKeyboardButton(text="➕ Add Admin", callback_data="add_admin")])
    buttons.append([InlineKeyboardButton(text="⬅️ Back", callback_data="home")])
    text="👤 <b>Admins</b>\n\n"+("\n".join(f"• <code>{r['user_id']}</code>" for r in rows) if rows else "No additional admins.")
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)); await c.answer()

@dp.callback_query(F.data == "add_admin")
async def add_admin(c):
    if c.from_user.id != OWNER_ID: return await c.answer("Owner only.", show_alert=True)
    db.set_state(c.from_user.id, "await_admin"); await c.message.answer("Send numeric Telegram user ID."); await c.answer()

@dp.callback_query(F.data.startswith("deladmin:"))
async def deladmin(c):
    if c.from_user.id != OWNER_ID: return await c.answer("Owner only.", show_alert=True)
    db.remove_admin(int(c.data.split(":")[1])); await c.answer("Removed."); await admins(c)

@dp.callback_query(F.data == "broadcast")
async def broadcast(c):
    if await auth_cb(c):
        db.set_state(c.from_user.id, "await_broadcast"); await c.message.answer("Send broadcast text."); await c.answer()

@dp.chat_join_request()
async def join_request(req: ChatJoinRequest, bot: Bot):
    # INTENTIONALLY NO APPROVE/DECLINE CALLS.
    u = req.from_user
    chat_id = req.chat.id

    # No manual channel-ID whitelist: Telegram supplies req.chat.id.
    db.record_join_request(u.id, chat_id, u.full_name)
    target_chat_id = req.user_chat_id
    verified = db.is_verified(u.id)
    s = db.get_settings()

    log.info(
        "JOIN REQUEST DETECTED chat_id=%s title=%r user_id=%s user_chat_id=%s verified=%s invite=%s",
        chat_id, req.chat.title, u.id, target_chat_id, verified,
        getattr(req.invite_link, "invite_link", None)
    )

    if verified:
        template = s.get("verified_html") or s.get("verified_message", "✅ Verified, {first_name}.")
        text = template.format(first_name=escape(u.first_name or "there"), user_id=u.id)
        kb = build_buttons(s.get("verified_buttons", ""))
        photo = s.get("verified_photo", "")
    else:
        # Re-use the verified UI for the response so an unverified request
        # still gets a visible result/Claim button instead of silent logging.
        text = (
            "⏳ <b>REQUEST RECEIVED!</b>\n\n"
            f"👤 Welcome, <b>{escape(u.first_name or 'there')}</b>!\n\n"
            "🔐 Your join request has been received.\n"
            "⏳ Please wait for Admin approval.\n\n"
            "🎁 Use the button below to continue."
        )
        kb = build_buttons(s.get("verified_buttons", ""))
        photo = s.get("verified_photo", "")

    try:
        if photo:
            await bot.send_photo(
                target_chat_id, FSInputFile(photo), caption=text,
                reply_markup=kb
            )
        else:
            await bot.send_message(
                target_chat_id, text, reply_markup=kb
            )
        log.info("Join-request response sent to user_chat_id=%s", target_chat_id)
    except Exception:
        log.exception(
            "Could not send join-request response to user_chat_id=%s",
            target_chat_id
        )


async def main():
    db.init()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    log.info("Started. Manual Accept/Reject only.")
    # Explicitly request chat_join_request updates.
    await dp.start_polling(
        bot,
        allowed_updates=["message", "callback_query", "chat_join_request"]
    )
if __name__ == "__main__":
    asyncio.run(main())
