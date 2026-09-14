import html
import re

from .. import loader, utils


@loader.tds
class ProfileCardMod(loader.Module):
    """Создаёт карточку-профиль пользователя по его сообщениям в чате"""

    strings = {"name": "ProfileCard"}

    STOP_WORDS = {
        "это", "что", "как", "всё", "все", "для", "или", "если", "ещё", "еще",
        "был", "была", "было", "были", "быть", "есть", "нет", "да", "не",
        "уже", "тоже", "также", "себя", "свой", "моя", "мой", "мне", "меня",
        "тебя", "тебе", "него", "неё", "нее", "них", "нам", "вам", "они",
        "она", "оно", "этот", "эта", "эти", "тот", "та", "те", "чем",
        "http", "https", "www", "com", "t.me",
    }

    async def whoiscmd(self, message):
        """Команда .whois — карточка пользователя.
        Используй в ответ на сообщение или напиши .whois @username"""
        try:
            reply = await message.get_reply_message()
            target = None

            if reply:
                target = await reply.get_sender()
            else:
                args = utils.get_args_raw(message)
                if args:
                    try:
                        target = await message.client.get_entity(args.strip())
                    except Exception:
                        await utils.answer(message, "❌ Не могу найти такого пользователя.")
                        return
                else:
                    target = await message.get_sender()

            if not target or not hasattr(target, "id"):
                await utils.answer(message, "❌ Не удалось определить пользователя.")
                return

            messages = []
            async for msg in message.client.iter_messages(
                message.chat_id, from_user=target.id, limit=300
            ):
                text = msg.raw_text or ""
                if text and not text.startswith("."):
                    messages.append(text)
                if len(messages) >= 100:
                    break

            if not messages:
                await utils.answer(
                    message,
                    "❌ Не нашёл сообщений этого пользователя в чате."
                )
                return

            total = len(messages)
            total_chars = sum(len(m) for m in messages)
            avg_len = total_chars // total

            emoji_count = 0
            for m in messages:
                for ch in m:
                    code = ord(ch)
                    if 0x1F300 <= code <= 0x1FAFF or 0x2600 <= code <= 0x27BF:
                        emoji_count += 1

            words = {}
            for m in messages:
                clean = re.sub(r"https?://\S+|@\w+|#\w+", " ", m.lower())
                for w in clean.split():
                    w = w.strip(".,!?;:()[]\"'«»—-…")
                    if len(w) > 3 and not w.isdigit() and w not in self.STOP_WORDS:
                        words[w] = words.get(w, 0) + 1
            top_words = sorted(words.items(), key=lambda x: x[1], reverse=True)[:5]

            if avg_len < 20:
                style = "⚡ Коротко и по делу"
            elif avg_len < 60:
                style = "💬 Обычный собеседник"
            else:
                style = "📚 Любит развёрнутые сообщения"

            emoji_ratio = emoji_count / max(total, 1)
            if emoji_ratio > 2:
                emoji_style = "😄 Очень эмоциональный"
            elif emoji_ratio > 0.5:
                emoji_style = "🙂 Умеренно эмоциональный"
            else:
                emoji_style = "😐 Сдержанный"

            if total < 10:
                activity = "👻 Редкий гость"
            elif total < 30:
                activity = "🌤 Появляется иногда"
            else:
                activity = "🔥 Активный участник"

            name = html.escape(target.first_name or "Без имени")
            username = (
                f"@{target.username}"
                if getattr(target, "username", None) else "—"
            )
            top_words_str = (
                ", ".join(
                    f"<code>{html.escape(w)}</code> ({c})" for w, c in top_words
                )
                if top_words else "—"
            )

            text = (
                f"<b>📇 Карточка профиля</b>\n\n"
                f"<b>Имя:</b> {name}\n"
                f"<b>Юзернейм:</b> {username}\n"
                f"<b>ID:</b> <code>{target.id}</code>\n\n"
                f"<b>📊 Статистика</b>\n"
                f"• Проанализировано: <b>{total}</b> сообщ.\n"
                f"• Средняя длина: <b>{avg_len}</b> симв.\n"
                f"• Эмодзи: <b>{emoji_count}</b>\n\n"
                f"<b>🎭 Стиль общения</b>\n"
                f"• {style}\n"
                f"• {emoji_style}\n"
                f"• {activity}\n\n"
                f"<b>💬 Частые слова</b>\n"
                f"{top_words_str}"
            )

            await utils.answer(message, text)

        except Exception as e:
            await utils.answer(
                message,
                f"⚠️ Ошибка: <code>{html.escape(str(e))}</code>"
            )