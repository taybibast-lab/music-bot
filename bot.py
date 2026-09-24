import asyncio
import logging
import os
import uuid
import time
import random
import shutil
from collections import defaultdict
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import BotCommand, LabeledPrice
from aiohttp import web

from config import BOT_TOKEN
import database as db

# === FFMPEG ===
try:
    from static_ffmpeg import run as _ffmpeg_run
    _ffmpeg_path, _ffprobe_path = _ffmpeg_run.get_or_fetch_platform_executables_else_raise()
    os.environ["PATH"] = os.path.dirname(_ffmpeg_path) + os.pathsep + os.environ.get("PATH", "")
    print(f"[ffmpeg] path: {_ffmpeg_path}")
except Exception as _e:
    print(f"[ffmpeg] не удалось загрузить static-ffmpeg: {_e}")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

db.init_db()


# ============ НАСТРОЙКИ АДМИНА ============
ADMIN_ID = 8933557359
ADMIN_USERNAME = "puffvsv"


def is_admin(user) -> bool:
    if user.id == ADMIN_ID:
        return True
    if (user.username or "").lower() == ADMIN_USERNAME.lower():
        return True
    return False


# ============ АНТИСПАМ ============
SPAM_LIMIT = 15
SPAM_WINDOW = 3
BOT_INTERVAL_WINDOW = 10
BOT_INTERVAL_COUNT = 5
BOT_INTERVAL_TOLERANCE = 0.010
MAX_CAPTCHA_TRIES = 3
OLD_MESSAGE_AGE = 30
BOT_WARMUP_TIME = 30

banned_users = set()
captcha_state = {}
user_tracker = defaultdict(list)
bot_start_time = time.time()


# ============ ВОЛНА ============
WAVE_QUERIES = [
    "русский рэп андеграунд",
    "русский рок",
    "славянский фолк",
    "электроника техно",
    "инди музыка новая",
    "поп 2024",
    "хип-хоп новый",
    "метал русский",
    "джаз",
    "блюз",
    "классика",
    "регги",
    "панк русский",
    "пост-панк",
    "лоу-фай",
    "фонк",
    "drill",
    "трэп",
    "хаус",
    "drum and bass",
]


# ============ АНТИСПАМ: ЛОГИКА ============

def load_banned():
    global banned_users
    banned_users = set(db.load_all_banned())
    print(f"[ban] загружено {len(banned_users)} забаненных")


def is_banned_fast(user_id: int) -> bool:
    return user_id in banned_users


def is_spamming(user_id: int, msg_time: float) -> bool:
    now = msg_time
    user_tracker[user_id] = [
        t for t in user_tracker[user_id]
        if now - t < BOT_INTERVAL_WINDOW
    ]
    user_tracker[user_id].append(now)
    timestamps = user_tracker[user_id]

    recent = [t for t in timestamps if now - t < SPAM_WINDOW]
    if len(recent) > SPAM_LIMIT:
        return True

    if len(timestamps) >= BOT_INTERVAL_COUNT + 1:
        intervals = [
            timestamps[i + 1] - timestamps[i]
            for i in range(len(timestamps) - 1)
        ]
        last_n = intervals[-BOT_INTERVAL_COUNT:]
        if max(last_n) - min(last_n) < BOT_INTERVAL_TOLERANCE:
            return True

    return False


def is_old_message(msg_date) -> bool:
    try:
        msg_time = msg_date.timestamp()
        return (time.time() - msg_time) > OLD_MESSAGE_AGE
    except Exception:
        return False


def bot_is_warming_up() -> bool:
    return (time.time() - bot_start_time) < BOT_WARMUP_TIME


def reset_user_tracker(user_id: int):
    user_tracker[user_id] = []


def ban_user(user_id: int, reason: str = "spam"):
    db.add_banned(user_id, reason)
    banned_users.add(user_id)
    captcha_state.pop(user_id, None)
    logging.info(f"[ban] user_id={user_id} reason={reason}")


