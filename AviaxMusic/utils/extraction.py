import re
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message, User

from AviaxMusic import app

def is_valid_username(username: str) -> bool:
    # Telegram usernames: 5-32 chars, a-z, A-Z, 0-9, underscore, no leading digit/underscore
    return re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{4,31}", username) is not None

async def extract_user(m: Message) -> User:
    if m.reply_to_message:
        return m.reply_to_message.from_user

    # Defensive: check for entities and m.command length
    if not m.entities or not hasattr(m, "command") or len(m.command) < 2:
        raise ValueError("No user argument found.")

    msg_entities = m.entities[1] if m.text.startswith("/") and len(m.entities) > 1 else m.entities[0]
    val = (
        msg_entities.user.id
        if msg_entities.type == MessageEntityType.TEXT_MENTION
        else m.command[1]
    )

    # Accept only valid int (user id) or username
    if isinstance(val, int) or (isinstance(val, str) and val.isdecimal()):
        return await app.get_users(int(val))
    elif isinstance(val, str) and is_valid_username(val):
        return await app.get_users(val)
    else:
        raise ValueError("Invalid user identifier: must be a user ID or a valid username.")
