import aiohttp
import asyncio
import html
import io
import json
import re
import time

from .. import loader, utils


@loader.tds
class AIMod(loader.Module):
    """AI-собеседник + анализ чата. Создатель: @fiftarir"""
    strings = {"name": "AI"}

    CREATOR_USERNAME = "@fiftarir"
    TREE_EMOJI = "🌳"
    TREE_RESPONSE = "ох.. Создатель?"

    CREATOR_ID = 1314782374

    PRESETS = {
        "cook": "Ты — опытный повар. Отвечай рецептами, советами по продуктам и техникам готовки. Кратко.",
        "coder": "Ты — senior-разработчик. Отвечай кодом, примерами и технически точно.",
        "psychologist": "Ты — поддерживающий психолог. Слушай, задавай вопросы, помогай разобраться. Без диагнозов.",
        "sarcastic": "Ты — саркастичный собеседник. Отвечай с иронией, но по сути. Не груби.",
        "teacher": "Ты — терпеливый учитель. Объясняй просто, с примерами, по шагам.",
        "philosopher": "Ты — философ. Отвечай размышлениями и вопросами, ссылайся на идеи.",
        "pirate": "Ты — пират. Отвечай в морском стиле, с 'арр' и 'йо-хо-хо'.",
        "anime": "Ты — персонаж аниме. Отвечай эмоционально, с 'ня' и восклицаниями.",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "provider", "groq",
                "Провайдер: groq, gemini, openrouter, mistral.",
                validator=loader.validators.Choice(["groq", "gemini", "openrouter", "mistral"]),
            ),
            loader.ConfigValue("api_key", "", "API-ключ.", validator=loader.validators.Hidden()),
            loader.ConfigValue("model", "", "Модель.", validator=loader.validators.String()),
            loader.ConfigValue(
                "system_prompt",
                "Ты — дружелюбный и остроумный помощник в Telegram-чате. Отвечай кратко, по делу, с легким юмором.",
                "Характер бота по умолчанию.", validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "max_tokens", 500, "Максимум токенов.",
                validator=loader.validators.Integer(minimum=50, maximum=4000),
            ),
            loader.ConfigValue(
                "temperature", 0.8, "Креативность.",
                validator=loader.validators.Float(minimum=0.0, maximum=2.0),
            ),
            loader.ConfigValue(
                "history_size", 20, "Сообщений в истории диалога.",
                validator=loader.validators.Integer(minimum=2, maximum=100),
            ),
            loader.ConfigValue(
                "summary_size", 100, "Сообщений для .ai summary.",
                validator=loader.validators.Integer(minimum=20, maximum=1000),
            ),
            loader.ConfigValue(
                "summary_prompt",
                "Ты — аналитик чата. Сделай краткую сводку обсуждения: "
                "о чём говорили, главные темы, ключевые выводы. "
                "Пиши по-русски, структурировано, не больше 10 строк.",
                "Инструкция для саммари.", validator=loader.validators.String(),
            ),
            loader.ConfigValue("ignore_bots", True, "Игнорировать ботов.", validator=loader.validators.Boolean()),
            loader.ConfigValue("ignore_commands", True, "Игнорировать команды.", validator=loader.validators.Boolean()),
            loader.ConfigValue("reply_to_trigger", "", "Слово-триггер.", validator=loader.validators.String()),
            loader.ConfigValue(
                "max_history_per_chat", 50, "Максимум чатов в истории.",
                validator=loader.validators.Integer(minimum=1, maximum=1000),
            ),
            loader.ConfigValue(
                "reply_only_when_mentioned", False, "Отвечать только при упоминании.",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "save_history_to_db", False, "Сохранять историю в БД.",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue("auto_reactions", False, "Авто-реакции.", validator=loader.validators.Boolean()),
            loader.ConfigValue("diary_enabled", False, "Дневник в Saved Messages.", validator=loader.validators.Boolean()),
            loader.ConfigValue(
                "diary_hour", 22, "Час дневника (0-23).",
                validator=loader.validators.Integer(minimum=0, maximum=23),
            ),
            loader.ConfigValue(
                "reply_context_enabled", True,
                "Учитывать сообщение, на которое отвечает пользователь.",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "reply_context_max_chars", 500,
                "Максимум символов из сообщения-контекста.",
                validator=loader.validators.Integer(minimum=50, maximum=2000),
            ),
        )
        self._history = {}
        self._tree_replied = set()
        self._chat_order = []
        self._stats = {"requests": 0, "errors": 0, "summaries": 0}
        self._diary_task = None
        self._last_diary_date = None
        self._banned = set()
        self._silent_banned = set()
        self._gagged_chats = set()
        self._gagged_users = {}
        self._maintenance = False
        self._tree_enabled = True
        self._user_msg_count = {}

    _PROVIDERS = {
        "groq": {"url": "https://api.groq.com/openai/v1/chat/completions", "default_model": "llama-3.3-70b-versatile"},
        "gemini": {
            "url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
            "default_model": "gemini-2.5-flash", "gemini": True,
        },
        "openrouter": {"url": "https://openrouter.ai/api/v1/chat/completions", "default_model": "openrouter/free"},
        "mistral": {"url": "https://api.mistral.ai/v1/chat/completions", "default_model": "mistral-small-latest"},
    }

    def _is_creator(self, message):
        return message.sender_id == self.CREATOR_ID

    async def _deny(self, message):
        await utils.answer(
            message,
            "🔒 <b>Только для создателя</b>\n"
            f"<i>Модуль создан {self.CREATOR_USERNAME}</i>",
        )

    async def client_ready(self, client, db):
        self._client = client
        self.db = db
        self._me = await client.get_me()
        if not self.CREATOR_ID:
            self.CREATOR_ID = self._me.id
        try:
            self._banned = set(self.db.get("AI", "banned", []) or [])
            self._silent_banned = set(self.db.get("AI", "silent_banned", []) or [])
            self._gagged_chats = set(self.db.get("AI", "gagged_chats", []) or [])
            self._gagged_users = self.db.get("AI", "gagged_users", {}) or {}
            self._maintenance = self.db.get("AI", "maintenance", False)
            self._tree_enabled = self.db.get("AI", "tree_enabled", True)
            self._user_msg_count = self.db.get("AI", "user_msg_count", {}) or {}
            if self.config["save_history_to_db"]:
                chat_ids = self.db.get("AI", "chat_ids", []) or []
                for cid in chat_ids:
                    hist = self.db.get("AI", f"history_{cid}", [])
                    if hist:
                        self._history[int(cid)] = hist
                        self._chat_order.append(int(cid))
        except Exception:
            pass
        if self.config["diary_enabled"] and self._diary_task is None:
            self._diary_task = asyncio.create_task(self._diary_loop())

    async def on_unload(self):
        if self._diary_task:
            self._diary_task.cancel()
            self._diary_task = None

    def _save_state(self):
        try:
            self.db.set("AI", "banned", list(self._banned))
            self.db.set("AI", "silent_banned", list(self._silent_banned))
            self.db.set("AI", "gagged_chats", list(self._gagged_chats))
            self.db.set("AI", "gagged_users", self._gagged_users)
            self.db.set("AI", "maintenance", self._maintenance)
            self.db.set("AI", "tree_enabled", self._tree_enabled)
            self.db.set("AI", "user_msg_count", self._user_msg_count)
        except Exception:
            pass

    def _is_user_gagged(self, user_id, chat_id):
        if user_id not in self._gagged_users:
            return False
        chats = self._gagged_users[user_id]
        if not chats:
            return True
        return chat_id in chats

    def _get_history(self, chat_id):
        return self._history.get(chat_id, [])

    def _add_to_history(self, chat_id, role, content):
        if chat_id not in self._history:
            self._history[chat_id] = []
            self._chat_order.append(chat_id)
            max_chats = int(self.config["max_history_per_chat"])
            while len(self._chat_order) > max_chats:
                old = self._chat_order.pop(0)
                self._history.pop(old, None)
                if self.config["save_history_to_db"]:
                    try:
                        self.db.set("AI", f"history_{old}", [])
                    except Exception:
                        pass
        self._history[chat_id].append({"role": role, "content": content})
        limit = int(self.config["history_size"])
        if len(self._history[chat_id]) > limit:
            self._history[chat_id] = self._history[chat_id][-limit:]
        if self.config["save_history_to_db"]:
            try:
                self.db.set("AI", f"history_{chat_id}", self._history[chat_id])
                self.db.set("AI", "chat_ids", self._chat_order)
            except Exception:
                pass

    def _get_user_prompt(self, user_id):
        try:
            gp = self.db.get("AI", "global_prompt", None)
            if gp:
                return gp
        except Exception:
            pass
        try:
            custom = self.db.get("AI", f"user_prompt_{user_id}", None)
        except Exception:
            custom = None
        return custom or self.config["system_prompt"]

    async def _get_reply_context(self, message, skip_bot_id=None):
        if not self.config["reply_context_enabled"]:
            return ""
        if not message.is_reply:
            return ""
        try:
            reply = await message.get_reply_message()
            if not reply:
                return ""
            if skip_bot_id is not None and reply.sender_id == skip_bot_id:
                return ""
            text = reply.raw_text
            if not text:
                if reply.photo:
                    text = "(фото)"
                elif reply.video:
                    text = "(видео)"
                elif reply.voice:
                    text = "(голосовое)"
                elif reply.sticker:
                    text = "(стикер)"
                elif reply.document:
                    text = "(файл)"
                else:
                    text = "(без текста)"
            try:
                sender = await reply.get_sender()
                name = getattr(sender, "first_name", None) or getattr(sender, "title", None) or "Кто-то"
            except Exception:
                name = "Кто-то"
            limit = int(self.config["reply_context_max_chars"])
            if len(text) > limit:
                text = text[:limit] + "…"
            return f'[Ответ на сообщение от {name}: "{text}"]'
        except Exception:
            return ""

    async def _build_user_message(self, message, user_text, skip_bot_id=None):
        context = await self._get_reply_context(message, skip_bot_id=skip_bot_id)
        if context:
            return f"{context}\n\n{user_text}"
        return user_text

    async def _ask_ai(self, messages, use_history_chat_id=None):
        if not self.config["api_key"]:
            return "❌ API-ключ не настроен. Открой <code>.cfg AI</code> и вставь ключ."
        provider = self.config["provider"]
        cfg = self._PROVIDERS.get(provider)
        if not cfg:
            return f"❌ Неизвестный провайдер: {provider}"
        model = self.config["model"] or cfg["default_model"]
        key = self.config["api_key"]
        self._stats["requests"] += 1
        try:
            async with aiohttp.ClientSession() as session:
                if cfg.get("gemini"):
                    url = cfg["url"].format(model=model, key=key)
                    contents = []
                    for m in messages:
                        if m["role"] == "system":
                            continue
                        role = "user" if m["role"] == "user" else "model"
                        contents.append({"role": role, "parts": [{"text": m["content"]}]})
                    system = next((m["content"] for m in messages if m["role"] == "system"), "")
                    payload = {
                        "contents": contents,
                        "systemInstruction": {"parts": [{"text": system}]},
                        "generationConfig": {
                            "temperature": float(self.config["temperature"]),
                            "maxOutputTokens": int(self.config["max_tokens"]),
                        },
                    }
                    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as r:
                        data = await r.json()
                        if r.status != 200:
                            self._stats["errors"] += 1
                            return f"⚠️ Ошибка API: {r.status}\n<code>{html.escape(str(data))[:300]}</code>"
                        reply = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                else:
                    payload = {
                        "model": model, "messages": messages,
                        "max_tokens": int(self.config["max_tokens"]),
                        "temperature": float(self.config["temperature"]),
                    }
                    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                    async with session.post(cfg["url"], json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as r:
                        if r.status != 200:
                            self._stats["errors"] += 1
                            err = await r.text()
                            return f"⚠️ Ошибка API: {r.status}\n<code>{html.escape(err[:300])}</code>"
                        data = await r.json()
                        reply = data["choices"][0]["message"]["content"].strip()
            if use_history_chat_id is not None:
                self._add_to_history(use_history_chat_id, "assistant", reply)
            return html.escape(reply)
        except aiohttp.ClientError as e:
            self._stats["errors"] += 1
            return f"⚠️ Ошибка сети: <code>{html.escape(str(e))}</code>"
        except Exception as e:
            self._stats["errors"] += 1
            return f"⚠️ Ошибка: <code>{html.escape(str(e))}</code>"

    async def _collect_messages(self, message, limit, from_user=None):
        collected = []
        async for msg in message.client.iter_messages(message.chat_id, limit=limit * 3, from_user=from_user):
            if len(collected) >= limit:
                break
            if not msg.raw_text:
                continue
            if self.config["ignore_commands"] and msg.raw_text.startswith((".", "/", "!")):
                continue
            if self.config["ignore_bots"]:
                sender = await msg.get_sender()
                if sender and getattr(sender, "bot", False):
                    continue
            name = "Кто-то"
            try:
                sender = await msg.get_sender()
                name = getattr(sender, "first_name", None) or getattr(sender, "title", None) or "Кто-то"
            except Exception:
                pass
            collected.append(f"{name}: {msg.raw_text}")
        collected.reverse()
        return collected

    def _pick_reaction(self, text):
        t = (text or "").lower()
        if any(w in t for w in ["ахах", "ржу", "😂", "🤣", "лол", "ору"]):
            return "😂"
        if any(w in t for w in ["спасибо", "круто", "супер", "отлично", "топ", "кайф"]):
            return "🔥"
        if any(w in t for w in ["люблю", "❤", "😍", "обожаю"]):
            return "❤"
        if any(w in t for w in ["грустно", "😢", "😭", "печаль"]):
            return "😢"
        if any(w in t for w in ["думаю", "интересно", "хм", "возможно"]):
            return "🤔"
        if any(w in t for w in ["ура", "победа", "получилось", "🎉"]):
            return "🎉"
        return None

    async def _diary_loop(self):
        while True:
            try:
                now = time.localtime()
                date = time.strftime("%Y-%m-%d", now)
                if now.tm_hour == int(self.config["diary_hour"]) and self._last_diary_date != date:
                    self._last_diary_date = date
                    await self._send_diary()
            except Exception:
                pass
            await asyncio.sleep(300)

    async def _send_diary(self):
        if not self._chat_order:
            return
        parts = []
        for cid in self._chat_order[-5:]:
            try:
                msgs = []
                async for m in self._client.iter_messages(cid, limit=50):
                    if not m.raw_text:
                        continue
                    if self.config["ignore_commands"] and m.raw_text.startswith((".", "/", "!")):
                        continue
                    msgs.append(m.raw_text)
                if not msgs:
                    continue
                try:
                    chat = await self._client.get_entity(cid)
                    title = getattr(chat, "title", None) or "Личный чат"
                except Exception:
                    title = "Чат"
                parts.append(f"--- {title} ---\n" + "\n".join(msgs[-30:]))
            except Exception:
                continue
        if not parts:
            return
        text = "\n\n".join(parts)
        if len(text) > 10000:
            text = text[-10000:]
        prompt = "Сделай краткий дневник за сутки по этим чатам. 5-10 строк, по-русски.\n\n" + text
        messages = [
            {"role": "system", "content": "Ты — составитель дневника."},
            {"role": "user", "content": prompt},
        ]
        summary = await self._ask_ai(messages)
        try:
            await self._client.send_message("me", f"📔 <b>Дневник за {time.strftime('%d.%m.%Y')}</b>\n\n{summary}")
        except Exception:
            pass

    # ─── Вспомогательные методы для подкоманд ───
    async def _do_ask(self, message, text):
        user_prompt = self._get_user_prompt(message.sender_id)
        final_text = await self._build_user_message(message, text)
        self._add_to_history(message.chat_id, "user", final_text)
        messages = [{"role": "system", "content": user_prompt}] + self._get_history(message.chat_id)
        await utils.answer(message, "🤔 <i>Думаю…</i>")
        answer = await self._ask_ai(messages, use_history_chat_id=message.chat_id)
        await utils.answer(message, answer)

    async def _do_summary(self, message, args):
        limit = int(self.config["summary_size"])
        from_user = None
        if args:
            for p in args.split():
                if p.startswith("@"):
                    try:
                        entity = await message.client.get_entity(p)
                        from_user = entity.id
                    except Exception:
                        await utils.answer(message, f"❌ Не нашёл {html.escape(p)}")
                        return
                elif p.isdigit():
                    limit = max(20, min(int(p), 1000))
        await utils.answer(message, f"📊 <i>Читаю {limit} сообщений…</i>")
        collected = await self._collect_messages(message, limit, from_user=from_user)
        if len(collected) < 5:
            await utils.answer(message, "❌ Слишком мало сообщений.")
            return
        text = "\n".join(collected)
        if len(text) > 12000:
            text = text[-12000:]
        prompt = f"{self.config['summary_prompt']}\n\nСообщения:\n\n{text}"
        messages = [
            {"role": "system", "content": "Ты — аналитик чатов."},
            {"role": "user", "content": prompt},
        ]
        summary = await self._ask_ai(messages)
        self._stats["summaries"] += 1
        await utils.answer(message, f"📊 <b>Сводка</b> ({len(collected)} сообщ.)\n\n{summary}")

    async def _do_timeline(self, message, args):
        limit = 30
        if args and args.isdigit():
            limit = max(5, min(int(args), 100))
        lines = []
        async for msg in message.client.iter_messages(message.chat_id, limit=limit * 3):
            if not msg.raw_text:
                continue
            if self.config["ignore_commands"] and msg.raw_text.startswith((".", "/", "!")):
                continue
            try:
                sender = await msg.get_sender()
                name = getattr(sender, "first_name", None) or getattr(sender, "title", None) or "?"
            except Exception:
                name = "?"
            when = msg.date.strftime("%H:%M") if msg.date else "??:??"
            text = msg.raw_text[:100]
            lines.append(f"<code>{when}</code> <b>{html.escape(name)}</b>: {html.escape(text)}")
            if len(lines) >= limit:
                break
        if not lines:
            await utils.answer(message, "❌ Нет сообщений для хронологии.")
            return
        lines.reverse()
        await utils.answer(message, "🕐 <b>Хронология</b>\n\n" + "\n".join(lines))

    async def _do_toggle(self, message):
        chat_id = message.chat_id
        if chat_id in self._history:
            del self._history[chat_id]
            if chat_id in self._chat_order:
                self._chat_order.remove(chat_id)
            if self.config["save_history_to_db"]:
                try:
                    self.db.set("AI", f"history_{chat_id}", [])
                except Exception:
                    pass
            await utils.answer(message, "🔇 Режим диалога выключен.")
        else:
            self._history[chat_id] = []
            if chat_id not in self._chat_order:
                self._chat_order.append(chat_id)
            await utils.answer(message, "🔊 Режим диалога включён.")

    async def _do_reset(self, message):
        self._history[message.chat_id] = []
        if self.config["save_history_to_db"]:
            try:
                self.db.set("AI", f"history_{message.chat_id}", [])
            except Exception:
                pass
        await utils.answer(message, "🧹 История этого чата очищена.")

    async def _do_clear(self, message):
        self._history.clear()
        self._chat_order.clear()
        if self.config["save_history_to_db"]:
            try:
                self.db.set("AI", "chat_ids", [])
            except Exception:
                pass
        await utils.answer(message, "🧹 Вся история очищена.")

    async def _do_prompt(self, message, args):
        user_id = message.sender_id
        if not args:
            current = self._get_user_prompt(user_id)
            await utils.answer(
                message,
                f"🎭 <b>Твой характер:</b>\n<i>{html.escape(current)}</i>\n\n"
                "Сменить: <code>.ai prompt текст</code>",
            )
            return
        try:
            self.db.set("AI", f"user_prompt_{user_id}", args)
            await utils.answer(message, f"✅ Твой характер обновлён:\n<i>{html.escape(args)}</i>")
        except Exception as e:
            await utils.answer(message, f"⚠️ Ошибка: {html.escape(str(e))}")

    async def _do_preset(self, message, args):
        user_id = message.sender_id
        if not args:
            presets = "\n".join(f"  • <code>{k}</code>" for k in self.PRESETS)
            await utils.answer(message, f"🎭 <b>Пресеты:</b>\n{presets}\n\n<code>.ai preset coder</code>")
            return
        if args not in self.PRESETS:
            await utils.answer(message, f"❌ Неизвестный пресет. Доступно: {', '.join(self.PRESETS.keys())}")
            return
        try:
            self.db.set("AI", f"user_prompt_{user_id}", self.PRESETS[args])
            await utils.answer(message, f"✅ Пресет <b>{args}</b>:\n<i>{html.escape(self.PRESETS[args])}</i>")
        except Exception as e:
            await utils.answer(message, f"⚠️ Ошибка: {html.escape(str(e))}")

    async def _do_char(self, message, args):
        user_id = message.sender_id
        if args.strip().lower() == "reset":
            try:
                self.db.set("AI", f"user_prompt_{user_id}", None)
            except Exception:
                pass
            await utils.answer(message, "✅ Личный характер сброшен.")
            return
        current = self._get_user_prompt(user_id)
        is_custom = False
        try:
            is_custom = self.db.get("AI", f"user_prompt_{user_id}", None) is not None
        except Exception:
            pass
        status = "личный" if is_custom else "по умолчанию"
        await utils.answer(
            message,
            f"🎭 <b>Твой характер</b> ({status}):\n<i>{html.escape(current)}</i>\n\n"
            "Сменить: <code>.ai prompt текст</code>\nСброс: <code>.ai char reset</code>",
        )

    async def _do_stats(self, message):
        await utils.answer(
            message,
            "📊 <b>Статистика AI</b>\n\n"
            f"  • Запросов: <b>{self._stats['requests']}</b>\n"
            f"  • Ошибок: <b>{self._stats['errors']}</b>\n"
            f"  • Сводок: <b>{self._stats['summaries']}</b>\n"
            f"  • Чатов: <b>{len(self._history)}</b>\n"
            f"  • Триггер: <code>{html.escape(self.config['reply_to_trigger']) or '—'}</code>\n"
            f"  • Авто-реакции: <b>{'вкл' if self.config['auto_reactions'] else 'выкл'}</b>\n"
            f"  • Дневник: <b>{'вкл' if self.config['diary_enabled'] else 'выкл'}</b>\n"
            f"  • Контекст ответа: <b>{'вкл' if self.config['reply_context_enabled'] else 'выкл'}</b>",
        )

    async def _do_export(self, message):
        data = {"history": {str(k): v for k, v in self._history.items()}, "exported_at": time.time()}
        content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        file = io.BytesIO(content)
        file.name = f"ai_history_{int(time.time())}.json"
        await message.client.send_file(message.chat_id, file, caption="📦 Экспорт истории AI")

    async def _do_import(self, message):
        reply = await message.get_reply_message()
        if not reply or not reply.document:
            await utils.answer(message, "❌ Ответь на JSON-файл.")
            return
        try:
            data = await reply.download_media(bytes)
            parsed = json.loads(data.decode("utf-8"))
            hist = parsed.get("history", {})
            count = 0
            for k, v in hist.items():
                try:
                    cid = int(k)
                except ValueError:
                    continue
                self._history[cid] = v
                if cid not in self._chat_order:
                    self._chat_order.append(cid)
                count += 1
            await utils.answer(message, f"✅ Импортировано {count} чатов.")
        except Exception as e:
            await utils.answer(message, f"⚠️ Ошибка: {html.escape(str(e))}")

    async def _do_info(self, message):
        provider = self.config["provider"]
        cfg = self._PROVIDERS.get(provider, {})
        model = self.config["model"] or cfg.get("default_model", "—")
        history_size = sum(len(h) for h in self._history.values())
        await utils.answer(
            message,
            "🤖 <b>AI-модуль — информация</b>\n\n"
            f"  • <b>Создатель:</b> {self.CREATOR_USERNAME}\n"
            f"  • <b>Провайдер:</b> <code>{provider}</code>\n"
            f"  • <b>Модель:</b> <code>{model}</code>\n"
            f"  • <b>Temperature:</b> {self.config['temperature']}\n"
            f"  • <b>Max tokens:</b> {self.config['max_tokens']}\n"
            f"  • <b>История:</b> {history_size} сообщ. в {len(self._history)} чатах\n"
            f"  • <b>Лимит чатов:</b> {self.config['max_history_per_chat']}\n"
            f"  • <b>Сводка:</b> {self.config['summary_size']} сообщ.\n"
            f"  • <b>Триггер:</b> {self.TREE_EMOJI} → <i>{html.escape(self.TREE_RESPONSE)}</i>\n"
            f"  • <b>Триггер-слово:</b> <code>{html.escape(self.config['reply_to_trigger']) or '—'}</code>\n"
            f"  • <b>Авто-реакции:</b> {'вкл' if self.config['auto_reactions'] else 'выкл'}\n"
            f"  • <b>Дневник:</b> {'вкл' if self.config['diary_enabled'] else 'выкл'} в {self.config['diary_hour']}:00\n"
            f"  • <b>Контекст ответа:</b> {'вкл' if self.config['reply_context_enabled'] else 'выкл'}",
        )

    # ─── HELP ───
    def _help_public(self):
        return (
            "🤖 <b>AI-модуль</b>\n"
            f"<i>Создатель: {self.CREATOR_USERNAME}</i>\n\n"
            "💬 <b>Диалог</b>\n"
            "  • <code>.ai вопрос</code> — спросить AI\n"
            "  • <code>.ai toggle</code> — режим диалога\n"
            "  • <code>.ai reset</code> — сброс истории чата\n"
            "  • <code>.ai clear</code> — сброс всей истории\n\n"
            "📊 <b>Анализ</b>\n"
            "  • <code>.ai summary [N] [@user]</code> — сводка\n"
            "  • <code>.ai timeline [N]</code> — хронология\n\n"
            "🎭 <b>Характер</b>\n"
            "  • <code>.ai prompt текст</code> — свой характер\n"
            "  • <code>.ai preset coder</code> — пресет\n"
            "  • <code>.ai char</code> — посмотреть / <code>reset</code>\n\n"
            "⚙️ <b>Прочее</b>\n"
            "  • <code>.ai stats</code> — статистика\n"
            "  • <code>.ai export</code> / <code>.ai import</code> — история\n"
            "  • <code>.ai info</code> — настройки\n"
            "  • <code>.cfg AI</code> — конфиг\n\n"
            "<i>💡 Ответь на сообщение перед .ai — AI учтёт контекст.</i>"
        )

    def _help_admin(self):
        return (
            "👑 <b>Панель создателя</b>\n"
            f"<i>Только для {self.CREATOR_USERNAME}</i>\n\n"
            "🛡️ <b>Модерация</b>\n"
            "  • <code>.aiadmin ban @user</code> — забанить\n"
            "  • <code>.aiadmin unban @user</code> — разбанить\n"
            "  • <code>.aiadmin unban_all</code> — разбанить всех\n"
            "  • <code>.aiadmin banlist</code> — список банов\n"
            "  • <code>.aiadmin silent @user</code> — тихий бан\n"
            "  • <code>.aiadmin unsilent @user</code> — снять тихий\n"
            "  • <code>.aiadmin gag [@user]</code> — заглушить\n"
            "  • <code>.aiadmin ungag [@user]</code> — разглушить\n\n"
            "⚙️ <b>Управление</b>\n"
            "  • <code>.aiadmin maintenance</code> — техрежим\n"
            "  • <code>.aiadmin tree</code> — триггер 🌳\n"
            "  • <code>.aiadmin globalprompt текст</code> / <code>reset</code>\n"
            "  • <code>.aiadmin broadcast текст</code> — AI-рассылка\n"
            "  • <code>.aiadmin announce текст</code> — простое объявление\n"
            "  • <code>.aiadmin dm @user текст</code> — личка\n"
            "  • <code>.aiadmin kill</code> — сброс истории\n\n"
            "📊 <b>Аналитика</b>\n"
            "  • <code>.aiadmin user_info @user</code>\n"
            "  • <code>.aiadmin top5</code>\n"
            "  • <code>.aiadmin export_all</code> — полный дамп"
        )

    # ─── ОСНОВНЫЕ КОМАНДЫ ───
    @loader.command()
    async def ai(self, message):
        """AI: спросить, сводка, характер, настройки. Без аргументов — справка."""
        args = (utils.get_args_raw(message) or "").strip()
        if not args:
            await utils.answer(message, self._help_public())
            return

        parts = args.split(maxsplit=1)
        sub = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        if sub == "help":
            await utils.answer(message, self._help_public())
            return
        if sub == "info":
            await self._do_info(message)
            return
        if sub == "stats":
            await self._do_stats(message)
            return
        if sub in ("summary", "sum"):
            await self._do_summary(message, rest)
            return
        if sub in ("timeline", "tl"):
            await self._do_timeline(message, rest)
            return
        if sub in ("toggle", "on", "off"):
            await self._do_toggle(message)
            return
        if sub == "reset":
            await self._do_reset(message)
            return
        if sub == "clear":
            await self._do_clear(message)
            return
        if sub in ("prompt", "p"):
            await self._do_prompt(message, rest)
            return
        if sub in ("preset", "pr"):
            await self._do_preset(message, rest)
            return
        if sub in ("char", "c"):
            await self._do_char(message, rest)
            return
        if sub == "export":
            await self._do_export(message)
            return
        if sub == "import":
            await self._do_import(message)
            return
        if sub == "admin":
            if not self._is_creator(message):
                await self._deny(message)
                return
            await utils.answer(message, self._help_admin())
            return

        # Если ничего не совпало — это вопрос к AI
        await self._do_ask(message, args)

    @loader.command()
    async def aiadmin(self, message):
        """[Создатель] Панель управления AI-модулем."""
        if not self._is_creator(message):
            await self._deny(message)
            return

        args = (utils.get_args_raw(message) or "").strip()
        if not args:
            # Полная панель
            active_chats = []
            for cid in self._chat_order[-10:]:
                try:
                    chat = await self._client.get_entity(cid)
                    title = getattr(chat, "title", None) or "Личный чат"
                except Exception:
                    title = str(cid)
                active_chats.append(f"  • <code>{cid}</code> — {html.escape(title)}")
            await utils.answer(
                message,
                "👑 <b>Панель создателя</b>\n\n"
                f"  • <b>Режим техрежима:</b> {'🛠 ВКЛ' if self._maintenance else '✅ выкл'}\n"
                f"  • <b>Активных чатов:</b> {len(self._chat_order)}\n"
                f"  • <b>Забанено:</b> {len(self._banned)}\n"
                f"  • <b>Тихих банов:</b> {len(self._silent_banned)}\n"
                f"  • <b>Заглушено чатов:</b> {len(self._gagged_chats)}\n"
                f"  • <b>Заглушено юзеров:</b> {len(self._gagged_users)}\n"
                f"  • <b>Триггер 🌳:</b> {'вкл' if self._tree_enabled else 'выкл'}\n\n"
                "📋 <b>Последние чаты:</b>\n" + ("\n".join(active_chats) or "  • —") + "\n\n"
                + self._help_admin(),
            )
            return

        parts = args.split(maxsplit=1)
        sub = parts[0].lower()
        rest = parts[1].strip() if len(parts) > 1 else ""

        # Модерация
        if sub == "ban":
            await self._admin_ban(message, rest)
        elif sub == "unban":
            await self._admin_unban(message, rest)
        elif sub == "unban_all":
            await self._admin_unban_all(message)
        elif sub == "banlist":
            await self._admin_banlist(message)
        elif sub == "silent":
            await self._admin_silent(message, rest)
        elif sub == "unsilent":
            await self._admin_unsilent(message, rest)
        elif sub == "gag":
            await self._admin_gag(message, rest)
        elif sub == "ungag":
            await self._admin_ungag(message, rest)
        # Управление
        elif sub == "tree":
            self._tree_enabled = not self._tree_enabled
            self._save_state()
            await utils.answer(message, f"🌳 Триггер {'включён' if self._tree_enabled else 'выключен'}.")
        elif sub == "maintenance":
            self._maintenance = not self._maintenance
            self._save_state()
            status = "🛠 включён" if self._maintenance else "✅ выключен"
            await utils.answer(
                message,
                f"<b>Режим техобслуживания {status}.</b>\n"
                f"<i>Бот {'не будет' if self._maintenance else 'снова будет'} отвечать.</i>",
            )
        elif sub == "broadcast":
            await self._admin_broadcast(message, rest)
        elif sub == "announce":
            await self._admin_announce(message, rest)
        elif sub == "dm":
            await self._admin_dm(message, rest)
        elif sub == "kill":
            count = len(self._history)
            self._history.clear()
            self._chat_order.clear()
            if self.config["save_history_to_db"]:
                try:
                    self.db.set("AI", "chat_ids", [])
                except Exception:
                    pass
            await utils.answer(message, f"💀 Очищено чатов: <b>{count}</b>.")
        elif sub == "globalprompt":
            await self._admin_globalprompt(message, rest)
        elif sub == "user_info":
            await self._admin_user_info(message, rest)
        elif sub == "top5":
            await self._admin_top5(message)
        elif sub == "export_all":
            await self._admin_export_all(message)
        else:
            await utils.answer(
                message,
                f"❌ Неизвестная подкоманда: <code>{html.escape(sub)}</code>\n\n"
                + self._help_admin(),
            )

    # ─── АДМИН-МЕТОДЫ ───
    async def _resolve_user(self, message, args):
        if not args:
            reply = await message.get_reply_message()
            if reply:
                return reply.sender_id
            return None
        try:
            entity = await message.client.get_entity(int(args) if args.lstrip("-").isdigit() else args)
            return entity.id
        except Exception:
            return None

    async def _admin_ban(self, message, args):
        uid = await self._resolve_user(message, args)
        if uid is None:
            await utils.answer(message, "❌ Укажи @юзер или ответь на сообщение.")
            return
        self._banned.add(uid)
        self._save_state()
        await utils.answer(message, f"🚫 Забанен: <code>{uid}</code>")

    async def _admin_unban(self, message, args):
        uid = await self._resolve_user(message, args)
        if uid is None:
            await utils.answer(message, "❌ Укажи @юзер или ответь на сообщение.")
            return
        self._banned.discard(uid)
        self._silent_banned.discard(uid)
        self._save_state()
        await utils.answer(message, f"✅ Разбанен: <code>{uid}</code>")

    async def _admin_unban_all(self, message):
        count = len(self._banned) + len(self._silent_banned)
        self._banned.clear()
        self._silent_banned.clear()
        self._save_state()
        await utils.answer(message, f"✅ Разбанено <b>{count}</b> пользователей.")

    async def _admin_banlist(self, message):
        if not self._banned and not self._silent_banned:
            await utils.answer(message, "✅ Список пуст.")
            return
        lines = []
        if self._banned:
            lines.append("<b>🚫 Обычные баны:</b>")
            for uid in self._banned:
                try:
                    entity = await message.client.get_entity(uid)
                    name = getattr(entity, "first_name", None) or "?"
                    username = getattr(entity, "username", None)
                    line = f"  • <code>{uid}</code> — {html.escape(name)}"
                    if username:
                        line += f" (@{username})"
                    lines.append(line)
                except Exception:
                    lines.append(f"  • <code>{uid}</code>")
        if self._silent_banned:
            lines.append("\n<b>🤫 Тихие баны:</b>")
            for uid in self._silent_banned:
                lines.append(f"  • <code>{uid}</code>")
        await utils.answer(message, "🚫 <b>Забаненные</b>\n\n" + "\n".join(lines))

    async def _admin_silent(self, message, args):
        uid = await self._resolve_user(message, args)
        if uid is None:
            await utils.answer(message, "❌ Укажи @юзер или ответь на сообщение.")
            return
        self._silent_banned.add(uid)
        self._banned.discard(uid)
        self._save_state()
        await utils.answer(message, f"🤫 Тихий бан: <code>{uid}</code>")

    async def _admin_unsilent(self, message, args):
        uid = await self._resolve_user(message, args)
        if uid is None:
            await utils.answer(message, "❌ Укажи @юзер или ответь на сообщение.")
            return
        self._silent_banned.discard(uid)
        self._save_state()
        await utils.answer(message, f"✅ Снят тихий бан: <code>{uid}</code>")

    async def _admin_gag(self, message, args):
        if not args:
            self._gagged_chats.add(message.chat_id)
            self._save_state()
            await utils.answer(message, f"🔇 AI заглушён в этом чате (<code>{message.chat_id}</code>).")
            return
        uid = await self._resolve_user(message, args)
        if uid is None:
            await utils.answer(message, "❌ Не нашёл пользователя.")
            return
        uid_str = str(uid)
        if uid_str not in self._gagged_users:
            self._gagged_users[uid_str] = []
        if message.chat_id not in self._gagged_users[uid_str]:
            self._gagged_users[uid_str].append(message.chat_id)
        self._save_state()
        await utils.answer(message, f"🔇 AI заглушён для <code>{uid}</code> в этом чате.")

    async def _admin_ungag(self, message, args):
        if not args:
            self._gagged_chats.discard(message.chat_id)
            self._save_state()
            await utils.answer(message, "🔊 AI разглушён в этом чате.")
            return
        uid = await self._resolve_user(message, args)
        if uid is None:
            await utils.answer(message, "❌ Не нашёл пользователя.")
            return
        uid_str = str(uid)
        if uid_str in self._gagged_users:
            if message.chat_id in self._gagged_users[uid_str]:
                self._gagged_users[uid_str].remove(message.chat_id)
            if not self._gagged_users[uid_str]:
                del self._gagged_users[uid_str]
        self._save_state()
        await utils.answer(message, f"🔊 AI разглушён для <code>{uid}</code>.")

    async def _admin_broadcast(self, message, args):
        if not args:
            await utils.answer(message, "Пример: <code>.aiadmin broadcast напишите привет</code>")
            return
        sent = 0
        failed = 0
        for cid in list(self._chat_order):
            try:
                messages = [{"role": "user", "content": args}]
                answer = await self._ask_ai(messages)
                await self._client.send_message(cid, answer)
                sent += 1
            except Exception:
                failed += 1
                continue
        await utils.answer(message, f"📢 Разослано в <b>{sent}</b> чатов. Ошибок: <b>{failed}</b>.")

    async def _admin_announce(self, message, args):
        if not args:
            await utils.answer(message, "Пример: <code>.aiadmin announce внимание!</code>")
            return
        sent = 0
        failed = 0
        for cid in list(self._chat_order):
            try:
                await self._client.send_message(cid, f"📢 <b>Объявление:</b>\n{html.escape(args)}")
                sent += 1
            except Exception:
                failed += 1
        await utils.answer(message, f"📢 Отправлено в <b>{sent}</b> чатов. Ошибок: <b>{failed}</b>.")

    async def _admin_dm(self, message, args):
        if not args:
            await utils.answer(message, "Пример: <code>.aiadmin dm @user привет</code>")
            return
        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            await utils.answer(message, "Нужно указать получателя и текст.")
            return
        target, text = parts[0], parts[1]
        try:
            entity = await message.client.get_entity(target)
            messages = [{"role": "user", "content": text}]
            answer = await self._ask_ai(messages)
            await self._client.send_message(entity.id, answer)
            await utils.answer(message, f"✉️ Отправлено <b>{html.escape(target)}</b>.")
        except Exception as e:
            await utils.answer(message, f"⚠️ Ошибка: {html.escape(str(e))}")

    async def _admin_globalprompt(self, message, args):
        if not args:
            try:
                current = self.db.get("AI", "global_prompt", None)
            except Exception:
                current = None
            await utils.answer(
                message,
                "🌐 <b>Глобальный характер</b>\n\n"
                f"<b>Текущий:</b> <i>{html.escape(current) if current else '—'}</i>\n\n"
                "Установить: <code>.aiadmin globalprompt текст</code>\n"
                "Сбросить: <code>.aiadmin globalprompt reset</code>",
            )
            return
        if args.lower() == "reset":
            try:
                self.db.set("AI", "global_prompt", None)
            except Exception:
                pass
            await utils.answer(message, "✅ Глобальный характер сброшен.")
            return
        try:
            self.db.set("AI", "global_prompt", args)
            await utils.answer(message, f"🌐 Установлен:\n<i>{html.escape(args)}</i>")
        except Exception as e:
            await utils.answer(message, f"⚠️ Ошибка: {html.escape(str(e))}")

    async def _admin_user_info(self, message, args):
        uid = await self._resolve_user(message, args)
        if uid is None:
            await utils.answer(message, "❌ Укажи @юзер или ответь на сообщение.")
            return
        try:
            entity = await message.client.get_entity(uid)
            name = getattr(entity, "first_name", None) or "?"
            username = getattr(entity, "username", None)
        except Exception:
            name, username = "?", None
        ban_status = "—"
        if uid in self._banned:
            ban_status = "🚫 обычный"
        elif uid in self._silent_banned:
            ban_status = "🤫 тихий"
        personal = None
        try:
            personal = self.db.get("AI", f"user_prompt_{uid}", None)
        except Exception:
            pass
        msg_count = self._user_msg_count.get(str(uid), 0)
        gag_list = self._gagged_users.get(str(uid), [])
        gag_str = f"{len(gag_list)} чат(ов)" if gag_list else "—"
        await utils.answer(
            message,
            "👤 <b>Карточка пользователя</b>\n\n"
            f"  • <b>Имя:</b> {html.escape(name)}\n"
            f"  • <b>Юзернейм:</b> {'@' + username if username else '—'}\n"
            f"  • <b>ID:</b> <code>{uid}</code>\n"
            f"  • <b>Бан:</b> {ban_status}\n"
            f"  • <b>Заглушек:</b> {gag_str}\n"
            f"  • <b>Личный характер:</b> <i>{html.escape(personal[:150]) if personal else '—'}</i>\n"
            f"  • <b>Сообщений AI:</b> {msg_count}",
        )

    async def _admin_top5(self, message):
        if not self._user_msg_count:
            await utils.answer(message, "📊 Пока никого нет в статистике.")
            return
        top = sorted(self._user_msg_count.items(), key=lambda x: x[1], reverse=True)[:5]
        lines = []
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        for i, (uid_str, count) in enumerate(top):
            try:
                entity = await message.client.get_entity(int(uid_str))
                name = getattr(entity, "first_name", None) or "?"
                username = getattr(entity, "username", None)
                display = f"{html.escape(name)}" + (f" (@{username})" if username else "")
            except Exception:
                display = f"<code>{uid_str}</code>"
            lines.append(f"  {medals[i]} {display} — <b>{count}</b>")
        await utils.answer(message, "🏆 <b>Топ-5 активных</b>\n\n" + "\n".join(lines))

    async def _admin_export_all(self, message):
        try:
            global_prompt = self.db.get("AI", "global_prompt", None)
        except Exception:
            global_prompt = None
        user_prompts = {}
        for uid_str in self._user_msg_count.keys():
            try:
                p = self.db.get("AI", f"user_prompt_{uid_str}", None)
                if p:
                    user_prompts[uid_str] = p
            except Exception:
                pass
        data = {
            "version": "1.0", "exported_at": time.time(), "creator": self.CREATOR_USERNAME,
            "history": {str(k): v for k, v in self._history.items()},
            "banned": list(self._banned), "silent_banned": list(self._silent_banned),
            "gagged_chats": list(self._gagged_chats), "gagged_users": self._gagged_users,
            "global_prompt": global_prompt, "user_prompts": user_prompts,
            "user_msg_count": self._user_msg_count, "stats": self._stats,
            "settings": {
                "provider": self.config["provider"], "model": self.config["model"],
                "temperature": self.config["temperature"], "max_tokens": self.config["max_tokens"],
                "history_size": self.config["history_size"], "summary_size": self.config["summary_size"],
            },
        }
        content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        file = io.BytesIO(content)
        file.name = f"ai_full_dump_{int(time.time())}.json"
        await message.client.send_file(message.chat_id, file, caption="📦 Полный дамп AI-модуля")

    # ─── Watcher ───
    @loader.watcher(only_messages=True)
    async def watcher(self, message):
        if not message.raw_text:
            return
        if message.sender_id == self._me.id:
            return
        if self._maintenance and message.sender_id != self.CREATOR_ID:
            return
        if message.sender_id in self._banned:
            return
        if message.sender_id in self._silent_banned:
            return
        if message.chat_id in self._gagged_chats:
            return
        if self._is_user_gagged(message.sender_id, message.chat_id):
            return

        uid_str = str(message.sender_id)
        self._user_msg_count[uid_str] = self._user_msg_count.get(uid_str, 0) + 1

        if self._tree_enabled and self.TREE_EMOJI in message.raw_text:
            if message.sender_id == self.CREATOR_ID:
                if message.id in self._tree_replied:
                    return
                self._tree_replied.add(message.id)
                await utils.answer(message, self.TREE_RESPONSE)
                return

        if self.config["auto_reactions"]:
            reaction = self._pick_reaction(message.raw_text)
            if reaction:
                try:
                    await message.react(reaction)
                except Exception:
                    pass

        if message.raw_text.startswith((".", "/", "!")):
            return

        text_lower = (message.raw_text or "").lower()
        my_username = (self._me.username or "").lower()
        trigger = (self.config["reply_to_trigger"] or "").lower().strip()

        mentioned = bool(my_username) and f"@{my_username}" in text_lower
        triggered = False
        if trigger:
            words = re.findall(r"\w+", text_lower)
            if trigger in words:
                triggered = True

        if mentioned or triggered:
            user_prompt = self._get_user_prompt(message.sender_id)
            final_text = await self._build_user_message(message, message.raw_text)
            self._add_to_history(message.chat_id, "user", final_text)
            messages = [{"role": "system", "content": user_prompt}] + self._get_history(message.chat_id)
            answer = await self._ask_ai(messages, use_history_chat_id=message.chat_id)
            await utils.answer(message, answer)
            self._save_state()
            return

        if not message.is_reply:
            return
        if message.chat_id not in self._history:
            return
        if self.config["reply_only_when_mentioned"] and not (mentioned or triggered):
            return
        reply = await message.get_reply_message()
        if not reply or reply.sender_id != self._me.id:
            return

        user_prompt = self._get_user_prompt(message.sender_id)
        self._add_to_history(message.chat_id, "user", message.raw_text)
        messages = [{"role": "system", "content": user_prompt}] + self._get_history(message.chat_id)
        answer = await self._ask_ai(messages, use_history_chat_id=message.chat_id)
        await utils.answer(message, answer)