# ============ КАПЧА ============

async def send_captcha(message: types.Message):
    user_id = message.from_user.id
    a = random.randint(2, 9)
    b = random.randint(2, 9)
    answer = a + b

    tries = captcha_state.get(user_id, {}).get("tries", 0)
    captcha_state[user_id] = {"answer": answer, "tries": tries}

    await message.answer(
        f"🤖 *Антиспам-проверка*\n\n"
        f"Ты пишешь слишком быстро. Подтверди, что ты человек.\n\n"
        f"Сколько будет *{a} + {b}*?\n\n"
        f"Напиши ответ цифрой.\n"
        f"Осталось попыток: *{MAX_CAPTCHA_TRIES - tries}*",
        parse_mode="Markdown"
    )


async def handle_captcha_answer(message: types.Message) -> bool:
    user_id = message.from_user.id
    if user_id not in captcha_state:
        return False

    state = captcha_state[user_id]
    try:
        answer = int(message.text.strip())
    except ValueError:
        await message.answer("⚠️ Напиши ответ цифрой.")
        return True

    if answer == state["answer"]:
        captcha_state.pop(user_id, None)
        reset_user_tracker(user_id)
        await message.answer("✅ Проверка пройдена. Пиши дальше.")
        return True
    else:
        state["tries"] += 1
        if state["tries"] >= MAX_CAPTCHA_TRIES:
            ban_user(user_id, "captcha_failed")
            await message.answer("🚫 Ты не прошёл проверку. Доступ заблокирован.")
            captcha_state.pop(user_id, None)
        else:
            remaining = MAX_CAPTCHA_TRIES - state["tries"]
            await message.answer(
                f"❌ Неправильно. Осталось попыток: *{remaining}*",
                parse_mode="Markdown"
            )
        return True


# ============ START / HELP ============

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if is_banned_fast(message.from_user.id):
        return

    db.add_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.first_name or ""
    )
    text = (
        f"Привет, {message.from_user.first_name}! 👋\n\n"
        f"🎵 Я — музыкальный бот, созданный PufenshuyVV.\n\n"
        f"Просто напиши название трека или исполнителя — "
        f"я найду и пришлю тебе музыку прямо в Telegram.\n\n"
        f"📋 Команды:\n"
        f"/likes — твои лайки\n"
        f"/history — что слушал\n"
        f"/wave — 🌊 случайный трек\n"
        f"/album — 📀 поиск по альбому\n"
        f"/donate — поддержать проект ⭐\n"
        f"/help — помощь"
    )
    await message.answer(text)


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    if is_banned_fast(message.from_user.id):
        return

    text = (
        f"🤖 *Как пользоваться ботом:*\n\n"
        f"1. Напиши название трека или исполнителя\n"
        f"2. Дождись, пока бот найдёт и пришлёт аудио\n"
        f"3. Жми ❤️ чтобы добавить трек в избранное\n\n"
        f"*Команды:*\n"
        f"/start — запуск\n"
        f"/likes — избранное\n"
        f"/history — история\n"
        f"/wave — 🌊 случайный трек\n"
        f"/album [название] — 📀 весь альбом\n"
        f"/donate — поддержать проект ⭐\n"
        f"/help — эта справка\n\n"
        f"_Бот создан PufenshuyVV_"
    )
    await message.answer(text, parse_mode="Markdown")


# ============ ВОЛНА ============

@dp.message(Command("wave"))
async def cmd_wave(message: types.Message):
    if is_banned_fast(message.from_user.id):
        return

    query = random.choice(WAVE_QUERIES)
    await message.answer(f"🌊 *Волна*: {query}", parse_mode="Markdown")
    await do_search(message, query)


# ============ АЛЬБОМ ============

@dp.message(Command("album"))
async def cmd_album(message: types.Message):
    if is_banned_fast(message.from_user.id):
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "📀 *Поиск по альбому*\n\n"
            "Напиши: `/album название альбома`\n"
            "Например: `/album Группа крови`",
            parse_mode="Markdown"
        )
        return

    album_name = args[1].strip()
    await do_album_search(message, album_name)


