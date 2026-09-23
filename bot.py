import asyncio
import logging
import os
import uuid
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import BotCommand, LabeledPrice
from aiohttp import web

from config import BOT_TOKEN
import database as db

# === FFMPEG для Render (static-ffmpeg) ===
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


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
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
        f"/donate — поддержать проект ⭐\n"
        f"/help — помощь"
    )
    await message.answer(text)


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    text = (
        f"🤖 *Как пользоваться ботом:*\n\n"
        f"1. Напиши название трека или исполнителя\n"
        f"2. Дождись, пока бот найдёт и пришлёт аудио\n"
        f"3. Жми ❤️ чтобы добавить трек в избранное\n\n"
        f"*Команды:*\n"
        f"/start — запуск\n"
        f"/likes — избранное\n"
        f"/history — история\n"
        f"/donate — поддержать проект ⭐\n"
        f"/help — эта справка\n\n"
        f"_Бот создан PufenshuyVV_"
    )
    await message.answer(text, parse_mode="Markdown")


# ============ DONATE ============

DONATE_AMOUNTS = [10, 50, 100, 500, 1000, 5000, 10000]


@dp.message(Command("donate"))
async def cmd_donate(message: types.Message):
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


# ============ LIKES ============

@dp.message(Command("likes"))
async def cmd_likes(message: types.Message):
    likes = db.get_likes_with_id(message.from_user.id, limit=20)
    if not likes:
        await message.answer("У тебя пока нет лайков. Нажми ❤️ под треком.")
        return

    await message.answer(f"❤️ Твои лайки ({len(likes)}):")
    for like_id, query, title, file_id in likes:
        builder = InlineKeyboardBuilder()
        builder.button(
            text="❌ Убрать из избранного",
            callback_data=f"unlike:{like_id}"
        )
        try:
            await message.answer_audio(
                audio=file_id,
                title=title,
                performer="Music Bot",
                reply_markup=builder.as_markup()
            )
        except Exception as e:
            logging.warning(f"Не отправил лайк {file_id}: {e}")


@dp.message(Command("history"))
async def cmd_history(message: types.Message):
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
        builder.button(
            text="🔁 Найти снова",
            callback_data=f"repeat:{history_id}"
        )
        try:
            await message.answer_audio(
                audio=file_id,
                title=title,
                performer="Music Bot",
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
    query = message.text.strip()

    if not query:
        await message.answer("Напиши что искать 🤔")
        return

    db.add_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.first_name or ""
    )

    await do_search(message, query)


async def do_search(message: types.Message, query: str):
    status = await message.answer(f"🔍 Ищу: *{query}*...", parse_mode="Markdown")

    file_id = str(uuid.uuid4())
    output_template = os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s")

    cmd = [
        "yt-dlp",
        f"scsearch1:{query}",
        "-x",
        "--audio-format", "mp3",
        "--audio-quality", "192K",
        "-o", output_template,
        "--no-playlist",
        "--max-filesize", "25M",
        "--print", "after_move:filepath",
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

        mp3_path = os.path.join(DOWNLOAD_DIR, f"{file_id}.mp3")
        if not os.path.exists(mp3_path):
            files = [f for f in os.listdir(DOWNLOAD_DIR) if f.startswith(file_id)]
            if not files:
                await status.edit_text("❌ Файл не нашёлся после скачивания.")
                return
            mp3_path = os.path.join(DOWNLOAD_DIR, files[0])

        title = query[:60]

        audio = types.FSInputFile(mp3_path, filename=f"{title}.mp3")
        sent = await message.answer_audio(
            audio=audio,
            title=title,
            performer="Music Bot",
        )

        tg_file_id = sent.audio.file_id

        db.add_history(message.from_user.id, query, title, tg_file_id)
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
    _, history_id = call.data.split(":", 1)
    row = db.get_history_by_id(int(history_id))

    if not row:
        await call.answer("Трек не найден")
        return

    query, title, file_id = row
    added = db.add_like(call.from_user.id, query, title, file_id)

    if added:
        await call.answer("❤️ Добавлено в избранное!")
    else:
        await call.answer("Уже в избранном")

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
    _, like_id = call.data.split(":", 1)
    deleted = db.remove_like_by_id(int(like_id), call.from_user.id)

    if deleted:
        await call.answer("❌ Убрано из избранного")
        try:
            await call.message.delete()
        except Exception as e:
            logging.warning(f"Не удалил сообщение: {e}")
    else:
        await call.answer("Не нашёл в избранном")


@dp.callback_query(F.data.startswith("repeat:"))
async def cb_repeat(call: types.CallbackQuery):
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


# ============ WEB SERVER (для пингов, чтобы Render не спал) ============

async def start_web_server():
    async def handle(request):
        return web.Response(text="OK")

    app = web.Application()
    app.router.add_get("/", handle)
    app.router.add_get("/ping", handle)

    # Render даёт порт через переменную окружения PORT
    port = int(os.environ.get("PORT", 8080))

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Веб-сервер запущен на порту {port}")


# ============ MAIN ============

async def main():
    # Запускаем веб-сервер в фоне
    asyncio.create_task(start_web_server())

    commands = [
        BotCommand(command="start", description="🚀 Запустить бота"),
        BotCommand(command="likes", description="❤️ Мои лайки"),
        BotCommand(command="history", description="🕐 История"),
        BotCommand(command="donate", description="⭐ Поддержать проект"),
        BotCommand(command="help", description="❓ Помощь"),
    ]
    await bot.set_my_commands(commands)

    print("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())