import aiohttp
import asyncio
import base64
import hashlib
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
    CREATOR_ID = 1314782374
    TREE_EMOJI = "🌳"
    TREE_RESPONSE = "ох.. Создатель?"
    MAX_MEDIA_SIZE = 20 * 1024 * 1024

    PRESETS = {
        "cook": "Ты — опытный повар. Отвечай рецептами, советами по продуктам и техникам готовки. Кратко. Отвечай на русском.",
        "coder": "Ты — senior-разработчик. Отвечай кодом, примерами и технически точно. Отвечай на русском.",
        "psychologist": "Ты — поддерживающий психолог. Слушай, задавай вопросы, помогай разобраться. Без диагнозов. Отвечай на русском.",
        "sarcastic": "Ты — саркастичный собеседник. Отвечай с иронией, но по сути. Не груби. Отвечай на русском.",
        "teacher": "Ты — терпеливый учитель. Объясняй просто, с примерами, по шагам. Отвечай на русском.",
        "philosopher": "Ты — философ. Отвечай размышлениями и вопросами, ссылайся на идеи. Отвечай на русском.",
        "pirate": "Ты — пират. Отвечай в морском стиле, с 'арр' и 'йо-хо-хо'. Отвечай на русском.",
        "anime": "Ты — персонаж аниме. Отвечай эмоционально, с 'ня' и восклицаниями. Отвечай на русском.",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "provider", "groq",
                "Провайдер: groq, gemini, openrouter, mistral.",
                validator=loader.validators.Choice(["groq", "gemini", "openrouter", "mistral"]),
            ),
            loader.ConfigValue("api_key", "", "API-ключ.", validator=loader.validators.Hidden()),
            loader.ConfigValue("model", "", "Модель для текста.", validator=loader.validators.String()),
            loader.ConfigValue(
                "vision_model", "",
                "Модель для картинок. Пусто — авто для провайдера.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "vision_enabled", True,
                "Разрешить AI смотреть картинки, стикеры, гифки.",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "system_prompt",
                "Ты — дружелюбный и остроумный помощник в Telegram-чате. Отвечай кратко, по делу, с легким юмором. Отвечай всегда на русском языке.",
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
                "summary_size", 100, "Сообщений для .aisummary.",
                validator=loader.validators.Integer(minimum=20, maximum=1000),
            ),
            loader.ConfigValue(
                "summary_prompt",
                "Ты — аналитик чата. Сделай краткую сводку обсуждения: "
                "о чём говорили, главные темы, ключевые выводы. "
                "Пиши по-русски, структурировано, не больше 10 строк.",
                "Инструкция для саммари.", validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "context_size", 100,
                "Сообщений для .aicontext (по умолчанию).",
                validator=loader.validators.Integer(minimum=20, maximum=1000),
            ),
            loader.ConfigValue(
                "context_prompt",
                "Ты — аналитик Telegram-чата. Тебе дают выдержку из сообщений и вопрос. "
                "Ответь на вопрос ОПИРАЯСЬ ТОЛЬКО НА ЭТИ СООБЩЕНИЯ. "
                "Если в сообщениях нет ответа — честно скажи об этом. "
                "Не выдумывай факты. Пиши по-русски, кратко и по делу.",
                "Инструкция для .aicontext.", validator=loader.validators.String(),
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
            loader.ConfigValue(
                "use_notes", True,
                "Использовать память о пользователях в ответах AI.",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "cache_enabled", True,
                "Кэшировать ответы AI. Повторные вопросы не тратят лимиты.",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "cache_ttl_hours", 24,
                "Сколько часов хранить ответы в кэше.",
                validator=loader.validators.Integer(minimum=1, maximum=720),
            ),
            loader.ConfigValue(
                "cache_max_size", 500,
                "Максимум записей в кэше.",
                validator=loader.validators.Integer(minimum=10, maximum=10000),
            ),
            loader.ConfigValue(
                "whitelist_enabled", False,
                "Ограничить AI только белым списком чатов.",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "sanitize_output", True,
                "Убирать 'thinking', 'analysis' и служебные префиксы из ответов AI.",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "auto_memory", True,
                "AI сам запоминает факты о пользователях из их сообщений.",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "auto_memory_prompt",
                "Ты — экстрактор фактов. Прочитай сообщение пользователя и выпиши "
                "ЛЮБЫЕ факты о нём (имя, работа, увлечения, город, питомцы, предпочтения). "
                "Формат строго:\n"
                "- <факт 1>\n"
                "- <факт 2>\n\n"
                "Если фактов нет — ответь ровно: НЕТ\n"
                "Не пиши ничего кроме списка фактов или слова НЕТ.",
                "Инструкция для извлечения фактов.",
                validator=loader.validators.String(),
            ),
        )
        
        self._history = {}
        self._tree_replied = set()
        self._chat_order = []
        self._stats = {
            "requests": 0, "errors": 0, "summaries": 0, "vision": 0, "ocr": 0, "cache_hits": 0,
            "contexts": 0,
            "tokens_in": 0, "tokens_out": 0, "tokens_total": 0,
            "errors_401": 0, "errors_404": 0, "errors_429": 0, "errors_500": 0, "errors_other": 0,
        }
        self._diary_task = None
        self._last_diary_date = None
        self._banned = set()
        self._silent_banned = set()
        self._gagged_chats = set()
        self._gagged_users = {}
        self._maintenance = False
        self._tree_enabled = True
        self._whitelist_chats = set()
        self._user_msg_count = {}
        self._cache = {}

    _PROVIDERS = {
        "groq": {
            "url": "https://api.groq.com/openai/v1/chat/completions",
            "default_model": "llama-3.3-70b-versatile",
            "vision_default": "meta-llama/llama-4-scout-17b-16e-instruct",
        },
        "gemini": {
            "url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
            "default_model": "gemini-2.5-flash",
            "vision_default": "gemini-2.5-flash",
            "gemini": True,
        },
        "openrouter": {
            "url": "https://openrouter.ai/api/v1/chat/completions",
            "default_model": "openrouter/free",
            "vision_default": "openrouter/free",
        },
        "mistral": {
            "url": "https://api.mistral.ai/v1/chat/completions",
            "default_model": "mistral-small-latest",
            "vision_default": "pixtral-12b-2409",
        },
    }

    @staticmethod
    def _compact_num(value) -> str:
        try:
            n = int(value or 0)
        except Exception:
            n = 0
        if n >= 1_000_000:
            return f"{n / 1_000_000:.2f}".rstrip("0").rstrip(".") + "M"
        if n >= 1_000:
            return f"{n / 1_000:.2f}".rstrip("0").rstrip(".") + "K"
        return str(n)

    def _track_usage(self, data):
        try:
            usage = data.get("usage") or {}
        except Exception:
            return
        try:
            self._stats["tokens_in"] += int(usage.get("prompt_tokens") or 0)
            self._stats["tokens_out"] += int(usage.get("completion_tokens") or 0)
            self._stats["tokens_total"] += int(usage.get("total_tokens") or 0)
        except Exception:
            pass

    def _friendly_api_error(self, status, body_text):
        code = int(status or 0)
        if code in (401, 403):
            self._stats["errors_401"] += 1
            return "❌ <b>Ключ отклонён</b>\n<i>Проверь <code>.cfg AI</code> → <code>api_key</code>.</i>"
        if code == 404:
            self._stats["errors_404"] += 1
            return "❌ <b>Модель не найдена</b>\n<i>Проверь <code>model</code> в <code>.cfg AI</code>.</i>"
        if code == 429:
            self._stats["errors_429"] += 1
            return "⏳ <b>Лимит исчерпан</b>\n<i>Подожди минуту или смени провайдера.</i>"
        if code == 413:
            self._stats["errors_other"] += 1
            return "📦 <b>Слишком большой запрос</b>\n<i>Уменьши <code>history_size</code> или <code>context_size</code>.</i>"
        if code >= 500:
            self._stats["errors_500"] += 1
            return f"🔥 <b>Сервер лежит</b> (HTTP {code})\n<i>Попробуй через минуту.</i>"
        self._stats["errors_other"] += 1
        return f"⚠️ <b>Ошибка API {code}</b>\n<code>{html.escape((body_text or '')[:200])}</code>"

    def _sanitize_ai_output(self, text: str) -> str:
        if not text or not self.config["sanitize_output"]:
            return text
        cleaned = str(text)
        cleaned = re.sub(r"<\s*(?:think|thinking|analysis|reasoning)[^>]*>[\s\S]*?<\s*/\s*(?:think|thinking|analysis|reasoning)\s*>", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"```(?:thinking|analysis|reasoning|scratchpad)[\s\S]*?```", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"(?im)^\s*(?:thinking|analysis|reasoning|scratchpad|final answer|answer|reply|assistant)\s*:\s*", "", cleaned)
        cleaned = re.sub(r"\n{4,}", "\n\n\n", cleaned)
        return cleaned.strip()

    async def client_ready(self, client, db):
        self._client = client
        self.db = db
        self._me = await client.get_me()
        if not self.CREATOR_ID:
            self.CREATOR_ID = self._me.id
        self._load_from_db()
        # при перезагрузке всегда восстанавливаем список включённых режимов
        try:
            chat_ids = self.db.get("AI", "chat_ids", []) or []
            self._chat_order = []
            self._history = {}
            for cid in chat_ids:
                cid_int = int(cid)
                hist = self.db.get("AI", f"history_{cid}", []) or []
                self._history[cid_int] = hist
                self._chat_order.append(cid_int)
        except Exception:
            pass
        if self.config["diary_enabled"] and self._diary_task is None:
            self._diary_task = asyncio.create_task(self._diary_loop())

    def _load_from_db(self):
        try:
            self._banned = set(self.db.get("AI", "banned", []) or [])
            self._silent_banned = set(self.db.get("AI", "silent_banned", []) or [])
            self._gagged_chats = set(self.db.get("AI", "gagged_chats", []) or [])
            self._gagged_users = self.db.get("AI", "gagged_users", {}) or {}
            self._maintenance = self.db.get("AI", "maintenance", False)
            self._tree_enabled = self.db.get("AI", "tree_enabled", True)
            self._user_msg_count = self.db.get("AI", "user_msg_count", {}) or {}
            self._whitelist_chats = set(self.db.get("AI", "whitelist_chats", []) or [])
            self._cache = self.db.get("AI", "cache", {}) or {}
            if self.config["save_history_to_db"]:
                chat_ids = self.db.get("AI", "chat_ids", []) or []
                for cid in chat_ids:
                    hist = self.db.get("AI", f"history_{cid}", [])
                    if hist:
                        self._history[int(cid)] = hist
                        self._chat_order.append(int(cid))
        except Exception:
            pass

    async def on_unload(self):
        if self._diary_task:
            self._diary_task.cancel()
            self._diary_task = None
        self._save_cache()

    def _save_cache(self):
        try:
            self.db.set("AI", "cache", self._cache)
        except Exception:
            pass

    def _save_user_count(self):
        try:
            self.db.set("AI", "user_msg_count", self._user_msg_count)
        except Exception:
            pass

    def _save_whitelist(self):
        try:
            self.db.set("AI", "whitelist_chats", list(self._whitelist_chats))
        except Exception:
            pass

    def _cache_key(self, model, messages):
        try:
            payload = {"m": model, "msg": messages}
            blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            return hashlib.sha256(blob).hexdigest()
        except Exception:
            return None

    def _cache_get(self, key):
        if not self.config["cache_enabled"] or not key:
            return None
        entry = self._cache.get(key)
        if not entry:
            return None
        ttl = int(self.config["cache_ttl_hours"]) * 3600
        if time.time() - entry.get("ts", 0) > ttl:
            self._cache.pop(key, None)
            return None
        return entry.get("reply")

    def _cache_set(self, key, reply):
        if not self.config["cache_enabled"] or not key:
            return
        self._cache[key] = {"reply": reply, "ts": time.time()}
        max_size = int(self.config["cache_max_size"])
        if len(self._cache) > max_size:
            items = sorted(self._cache.items(), key=lambda x: x[1].get("ts", 0))
            for k, _ in items[: len(items) - max_size]:
                self._cache.pop(k, None)
        if len(self._cache) % 50 == 0:
            self._save_cache()

    def _is_user_gagged(self, user_id, chat_id):
        if user_id not in self._gagged_users:
            return False
        chats = self._gagged_users[user_id]
        if not chats:
            return True
        return chat_id in chats

    def _whitelist_ok(self, message):
        # Создатель всегда в обход всех проверок
        if message.sender_id == self.CREATOR_ID:
            return True
        # Режим диалога в чате должен быть включён (кем угодно, обычно тобой)
        if message.chat_id not in self._history:
            return False
        # Если включён ещё и whitelist — проверяем его
        if self.config["whitelist_enabled"]:
            return message.chat_id in self._whitelist_chats
        return True

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

    def _get_user_notes(self, uid):
        try:
            return self.db.get("AI", f"user_notes_{uid}", []) or []
        except Exception:
            return []

    def _save_user_notes(self, uid, notes):
        try:
            self.db.set("AI", f"user_notes_{uid}", notes)
        except Exception:
            pass

    def _notes_block(self, uid):
        if not self.config["use_notes"]:
            return ""
        notes = self._get_user_notes(uid)
        if not notes:
            return ""
        lines = "\n".join(f"  - {n}" for n in notes)
        return f"\n\nЧто известно об этом пользователе:\n{lines}\nУчитывай это, но не перечисляй в ответе явно."

    async def _extract_and_save_facts(self, user_id: int, text: str):
        """Фоново извлекает факты из сообщения и сохраняет в память."""
        if not self.config["auto_memory"]:
            return
        if not text or len(text.strip()) < 10:
            return
        try:
            messages = [
                {"role": "system", "content": self.config["auto_memory_prompt"]},
                {"role": "user", "content": text[:1500]},
            ]
            reply = await self._ask_ai(messages)
            if not reply:
                return
            cleaned = re.sub(r"<[^>]+>", "", reply).strip()
            if not cleaned or cleaned.upper().startswith("НЕТ"):
                return
            new_facts = []
            for line in cleaned.splitlines():
                line = line.strip()
                if line.startswith(("-", "•", "*")):
                    fact = line.lstrip("-•* ").strip()
                    if 3 < len(fact) < 200:
                        new_facts.append(fact)
            if not new_facts:
                return
            existing = self._get_user_notes(user_id)
            existing_lower = {e.lower().strip() for e in existing}
            added = 0
            for fact in new_facts[:5]:
                if fact.lower().strip() not in existing_lower:
                    existing.append(fact)
                    existing_lower.add(fact.lower().strip())
                    added += 1
            if added > 0:
                self._save_user_notes(user_id, existing[-50:])
        except Exception:
            pass

    def _get_user_prompt_with_notes(self, uid):
        return self._get_user_prompt(uid) + self._notes_block(uid)

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
            text = reply.raw_text or "(без текста)"
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

    async def _extract_media(self, msg):
        if not msg:
            return None
        try:
            mime = None
            if msg.photo:
                mime = "image/jpeg"
            elif msg.sticker:
                st_mime = getattr(msg.sticker, "mime_type", "") or ""
                if "tgsticker" in st_mime or "tgs" in st_mime:
                    return ("__unsupported__", "Анимированный стикер (.tgs) не поддерживается")
                mime = "video/webm" if "webm" in st_mime else "image/webp"
            elif msg.gif:
                mime = "image/gif"
            elif msg.video:
                mime = "video/mp4"
            else:
                return None
            file_size = 0
            if msg.file and getattr(msg.file, "size", None):
                file_size = msg.file.size
            if file_size and file_size > self.MAX_MEDIA_SIZE:
                return ("__too_big__", "Файл больше 20 МБ")
            data = await msg.download_media(bytes)
            if not data:
                return None
            return (data, mime)
        except Exception as e:
            return ("__error__", str(e))

    def _get_vision_model(self):
        if self.config["vision_model"]:
            return self.config["vision_model"]
        cfg = self._PROVIDERS.get(self.config["provider"], {})
        return cfg.get("vision_default", cfg.get("default_model", ""))

    async def _ask_ai_vision(self, message, user_text, media_msg):
        if not self.config["api_key"]:
            return "❌ API-ключ не настроен."
        extracted = await self._extract_media(media_msg)
        if not extracted:
            return "❌ Не удалось найти медиа."
        if extracted[0] == "__unsupported__":
            return f"⚠️ {extracted[1]}"
        if extracted[0] == "__too_big__":
            return f"⚠️ {extracted[1]}"
        if extracted[0] == "__error__":
            return f"⚠️ Ошибка: {html.escape(extracted[1])}"
        media_bytes, mime = extracted
        b64 = base64.b64encode(media_bytes).decode("ascii")
        provider = self.config["provider"]
        cfg = self._PROVIDERS.get(provider)
        if not cfg:
            return f"❌ Неизвестный провайдер: {provider}"
        model = self._get_vision_model()
        key = self.config["api_key"]
        self._stats["requests"] += 1
        self._stats["vision"] += 1
        user_prompt = self._get_user_prompt_with_notes(message.sender_id)
        if "русск" not in user_prompt.lower():
            user_prompt += "\n\nВАЖНО: отвечай ТОЛЬКО на русском языке."
        text_part = user_text.strip() if user_text and user_text.strip() else (
            "Опиши подробно, что на этой картинке. Если есть текст — переведи по-русски."
        )
        cache_key = None
        if self.config["cache_enabled"]:
            media_hash = hashlib.sha256(media_bytes).hexdigest()[:16]
            cache_key = self._cache_key(model, [
                {"role": "system", "content": user_prompt},
                {"role": "user", "content": f"[IMG:{media_hash}] {text_part}"},
            ])
            cached = self._cache_get(cache_key)
            if cached:
                self._stats["cache_hits"] += 1
                self._add_to_history(message.chat_id, "user", f"[картинка] {user_text or ''}")
                self._add_to_history(message.chat_id, "assistant", cached)
                return cached
        try:
            async with aiohttp.ClientSession() as session:
                if cfg.get("gemini"):
                    url = cfg["url"].format(model=model, key=key)
                    payload = {
                        "contents": [{"role": "user", "parts": [
                            {"text": text_part},
                            {"inline_data": {"mime_type": mime, "data": b64}},
                        ]}],
                        "systemInstruction": {"parts": [{"text": user_prompt}]},
                        "generationConfig": {
                            "temperature": float(self.config["temperature"]),
                            "maxOutputTokens": int(self.config["max_tokens"]),
                        },
                    }
                    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=90)) as r:
                        data = await r.json()
                        if r.status != 200:
                            self._stats["errors"] += 1
                            return self._friendly_api_error(r.status, str(data))
                        try:
                            usage = data.get("usageMetadata") or {}
                            self._stats["tokens_in"] += int(usage.get("promptTokenCount") or 0)
                            self._stats["tokens_out"] += int(usage.get("candidatesTokenCount") or 0)
                            self._stats["tokens_total"] += int(usage.get("totalTokenCount") or 0)
                        except Exception:
                            pass
                        reply = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                else:
                    data_url = f"data:{mime};base64,{b64}"
                    messages = [
                        {"role": "system", "content": user_prompt},
                        {"role": "user", "content": [
                            {"type": "text", "text": text_part},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ]},
                    ]
                    payload = {
                        "model": model, "messages": messages,
                        "max_tokens": int(self.config["max_tokens"]),
                        "temperature": float(self.config["temperature"]),
                    }
                    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                    async with session.post(cfg["url"], json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=90)) as r:
                        if r.status != 200:
                            self._stats["errors"] += 1
                            err = await r.text()
                            return self._friendly_api_error(r.status, err)
                        data = await r.json()
                        self._track_usage(data)
                        reply = data["choices"][0]["message"]["content"].strip()
            self._add_to_history(message.chat_id, "user", f"[картинка] {user_text or ''}")
            self._add_to_history(message.chat_id, "assistant", reply)
            result = html.escape(reply)
            if cache_key:
                self._cache_set(cache_key, result)
            return result
        except aiohttp.ClientError as e:
            self._stats["errors"] += 1
            return f"⚠️ Ошибка сети: <code>{html.escape(str(e))}</code>"
        except Exception as e:
            self._stats["errors"] += 1
            return f"⚠️ Ошибка: <code>{html.escape(str(e))}</code>"

    async def _ask_ai(self, messages, use_history_chat_id=None):
        if not self.config["api_key"]:
            return "❌ API-ключ не настроен."
        provider = self.config["provider"]
        cfg = self._PROVIDERS.get(provider)
        if not cfg:
            return f"❌ Неизвестный провайдер: {provider}"
        model = self.config["model"] or cfg["default_model"]
        key = self.config["api_key"]
        cache_key = None
        if self.config["cache_enabled"]:
            cache_key = self._cache_key(model, messages)
            cached = self._cache_get(cache_key)
            if cached:
                self._stats["cache_hits"] += 1
                if use_history_chat_id is not None:
                    self._add_to_history(use_history_chat_id, "assistant", cached)
                return cached
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
                            return self._friendly_api_error(r.status, str(data))
                        try:
                            usage = data.get("usageMetadata") or {}
                            self._stats["tokens_in"] += int(usage.get("promptTokenCount") or 0)
                            self._stats["tokens_out"] += int(usage.get("candidatesTokenCount") or 0)
                            self._stats["tokens_total"] += int(usage.get("totalTokenCount") or 0)
                        except Exception:
                            pass
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
                            return self._friendly_api_error(r.status, err)
                        data = await r.json()
                        self._track_usage(data)
                        reply = data["choices"][0]["message"]["content"].strip()
            result = html.escape(reply)
            if use_history_chat_id is not None:
                self._add_to_history(use_history_chat_id, "assistant", result)
            if cache_key:
                self._cache_set(cache_key, result)
            return result
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
        if any(w in t for w in ["спасибо", "круто", "супер", "отлично", "топ"]):
            return "🔥"
        if any(w in t for w in ["люблю", "❤", "😍", "обожаю"]):
            return "❤"
        if any(w in t for w in ["грустно", "😢", "😭", "печаль"]):
            return "😢"
        if any(w in t for w in ["думаю", "интересно", "хм"]):
            return "🤔"
        if any(w in t for w in ["ура", "победа", "получилось"]):
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
        text = "\n\n".join(parts)[-10000:]
        messages = [
            {"role": "system", "content": "Ты — составитель дневника."},
            {"role": "user", "content": "Сделай краткий дневник за сутки по этим чатам. 5-10 строк, по-русски.\n\n" + text},
        ]
        summary = await self._ask_ai(messages)
        summary = self._sanitize_ai_output(summary)
        try:
            await self._client.send_message("me", f"📔 <b>Дневник за {time.strftime('%d.%m.%Y')}</b>\n\n{summary}")
        except Exception:
            pass

    # ─── Обработчики ───
    async def _do_ask(self, message, text):
        if not self._whitelist_ok(message):
            await utils.answer(message, "🔒 AI в этом чате недоступен.")
            return
        reply = await message.get_reply_message()
        if reply and self.config["vision_enabled"] and (reply.photo or reply.sticker or reply.gif or reply.video):
            await utils.answer(message, "👀 <i>Смотрю картинку…</i>")
            answer = await self._ask_ai_vision(message, text, reply)
            await utils.answer(message, self._sanitize_ai_output(answer))
            return
        user_prompt = self._get_user_prompt_with_notes(message.sender_id)
        final_text = await self._build_user_message(message, text)
        self._add_to_history(message.chat_id, "user", final_text)
        messages = [{"role": "system", "content": user_prompt}] + self._get_history(message.chat_id)
        await utils.answer(message, "🤔 <i>Думаю…</i>")
        answer = await self._ask_ai(messages, use_history_chat_id=message.chat_id)
        await utils.answer(message, self._sanitize_ai_output(answer))
        asyncio.create_task(self._extract_and_save_facts(message.sender_id, text))

    async def _do_ocr(self, message, args):
        reply = await message.get_reply_message()
        if not reply:
            await utils.answer(message, "❌ Ответь на фото.")
            return
        base_prompt = (
            "Распознай ВЕСЬ текст на этой картинке. Сохрани структуру. "
            "Если текст на другом языке — сначала оригинал, потом перевод на русский. "
            "Только распознанный текст, без описаний."
        )
        prompt = f"{args}\n\n{base_prompt}" if args else base_prompt
        await utils.answer(message, "📝 <i>Распознаю текст…</i>")
        answer = await self._ask_ai_vision(message, prompt, reply)
        self._stats["ocr"] += 1
        await utils.answer(message, f"📄 <b>OCR</b>\n\n{self._sanitize_ai_output(answer)}")

    async def _do_remember(self, message, args):
        uid = message.sender_id
        text = args.strip()
        target_uid = uid
        if text:
            parts = text.split(maxsplit=1)
            if parts[0].startswith("@"):
                try:
                    entity = await message.client.get_entity(parts[0])
                    target_uid = entity.id
                    text = parts[1] if len(parts) > 1 else ""
                except Exception:
                    await utils.answer(message, f"❌ Не нашёл {html.escape(parts[0])}")
                    return
        if not text and message.is_reply:
            reply = await message.get_reply_message()
            if reply:
                target_uid = reply.sender_id
                text = args.strip()
        if not text:
            await utils.answer(message, "❌ Укажи факт.")
            return
        notes = self._get_user_notes(target_uid)
        notes.append(text[:300])
        self._save_user_notes(target_uid, notes)
        await utils.answer(message, f"✅ Запомнил.\n<i>{html.escape(text)}</i>\n<i>Всего: {len(notes)}</i>")

    async def _do_forget(self, message, args):
        args = args.strip()
        target_uid = message.sender_id
        idx = None
        if args:
            parts = args.split()
            if parts[0].startswith("@"):
                try:
                    entity = await message.client.get_entity(parts[0])
                    target_uid = entity.id
                except Exception:
                    await utils.answer(message, "❌ Не нашёл.")
                    return
                if len(parts) > 1 and parts[1].isdigit():
                    idx = int(parts[1])
            elif parts[0].isdigit():
                idx = int(parts[0])
        notes = self._get_user_notes(target_uid)
        if not notes:
            await utils.answer(message, "📭 Нет фактов.")
            return
        if idx is None:
            self._save_user_notes(target_uid, [])
            await utils.answer(message, f"🗑 Удалено: <b>{len(notes)}</b>.")
            return
        if idx < 1 or idx > len(notes):
            await utils.answer(message, f"❌ Номер 1..{len(notes)}.")
            return
        removed = notes.pop(idx - 1)
        self._save_user_notes(target_uid, notes)
        await utils.answer(message, f"🗑 Удалён #{idx}: <i>{html.escape(removed)}</i>")

    async def _do_notes(self, message, args):
        args = args.strip()
        target_uid = message.sender_id
        display = "себе"
        if args:
            try:
                entity = await message.client.get_entity(
                    int(args) if args.lstrip("-").isdigit() else args
                )
                target_uid = entity.id
                display = html.escape(getattr(entity, "first_name", None) or str(target_uid))
            except Exception:
                await utils.answer(message, "❌ Не нашёл.")
                return
        notes = self._get_user_notes(target_uid)
        if not notes:
            await utils.answer(message, f"📭 Нет фактов о {display}.")
            return
        lines = [f"📝 <b>Факты</b> о {display}:\n"]
        for i, n in enumerate(notes, 1):
            lines.append(f"  {i}. {html.escape(n)}")
        await utils.answer(message, "\n".join(lines))

    async def _do_summary(self, message, args):
        if not self._whitelist_ok(message):
            await utils.answer(message, "🔒 AI недоступен.")
            return
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
            await utils.answer(message, "❌ Мало сообщений.")
            return
        text = "\n".join(collected)[-12000:]
        messages = [
            {"role": "system", "content": "Ты — аналитик чатов."},
            {"role": "user", "content": f"{self.config['summary_prompt']}\n\nСообщения:\n\n{text}"},
        ]
        summary = await self._ask_ai(messages)
        self._stats["summaries"] += 1
        await utils.answer(message, f"📊 <b>Сводка</b> ({len(collected)} сообщ.)\n\n{self._sanitize_ai_output(summary)}")

    async def _do_context(self, message, args):
        if not self._whitelist_ok(message):
            await utils.answer(message, "🔒 AI недоступен.")
            return
        if not args or not args.strip():
            await utils.answer(
                message,
                "📖 <b>Контекст чата</b>\n\n"
                "Беру последние N сообщений и отвечаю на вопрос по ним.\n\n"
                "  • <code>.aicontext о чём говорили?</code>\n"
                "  • <code>.aicontext 300 кто спорил?</code>",
            )
            return
        parts = args.split(maxsplit=1)
        limit = int(self.config["context_size"])
        question = args
        if parts[0].isdigit():
            limit = max(20, min(int(parts[0]), 1000))
            question = parts[1].strip() if len(parts) > 1 else ""
            if not question:
                await utils.answer(message, "❌ Укажи вопрос после числа.")
                return
        await utils.answer(message, f"🔎 <i>Читаю {limit} сообщений…</i>")
        collected = await self._collect_messages(message, limit)
        if len(collected) < 5:
            await utils.answer(message, "❌ Мало сообщений.")
            return
        context_text = "\n".join(collected)[-14000:]
        messages = [
            {"role": "system", "content": self.config["context_prompt"]},
            {"role": "user", "content": f"Вопрос: {question}\n\n=== ВЫДЕРЖКА ===\n{context_text}\n=== КОНЕЦ ==="},
        ]
        answer = await self._ask_ai(messages)
        self._stats["contexts"] += 1
        await utils.answer(
            message,
            f"📖 <b>Контекст</b> ({len(collected)} сообщ.)\n\n"
            f"<b>Вопрос:</b> <i>{html.escape(question)}</i>\n\n"
            f"{self._sanitize_ai_output(answer)}",
        )

    async def _do_timeline(self, message, args):
        if not self._whitelist_ok(message):
            await utils.answer(message, "🔒 AI недоступен.")
            return
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
            lines.append(f"<code>{when}</code> <b>{html.escape(name)}</b>: {html.escape(msg.raw_text[:100])}")
            if len(lines) >= limit:
                break
        if not lines:
            await utils.answer(message, "❌ Нет сообщений.")
            return
        lines.reverse()
        await utils.answer(message, "🕐 <b>Хронология</b>\n\n" + "\n".join(lines))

    async def _do_toggle(self, message):
        if message.sender_id != self.CREATOR_ID:
            await utils.answer(message, "🔒 Только создатель может включать режим диалога.")
            return
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
            await utils.answer(message, "🔇 Режим диалога выключен. Бот молчит в этом чате.")
        else:
            self._history[chat_id] = []
            if chat_id not in self._chat_order:
                self._chat_order.append(chat_id)
            # сохраняем пустой список — так при перезагрузке режим восстановится
            try:
                self.db.set("AI", f"history_{chat_id}", [])
                self.db.set("AI", "chat_ids", self._chat_order)
            except Exception:
                pass
            await utils.answer(message, "🔊 Режим диалога включён. Бот отвечает в этом чате.")

    async def _do_reset(self, message):
        self._history[message.chat_id] = []
        await utils.answer(message, "🧹 История очищена.")

    async def _do_clear(self, message):
        self._history.clear()
        self._chat_order.clear()
        await utils.answer(message, "🧹 Вся история очищена.")

    async def _do_prompt(self, message, args):
        user_id = message.sender_id
        if not args:
            await utils.answer(message, f"🎭 <i>{html.escape(self._get_user_prompt(user_id))}</i>\n\nСменить: <code>.aiprompt текст</code>")
            return
        try:
            self.db.set("AI", f"user_prompt_{user_id}", args)
            await utils.answer(message, f"✅ Характер обновлён:\n<i>{html.escape(args)}</i>")
        except Exception as e:
            await utils.answer(message, f"⚠️ {html.escape(str(e))}")

    async def _do_preset(self, message, args):
        user_id = message.sender_id
        if not args:
            presets = "\n".join(f"  • <code>{k}</code>" for k in self.PRESETS)
            await utils.answer(message, f"🎭 <b>Пресеты:</b>\n{presets}")
            return
        if args not in self.PRESETS:
            await utils.answer(message, f"❌ Доступно: {', '.join(self.PRESETS.keys())}")
            return
        try:
            self.db.set("AI", f"user_prompt_{user_id}", self.PRESETS[args])
            await utils.answer(message, f"✅ Пресет <b>{args}</b> установлен.")
        except Exception as e:
            await utils.answer(message, f"⚠️ {html.escape(str(e))}")

    async def _do_char(self, message, args):
        user_id = message.sender_id
        if args.strip().lower() == "reset":
            try:
                self.db.set("AI", f"user_prompt_{user_id}", None)
            except Exception:
                pass
            await utils.answer(message, "✅ Сброшено.")
            return
        current = self._get_user_prompt(user_id)
        is_custom = False
        try:
            is_custom = self.db.get("AI", f"user_prompt_{user_id}", None) is not None
        except Exception:
            pass
        await utils.answer(
            message,
            f"🎭 <b>Твой характер</b> ({'личный' if is_custom else 'по умолчанию'}):\n<i>{html.escape(current)}</i>\n\n"
            "Сброс: <code>.aichar reset</code>",
        )

    async def _do_stats(self, message):
        total_req = self._stats["requests"] + self._stats.get("cache_hits", 0)
        hit_rate = (self._stats.get("cache_hits", 0) / total_req * 100) if total_req else 0
        c = self._compact_num
        await utils.answer(
            message,
            "📊 <b>Статистика AI</b>\n\n"
            f"  • Запросов: <b>{c(self._stats['requests'])}</b>\n"
            f"  • Cache hits: <b>{c(self._stats.get('cache_hits', 0))}</b> ({hit_rate:.1f}%)\n"
            f"  • Vision: <b>{c(self._stats.get('vision', 0))}</b>\n"
            f"  • OCR: <b>{c(self._stats.get('ocr', 0))}</b>\n"
            f"  • Context: <b>{c(self._stats.get('contexts', 0))}</b>\n"
            f"  • Сводок: <b>{c(self._stats.get('summaries', 0))}</b>\n"
            f"  • Ошибок: <b>{c(self._stats['errors'])}</b>\n\n"
            "💳 <b>Токены</b>\n"
            f"  • In: <b>{c(self._stats.get('tokens_in', 0))}</b>\n"
            f"  • Out: <b>{c(self._stats.get('tokens_out', 0))}</b>\n"
            f"  • Total: <b>{c(self._stats.get('tokens_total', 0))}</b>\n\n"
            "🚨 <b>Ошибки</b>\n"
            f"  • 401/403: <b>{c(self._stats.get('errors_401', 0))}</b>\n"
            f"  • 404: <b>{c(self._stats.get('errors_404', 0))}</b>\n"
            f"  • 429: <b>{c(self._stats.get('errors_429', 0))}</b>\n"
            f"  • 500+: <b>{c(self._stats.get('errors_500', 0))}</b>\n"
            f"  • Прочие: <b>{c(self._stats.get('errors_other', 0))}</b>",
        )

    async def _do_export(self, message):
        data = {"history": {str(k): v for k, v in self._history.items()}, "exported_at": time.time()}
        content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        file = io.BytesIO(content)
        file.name = f"ai_history_{int(time.time())}.json"
        await message.client.send_file(message.chat_id, file, caption="📦 Экспорт истории")

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
            await utils.answer(message, f"⚠️ {html.escape(str(e))}")

    async def _do_info(self, message):
        provider = self.config["provider"]
        cfg = self._PROVIDERS.get(provider, {})
        model = self.config["model"] or cfg.get("default_model", "—")
        vision_model = self._get_vision_model() or "—"
        history_size = sum(len(h) for h in self._history.values())
        await utils.answer(
            message,
            "🤖 <b>AI-модуль — информация</b>\n\n"
            f"  • <b>Создатель:</b> {self.CREATOR_USERNAME}\n"
            f"  • <b>Провайдер:</b> <code>{provider}</code>\n"
            f"  • <b>Модель:</b> <code>{model}</code>\n"
            f"  • <b>Vision:</b> <code>{vision_model}</code>\n"
            f"  • <b>Temperature:</b> {self.config['temperature']}\n"
            f"  • <b>Max tokens:</b> {self.config['max_tokens']}\n"
            f"  • <b>История:</b> {history_size} сообщ. в {len(self._history)} чатах\n"
            f"  • <b>Vision:</b> {'вкл' if self.config['vision_enabled'] else 'выкл'}\n"
            f"  • <b>Кэш:</b> {'вкл' if self.config['cache_enabled'] else 'выкл'} ({len(self._cache)})\n"
            f"  • <b>Санитайзер:</b> {'вкл' if self.config['sanitize_output'] else 'выкл'}\n"
            f"  • <b>Белый список:</b> {'вкл 🔒' if self.config['whitelist_enabled'] else 'выкл 🔓'} ({len(self._whitelist_chats)})\n"
            f"  • <b>Контекст:</b> {self.config['context_size']} сообщ.",
        )

    # ─── Whitelist ───
    async def _do_allow(self, message):
        if message.sender_id != self.CREATOR_ID:
            await utils.answer(message, "🔒 Только для создателя.")
            return
        self._whitelist_chats.add(message.chat_id)
        self._save_whitelist()
        await utils.answer(
            message,
            f"✅ Чат добавлен в белый список.\n"
            f"<b>ID:</b> <code>{message.chat_id}</code>\n"
            f"<b>Всего:</b> {len(self._whitelist_chats)}",
        )

    async def _do_disallow(self, message):
        if message.sender_id != self.CREATOR_ID:
            await utils.answer(message, "🔒 Только для создателя.")
            return
        self._whitelist_chats.discard(message.chat_id)
        self._save_whitelist()
        await utils.answer(
            message,
            f"🚫 Чат удалён из белого списка.\n<b>ID:</b> <code>{message.chat_id}</code>",
        )

    async def _do_allowlist(self, message):
        if message.sender_id != self.CREATOR_ID:
            await utils.answer(message, "🔒 Только для создателя.")
            return
        if not self._whitelist_chats:
            await utils.answer(message, "📋 Белый список пуст.")
            return
        lines = [f"📋 <b>Белый список</b> ({len(self._whitelist_chats)})\n"]
        for cid in self._whitelist_chats:
            try:
                chat = await self._client.get_entity(cid)
                title = getattr(chat, "title", None) or "Личный чат"
            except Exception:
                title = "?"
            lines.append(f"  • <code>{cid}</code> — {html.escape(title)}")
        await utils.answer(message, "\n".join(lines))

    async def _do_allow_all(self, message):
        if message.sender_id != self.CREATOR_ID:
            await utils.answer(message, "🔒 Только для создателя.")
            return
        count = len(self._whitelist_chats)
        self._whitelist_chats.clear()
        self._save_whitelist()
        await utils.answer(message, f"✅ Белый список очищен (<b>{count}</b>).")

    async def _do_whitelist_toggle(self, message):
        if message.sender_id != self.CREATOR_ID:
            await utils.answer(message, "🔒 Только для создателя.")
            return
        self.config["whitelist_enabled"] = not self.config["whitelist_enabled"]
        status = "вкл 🔒" if self.config["whitelist_enabled"] else "выкл 🔓"
        await utils.answer(
            message,
            f"<b>Белый список: {status}</b>\n<i>В списке:</i> <b>{len(self._whitelist_chats)}</b>",
        )

    def _help_public(self):
        return (
            "🤖 <b>AI-модуль</b>\n"
            f"<i>Создатель: {self.CREATOR_USERNAME}</i>\n\n"
            "💬 <b>Диалог</b>\n"
            "  • <code>.ai вопрос</code> — спросить AI (ответом на сообщение тоже работает)\n"
            "  • <code>.aitoggle</code> — вкл/выкл режим живого диалога\n"
            "  • <code>.aireset</code> — сбросить историю диалога в этом чате\n"
            "  • <code>.aiclear</code> — сбросить историю во ВСЕХ чатах\n\n"
            "🖼 <b>Картинки</b>\n"
            "  • ответом на фото + <code>.ai вопрос</code> — AI посмотрит и опишет\n"
            "  • <code>.aiocr</code> — распознать текст с фото/скриншота\n\n"
            "📊 <b>Анализ</b>\n"
            "  • <code>.aisummary [N] [@user]</code> — краткая сводка последних N сообщений\n"
            "  • <code>.aicontext [N] вопрос</code> — ответить на вопрос по истории чата\n"
            "  • <code>.aitimeline [N]</code> — хронология сообщений\n\n"
            "🧠 <b>Память о людях</b>\n"
            "  • <code>.airemember текст</code> — запомнить факт о себе\n"
            "  • <code>.airemember @user текст</code> — запомнить факт о другом\n"
            "  • <code>.aiforget [@user] [N]</code> — удалить факт (или все)\n"
            "  • <code>.ainotes [@user]</code> — посмотреть все факты\n\n"
            "🎭 <b>Характер</b>\n"
            "  • <code>.aiprompt текст</code> — задать свой личный характер\n"
            "  • <code>.aipreset coder</code> — готовый пресет\n"
            "  • <code>.aichar</code> — посмотреть текущий / <code>reset</code>\n\n"
            "⚙️ <b>Прочее</b>\n"
            "  • <code>.aistats</code> — статистика: запросы, токены, ошибки, кэш\n"
            "  • <code>.aiinfo</code> — настройки модуля\n"
            "  • <code>.aiexport</code> / <code>.aiimport</code> — история\n\n"
            "🔒 <b>Белый список)\n"
            "  • <code>.aiwhitelist</code> — вкл/выкл режим\n"
            "  • <code>.aiallow</code> — добавить текущий чат\n"
            "  • <code>.aidisallow</code> — убрать текущий чат\n"
            "  • <code>.aiallowlist</code> — показать список\n"
            "  • <code>.aiallowall</code> — очистить список"
        )

    # ─── Основные команды ───
    @loader.command()
    async def ai(self, message):
        """AI: спросить, сводка, контекст, характер, настройки."""
        args = (utils.get_args_raw(message) or "").strip()
        if not self._whitelist_ok(message):
            await utils.answer(message, "🔒 AI в этом чате недоступен.")
            return
        if not args:
            reply = await message.get_reply_message()
            if reply and self.config["vision_enabled"]:
                if reply.photo or reply.sticker or reply.gif or reply.video:
                    await self._do_ask(message, "")
                    return
            await utils.answer(message, self._help_public())
            return
        parts = args.split(maxsplit=1)
        sub = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""
        if sub == "help":
            await utils.answer(message, self._help_public()); return
        if sub == "info":
            await self._do_info(message); return
        if sub == "stats":
            await self._do_stats(message); return
        if sub in ("summary", "sum"):
            await self._do_summary(message, rest); return
        if sub in ("context", "ctx", "ask"):
            await self._do_context(message, rest); return
        if sub in ("timeline", "tl"):
            await self._do_timeline(message, rest); return
        if sub in ("toggle", "on", "off"):
            await self._do_toggle(message); return
        if sub == "reset":
            await self._do_reset(message); return
        if sub == "clear":
            await self._do_clear(message); return
        if sub in ("prompt", "p"):
            await self._do_prompt(message, rest); return
        if sub in ("preset", "pr"):
            await self._do_preset(message, rest); return
        if sub in ("char", "c"):
            await self._do_char(message, rest); return
        if sub == "export":
            await self._do_export(message); return
        if sub == "import":
            await self._do_import(message); return
        if sub == "ocr":
            await self._do_ocr(message, rest); return
        if sub in ("remember", "rem"):
            await self._do_remember(message, rest); return
        if sub in ("forget", "fgt"):
            await self._do_forget(message, rest); return
        if sub in ("notes", "note", "n"):
            await self._do_notes(message, rest); return
        # Whitelist через .ai
        if sub == "whitelist":
            await self._do_whitelist_toggle(message); return
        if sub == "allow":
            await self._do_allow(message); return
        if sub == "disallow":
            await self._do_disallow(message); return
        if sub == "allowlist":
            await self._do_allowlist(message); return
        if sub == "allow_all":
            await self._do_allow_all(message); return
        await self._do_ask(message, args)

    # ─── Alias-команды ───
    @loader.command()
    async def aistats(self, message):
        """Статистика AI: запросы, токены, ошибки"""
        await self._do_stats(message)

    @loader.command()
    async def aiinfo(self, message):
        """Информация о настройках AI-модуля"""
        await self._do_info(message)

    @loader.command()
    async def aisummary(self, message):
        """Сводка последних N сообщений. .aisummary [N] [@user]"""
        await self._do_summary(message, utils.get_args_raw(message) or "")

    @loader.command()
    async def aicontext(self, message):
        """Ответить на вопрос по истории чата. .aicontext [N] вопрос"""
        await self._do_context(message, utils.get_args_raw(message) or "")

    @loader.command()
    async def aitimeline(self, message):
        """Хронология сообщений. .aitimeline [N]"""
        await self._do_timeline(message, utils.get_args_raw(message) or "")

    @loader.command()
    async def aitoggle(self, message):
        """Включить/выключить режим диалога в этом чате"""
        await self._do_toggle(message)

    @loader.command()
    async def aireset(self, message):
        """Сбросить историю диалога в этом чате"""
        await self._do_reset(message)

    @loader.command()
    async def aiclear(self, message):
        """Сбросить историю диалога во ВСЕХ чатах"""
        await self._do_clear(message)

    @loader.command()
    async def aiprompt(self, message):
        """Задать личный характер AI. .aiprompt текст"""
        await self._do_prompt(message, utils.get_args_raw(message) or "")

    @loader.command()
    async def aipreset(self, message):
        """Установить пресет характера. .aipreset coder"""
        await self._do_preset(message, utils.get_args_raw(message) or "")

    @loader.command()
    async def aichar(self, message):
        """Показать твой текущий характер. .aichar reset — сбросить"""
        await self._do_char(message, utils.get_args_raw(message) or "")

    @loader.command()
    async def aiexport(self, message):
        """Экспорт истории диалогов в JSON-файл"""
        await self._do_export(message)

    @loader.command()
    async def aiimport(self, message):
        """Импорт истории из JSON (ответом на файл)"""
        await self._do_import(message)

    @loader.command()
    async def aiocr(self, message):
        """Распознать текст с фото. Ответом на картинку"""
        await self._do_ocr(message, utils.get_args_raw(message) or "")

    @loader.command()
    async def airemember(self, message):
        """Запомнить факт о пользователе. .airemember [@user] текст"""
        await self._do_remember(message, utils.get_args_raw(message) or "")

    @loader.command()
    async def aiforget(self, message):
        """Удалить факт из памяти. .aiforget [@user] [N]"""
        await self._do_forget(message, utils.get_args_raw(message) or "")

    @loader.command()
    async def aimemory(self, message):
        """Показать, что AI запомнил о тебе (или о другом). .aimemory [@user]"""
        args = (utils.get_args_raw(message) or "").strip()
        target_uid = message.sender_id
        display = "тебе"
        if args:
            try:
                entity = await message.client.get_entity(
                    int(args) if args.lstrip("-").isdigit() else args
                )
                target_uid = entity.id
                display = html.escape(getattr(entity, "first_name", None) or str(target_uid))
            except Exception:
                await utils.answer(message, "❌ Не нашёл.")
                return
        notes = self._get_user_notes(target_uid)
        if not notes:
            await utils.answer(message, f"📭 AI пока ничего не запомнил о {display}.")
            return
        lines = [f"🧠 <b>AI помнит</b> о {display} <i>({len(notes)})</i>:\n"]
        for i, n in enumerate(notes, 1):
            lines.append(f"  {i}. {html.escape(n)}")
        lines.append("\n<i>Удалить: .aiforget [@user] N</i>")
        await utils.answer(message, "\n".join(lines))

    @loader.command()
    async def aimemory_off(self, message):
        """[Создатель] Выключить авто-память"""
        if message.sender_id != self.CREATOR_ID:
            await utils.answer(message, "🔒 Только для создателя.")
            return
        self.config["auto_memory"] = False
        await utils.answer(message, "🧠 Авто-память <b>выключена</b>.")

    @loader.command()
    async def aimemory_on(self, message):
        """[Создатель] Включить авто-память"""
        if message.sender_id != self.CREATOR_ID:
            await utils.answer(message, "🔒 Только для создателя.")
            return
        self.config["auto_memory"] = True
        await utils.answer(message, "🧠 Авто-память <b>включена</b>.")

    @loader.command()
    async def aiwhitelist(self, message):
        """ Вкл/выкл белый список чатов"""
        await self._do_whitelist_toggle(message)

    @loader.command()
    async def aiallow(self, message):
        """ Добавить текущий чат в белый список"""
        await self._do_allow(message)

    @loader.command()
    async def aidisallow(self, message):
        """ Убрать текущий чат из белого списка"""
        await self._do_disallow(message)

    @loader.command()
    async def aiallowlist(self, message):
        """ Показать белый список чатов"""
        await self._do_allowlist(message)

    @loader.command()
    async def aiallowall(self, message):
        """ Очистить белый список"""
        await self._do_allow_all(message)

    @loader.watcher(only_messages=True)
    async def watcher(self, message):
        if not message.raw_text and not (
            message.photo or message.sticker or message.gif or message.video
        ):
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
        if not self._whitelist_ok(message):
            return
        uid_str = str(message.sender_id)
        self._user_msg_count[uid_str] = self._user_msg_count.get(uid_str, 0) + 1
        raw_text = message.raw_text or ""
        if self._tree_enabled and self.TREE_EMOJI in raw_text:
            if message.sender_id == self.CREATOR_ID:
                if message.id in self._tree_replied:
                    return
                self._tree_replied.add(message.id)
                await utils.answer(message, self.TREE_RESPONSE)
                return
        if self.config["auto_reactions"] and raw_text:
            reaction = self._pick_reaction(raw_text)
            if reaction:
                try:
                    await message.react(reaction)
                except Exception:
                    pass
        if raw_text.startswith((".", "/", "!")):
            return
        text_lower = raw_text.lower()
        my_username = (self._me.username or "").lower()
        trigger = (self.config["reply_to_trigger"] or "").lower().strip()
        mentioned = bool(my_username) and f"@{my_username}" in text_lower
        triggered = False
        if trigger:
            words = re.findall(r"\w+", text_lower)
            if trigger in words:
                triggered = True
        if mentioned or triggered:
            if self.config["vision_enabled"] and (
                message.photo or message.sticker or message.gif or message.video
            ):
                answer = await self._ask_ai_vision(message, raw_text, message)
            else:
                user_prompt = self._get_user_prompt_with_notes(message.sender_id)
                final_text = await self._build_user_message(message, raw_text)
                self._add_to_history(message.chat_id, "user", final_text)
                messages = [{"role": "system", "content": user_prompt}] + self._get_history(message.chat_id)
                answer = await self._ask_ai(messages, use_history_chat_id=message.chat_id)
            await utils.answer(message, self._sanitize_ai_output(answer))
            self._save_user_count()
            return
        if message.chat_id not in self._history:
            return
        if self.config["reply_only_when_mentioned"] and not (mentioned or triggered):
            return
        if not message.is_reply:
            return
        reply = await message.get_reply_message()
        if not reply or reply.sender_id != self._me.id:
            return
        if self.config["vision_enabled"] and (
            message.photo or message.sticker or message.gif or message.video
        ):
            answer = await self._ask_ai_vision(message, raw_text, message)
        else:
            user_prompt = self._get_user_prompt_with_notes(message.sender_id)
            self._add_to_history(message.chat_id, "user", raw_text)
            messages = [{"role": "system", "content": user_prompt}] + self._get_history(message.chat_id)
            answer = await self._ask_ai(messages, use_history_chat_id=message.chat_id)
        await utils.answer(message, self._sanitize_ai_output(answer))