async def do_album_search(message: types.Message, album_name: str):
    status = await message.answer("📀 *Ищу альбом...*", parse_mode="Markdown")

    tmp_dir = os.path.join(DOWNLOAD_DIR, str(uuid.uuid4()))
    os.makedirs(tmp_dir, exist_ok=True)

    try:
        # === ШАГ 1: получаем URL'ы треков (быстро) ===
        info_cmd = [
            "yt-dlp",
            f"scsearch:{album_name}",
            "--flat-playlist",
            "--playlist-end", "10",
            "--print", "%(url)s|||%(title)s",
            "--skip-download",
            "--no-warnings",
            "-q",
        ]

        proc = await asyncio.create_subprocess_exec(
            *info_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        tracks = []
        for line in stdout.decode(errors="ignore").strip().split("\n"):
            line = line.strip()
            if "|||" in line:
                url, title = line.split("|||", 1)
                url = url.strip()
                title = title.strip()
                if url.startswith("http"):
                    tracks.append((url, title))

        if not tracks:
            await status.edit_text(
                "❌ *Альбом не найден.*\n\nПопробуй точное название.",
                parse_mode="Markdown"
            )
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return

        await status.edit_text(
            f"📀 *Найдено {len(tracks)} треков. Качаю...*",
            parse_mode="Markdown"
        )

        # === ШАГ 2: параллельное скачивание (2 одновременно) ===
        sem = asyncio.Semaphore(2)
        sent_count = [0]
        print_fmt = "after_move:%(title)s\t%(uploader)s\t%(filepath)s"

        async def download_and_send(url, fallback_title):
            async with sem:
                track_id = str(uuid.uuid4())
                out_template = os.path.join(tmp_dir, f"{track_id}.%(ext)s")

                dl_cmd = [
                    "yt-dlp", url,
                    "-x",
                    "--audio-format", "mp3",
                    "--audio-quality", "192K",
                    "-o", out_template,
                    "--no-playlist",
                    "--max-filesize", "25M",
                    "--print", print_fmt,
                    "--no-warnings",
                    "-q",
                    "--no-check-certificates",
                    "--socket-timeout", "15",
                ]

                try:
                    p = await asyncio.create_subprocess_exec(
                        *dl_cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    out, _ = await p.communicate()

                    # Парсим метаданные
                    real_title = fallback_title[:80]
                    real_artist = "Music Bot"
                    mp3 = None

                    for line in out.decode(errors="ignore").split("\n"):
                        line = line.strip()
                        if line.count("\t") >= 2:
                            parts = line.split("\t")
                            real_title = parts[0].strip()[:80] or fallback_title[:80]
                            real_artist = parts[1].strip()[:60] or "Music Bot"
                            mp3 = parts[2].strip()
                            break

                    if not mp3 or not os.path.exists(mp3):
                        mp3 = os.path.join(tmp_dir, f"{track_id}.mp3")
                        if not os.path.exists(mp3):
                            files = [f for f in os.listdir(tmp_dir) if f.startswith(track_id)]
                            if not files:
                                return
                            mp3 = os.path.join(tmp_dir, files[0])

                    audio = types.FSInputFile(mp3, filename=f"{real_title}.mp3")
                    sent = await message.answer_audio(
                        audio=audio,
                        title=real_title,
                        performer=real_artist,
                    )
                    db.add_history(
                        message.from_user.id, album_name,
                        real_title, sent.audio.file_id
                    )
                    sent_count[0] += 1

                    try:
                        os.remove(mp3)
                    except Exception:
                        pass
                except Exception as e:
                    logging.warning(f"Album track error {fallback_title}: {e}")

        tasks = [download_and_send(url, title) for url, title in tracks]
        await asyncio.gather(*tasks, return_exceptions=True)

        try:
            await status.delete()
        except Exception:
            pass

        if sent_count[0] == 0:
            await message.answer("❌ Не удалось скачать ни одного трека.")

        shutil.rmtree(tmp_dir, ignore_errors=True)

    except Exception as e:
        logging.exception("Ошибка при поиске альбома")
        try:
            await status.edit_text(f"⚠️ Ошибка: {str(e)[:200]}")
        except Exception:
            pass
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ============ DONATE ============

DONATE_AMOUNTS = [10, 50, 100, 500, 1000, 5000, 10000]


@dp.message(Command("donate"))
async def cmd_donate(message: types.Message):
    if is_banned_fast(message.from_user.id):
        return

    builder = InlineKeyboardBuilder()
    for amount in DONATE_AMOUNTS:
        builder.button(text=f"⭐ {amount}", callback_data=f"donate:{amount}")
    builder.adjust(3)

    await message.answer(
        "⭐ *Поддержать проект*\n\n"
        "Выбери сумму в Telegram Stars.\n"
        "Все звёзды идут на развитие бота ❤️\n\n"
        "_Минимум 10 ⭐, максимум 10 000 ⭐_",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )


@dp.callback_query(F.data.startswith("donate:"))
async def cb_donate(call: types.CallbackQuery):
    if is_banned_fast(call.from_user.id):
        return

    amount = int(call.data.split(":", 1)[1])
    if amount < 10 or amount > 10000:
        await call.answer("Сумма должна быть от 10 до 10 000 ⭐")
        return

    await call.answer()

    try:
        await bot.send_invoice(
            chat_id=call.from_user.id,
            title="Поддержка MusicLab",
            description=f"Поддержать проект на {amount} ⭐",
            payload=f"donate_{amount}_{call.from_user.id}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="⭐", amount=amount)],
        )
    except Exception as e:
        logging.exception("Ошибка при отправке инвойса")
        await call.message.answer(f"⚠️ Ошибка оплаты: {str(e)[:150]}")


@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_q: types.PreCheckoutQuery):
    await pre_checkout_q.answer(ok=True)


@dp.message(F.successful_payment)
async def process_successful_payment(message: types.Message):
    amount = message.successful_payment.total_amount
    await message.answer(
        f"🙏 *Спасибо за поддержку!*\n\n"
        f"Ты отправил *{amount} ⭐*\n"
        f"Это очень помогает развитию бота ❤️\n\n"
        f"_Бот создан PufenshuyVV_",
        parse_mode="Markdown"
    )


# ============ LIKES / HISTORY ============

@dp.message(Command("likes"))
async def cmd_likes(message: types.Message):
    if is_banned_fast(message.from_user.id):
        return

    likes = db.get_likes_with_id(message.from_user.id, limit=20)
    if not likes:
        await message.answer("У тебя пока нет лайков. Нажми ❤️ под треком.")
        return

    await message.answer(f"❤️ Твои лайки ({len(likes)}):")
    for like_id, query, title, file_id in likes:
        builder = InlineKeyboardBuilder()
        builder.button(text="❌ Убрать из избранного", callback_data=f"unlike:{like_id}")
        try:
            await message.answer_audio(
                audio=file_id, title=title, performer="Music Bot",
                reply_markup=builder.as_markup()
            )
        except Exception as e:
            logging.warning(f"Не отправил лайк {file_id}: {e}")


@dp.message(Command("history"))
async def cmd_history(message: types.Message):
    if is_banned_fast(message.from_user.id):
        return

    history = db.get_history(message.from_user.id, limit=10)
    if not history:
        await message.answer("Ты ещё ничего не слушал.")
        return

    await message.answer(f"🕐 Последнее, что ты слушал ({len(history)}):")
    for query, title, file_id in history:
        hist_row = db.get_history_by_file_id(message.from_user.id, file_id)
        if not hist_row:
            continue
        history_id, _ = hist_row
        builder = InlineKeyboardBuilder()
        builder.button(text="🔁 Найти снова", callback_data=f"repeat:{history_id}")
        try:
            await message.answer_audio(
                audio=file_id, title=title, performer="Music Bot",
                reply_markup=builder.as_markup()
            )
        except Exception as e:
            logging.warning(f"Не отправил из истории {file_id}: {e}")


def build_track_keyboard(history_id: int, liked: bool = False):
    builder = InlineKeyboardBuilder()
    if liked:
        builder.button(text="✅ В избранном", callback_data=f"nolike:{history_id}")
    else:
        builder.button(text="❤️ В избранное", callback_data=f"like:{history_id}")
    builder.button(text="🔁 Похожие", callback_data=f"similar:{history_id}")
    return builder.as_markup()


# ============ SEARCH ============

@dp.message(F.text & ~F.text.startswith("/"))
async def search_music(message: types.Message):
    user_id = message.from_user.id

    if is_old_message(message.date):
        return
    if is_banned_fast(user_id):
        return
    if await handle_captcha_answer(message):
        return

    if not bot_is_warming_up():
        msg_time = message.date.timestamp()
        if is_spamming(user_id, msg_time):
            if is_admin(message.from_user):
                await message.answer(
                    "Господин, будь вы ботом — мы бы вас забанили 😏\n\n"
                    "Но вы — не бот. Хотите решить капчу для интереса?"
                )
                return
            await send_captcha(message)
            return

    query = message.text.strip()
    if not query:
        await message.answer("Напиши что искать 🤔")
        return

    db.add_user(
        user_id,
        message.from_user.username or "",
        message.from_user.first_name or ""
    )

    await do_search(message, query)


async def do_search(message: types.Message, query: str):
    # === КЭШ ===
    cached = db.get_cached_track(query)
    if cached:
        title, artist, file_id = cached
        try:
            sent = await message.answer_audio(
                audio=file_id,
                title=title,
                performer=artist or "Music Bot",
            )
            db.add_history(message.from_user.id, query, title, file_id)
            history_id = db.get_last_history_id(message.from_user.id)
            liked = db.is_liked(message.from_user.id, file_id)
            await sent.edit_reply_markup(
                reply_markup=build_track_keyboard(history_id, liked)
            )
            logging.info(f"[cache] hit: {query}")
            return
        except Exception as e:
            logging.warning(f"[cache] miss: {e}")

    status = await message.answer(f"🔍 Ищу: *{query}*...", parse_mode="Markdown")

    file_id = str(uuid.uuid4())
    output_template = os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s")

    print_fmt = "after_move:%(title)s\t%(uploader)s\t%(filepath)s"

    cmd = [
        "yt-dlp",
        f"scsearch1:{query}",
        "-x",
        "--audio-format", "mp3",
        "--audio-quality", "192K",
        "-o", output_template,
        "--no-playlist",
        "--max-filesize", "25M",
        "--print", print_fmt,
        "--no-warnings",
        "-q",
        "--no-check-certificates",
        "--socket-timeout", "15",
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            await status.edit_text("❌ Не нашёл трек.\n\nПопробуй другой запрос.")
            logging.error(f"yt-dlp error: {stderr.decode(errors='ignore')[-500:]}")
            return

        # === Парсим метаданные ===
        out = stdout.decode(errors="ignore")
        real_title = query[:60]
        real_artist = "Music Bot"
        mp3_path = None

        for line in out.split("\n"):
            line = line.strip()
            if line.count("\t") >= 2:
                parts = line.split("\t")
                real_title = parts[0].strip()[:80] or query[:60]
                real_artist = parts[1].strip()[:60] or "Music Bot"
                mp3_path = parts[2].strip()
                break

        if not mp3_path or not os.path.exists(mp3_path):
            fallback = os.path.join(DOWNLOAD_DIR, f"{file_id}.mp3")
            if os.path.exists(fallback):
                mp3_path = fallback
            else:
                files = [f for f in os.listdir(DOWNLOAD_DIR) if f.startswith(file_id)]
                if not files:
                    await status.edit_text("❌ Файл не нашёлся после скачивания.")
                    return
                mp3_path = os.path.join(DOWNLOAD_DIR, files[0])

        audio = types.FSInputFile(mp3_path, filename=f"{real_title}.mp3")
        sent = await message.answer_audio(
            audio=audio,
            title=real_title,
            performer=real_artist,
        )

        tg_file_id = sent.audio.file_id

        db.add_history(message.from_user.id, query, real_title, tg_file_id)
        db.cache_track(query, real_title, real_artist, tg_file_id)

        history_id = db.get_last_history_id(message.from_user.id)
        liked = db.is_liked(message.from_user.id, tg_file_id)

        await sent.edit_reply_markup(
            reply_markup=build_track_keyboard(history_id, liked)
        )

        await status.delete()

        try:
            os.remove(mp3_path)
        except Exception as e:
            logging.warning(f"Не удалил файл: {e}")

    except Exception as e:
        logging.exception("Ошибка при поиске")
        await status.edit_text(f"⚠️ Ошибка: {str(e)[:200]}")


# ============ CALLBACKS ============

@dp.callback_query(F.data.startswith("like:"))
async def cb_like(call: types.CallbackQuery):
    if is_banned_fast(call.from_user.id):
        return
    _, history_id = call.data.split(":", 1)
    row = db.get_history_by_id(int(history_id))
    if not row:
        await call.answer("Трек не найден")
        return
    query, title, file_id = row
    added = db.add_like(call.from_user.id, query, title, file_id)
    await call.answer("❤️ Добавлено!" if added else "Уже в избранном")
    try:
        await call.message.edit_reply_markup(
            reply_markup=build_track_keyboard(int(history_id), liked=True)
        )
    except Exception as e:
        logging.warning(f"Не обновил кнопку: {e}")


@dp.callback_query(F.data.startswith("nolike:"))
async def cb_nolike(call: types.CallbackQuery):
    await call.answer("Уже в избранном ✅")


@dp.callback_query(F.data.startswith("unlike:"))
async def cb_unlike(call: types.CallbackQuery):
    if is_banned_fast(call.from_user.id):
        return
    _, like_id = call.data.split(":", 1)
    deleted = db.remove_like_by_id(int(like_id), call.from_user.id)
    if deleted:
        await call.answer("❌ Убрано")
        try:
            await call.message.delete()
        except Exception:
            pass
    else:
        await call.answer("Не нашёл")


@dp.callback_query(F.data.startswith("repeat:"))
async def cb_repeat(call: types.CallbackQuery):
    if is_banned_fast(call.from_user.id):
        return
    _, history_id = call.data.split(":", 1)
    row = db.get_history_by_id(int(history_id))
    if not row:
        await call.answer("Трек не найден")
        return
    query, title, file_id = row
    await call.answer(f"🔍 Ищу: {query}")
    await do_search(call.message, query)


@dp.callback_query(F.data.startswith("similar:"))
async def cb_similar(call: types.CallbackQuery):
    await call.answer()
    await call.message.answer("🔍 Просто напиши новый запрос — найду похожее.")


# ============ WEB SERVER ============

async def start_web_server():
    async def handle(request):
        return web.Response(text="OK")
    app = web.Application()
    app.router.add_get("/", handle)
    app.router.add_get("/ping", handle)
    port = int(os.environ.get("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Веб-сервер запущен на порту {port}")


# ============ MAIN ============

async def main():
    load_banned()
    asyncio.create_task(start_web_server())

    commands = [
        BotCommand(command="start", description="🚀 Запустить бота"),
        BotCommand(command="likes", description="❤️ Мои лайки"),
        BotCommand(command="history", description="🕐 История"),
        BotCommand(command="wave", description="🌊 Случайный трек"),
        BotCommand(command="album", description="📀 Поиск по альбому"),
        BotCommand(command="donate", description="⭐ Поддержать проект"),
        BotCommand(command="help", description="❓ Помощь"),
    ]
    await bot.set_my_commands(commands)

    print("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())