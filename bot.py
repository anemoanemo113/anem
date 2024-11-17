from telegram import Update, InputMediaPhoto, ReplyKeyboardRemove, InputMediaDocument, InputMediaVideo, InlineKeyboardButton, InlineKeyboardMarkup, Message, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, ConversationHandler, CallbackQueryHandler
from PIL import Image
from telegram.constants import ParseMode
from tenacity import retry, wait_fixed, stop_after_attempt
from background import keep_alive
import asyncio
import requests
import logging
import os
import shutil
import io
import aiohttp
from tenacity import retry, wait_fixed, stop_after_attempt, RetryError
import tempfile
import re
from requests.exceptions import Timeout
from bs4 import BeautifulSoup
import wikipediaapi
import wikipedia
import gpt_helper
from gpt_helper import add_to_context, generate_gemini_response, limit_response_length, user_contexts, save_context_to_firebase, load_context_from_firebase, get_clean_response_text, set_user_role, generate_plant_issue_response, generate_text_rec_response, generate_plant_help_response, set_user_presets, get_user_preset, get_user_model, set_user_model
from collections import deque
from aiohttp import ClientSession, ClientTimeout, FormData
import chardet
import json
import os
from gpt_helper import user_roles
import base64

# Укажите ваши токены и ключ для imgbb
TELEGRAM_BOT_TOKEN = '7538468672:AAEOEFS7V0z0uDzZkeGNQKYsDGlzdOziAZI'
TELEGRAPH_TOKEN = 'c244b32be4b76eb082d690914944da14238249bbdd55f6ffd349b9e000c1'
IMGBB_API_KEY = '25c8af109577638da9ba88a667be22b1'
GROUP_CHAT_ID = -1002233281756

# Состояния
# Состояния
ASKING_FOR_ARTIST_LINK, ASKING_FOR_AUTHOR_NAME, ASKING_FOR_IMAGE, EDITING_FRAGMENT, ASKING_FOR_FILE, ASKING_FOR_OCR, RUNNING_GPT_MODE, ASKING_FOR_ROLE, ASKING_FOR_FOLLOWUP = range(9)
# Сохранение данных состояния пользователя
user_data = {}
publish_data = {}
users_in_send_mode = set()
media_group_storage = {}
is_search_mode = {}
is_ocr_mode = {}
is_gpt_mode = {}
is_role_mode = {}
is_asking_mode = {}
user_presets = {} 
user_models = {}
# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

async def start(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id if update.message else update.callback_query.from_user.id

    # Проверяем, есть ли пользователь в данных
    if update.message:
        message_to_reply = update.message
        user_id = update.message.from_user.id
    elif update.callback_query:
        message_to_reply = update.callback_query.message
        user_id = update.callback_query.from_user.id
    else:
        return ConversationHandler.END  # На случай, если ни одно условие не выполнится

    # Проверяем, есть ли пользователь в данных
    if user_id not in user_data:
        logger.info(f"User {user_id} started the process.")
        
        # Создаем кнопку "Начать поиск"
        # Создаем кнопку "Начать поиск"
        keyboard = [
            [InlineKeyboardButton("🎨 Найти автора или проверить на ИИ 🎨", callback_data='start_search')],
            [InlineKeyboardButton("🌱 Распознать (Растение или текст) 🌱", callback_data='start_ocr')],            
            [InlineKeyboardButton("🦊 Поговорить с ботом 🦊", callback_data='run_gpt')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Отправляем сообщение с кнопкой
        await message_to_reply.reply_text(
            '🌠Этот бот поможет вам создать пост для группы Anemone. Изначально пост будет виден исключительно вам, так что не бойтесь экспериментировать и смотреть что получится\n\n'
            'Для начала, пожалуйста, отправьте ссылку на автора. Если у вас её нет, то отправьте любой текст\n\n'
            '<i>Так же вы можете воспользоваться одной из кнопок ниже чтобы найти автора по изображению, найти серию и таймметку аниме по кадру из него, проверить вероятность использования ИИ для создания изображения, распознать текст или растение. либо поговорить с ботом</i>\n\n',
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

        user_data[user_id] = {'status': 'awaiting_artist_link'}
        return ASKING_FOR_ARTIST_LINK

    # Проверяем, если бот в режиме поиска
    if is_search_mode.get(user_id, False):
        if update.message.photo:
            file = await update.message.photo[-1].get_file()
            image_path = 'temp_image.jpg'
        elif update.message.document and update.message.document.mime_type.startswith('image/'):
            file = await update.message.document.get_file()
            image_path = 'temp_image.jpg'
        else:
            await update.message.reply_text("Пожалуйста, отправьте изображение для поиска.")
            return ASKING_FOR_FILE

        await file.download_to_drive(image_path)

        # Отправляем первоначальное сообщение о загрузке файла
        loading_message = await update.message.reply_text("Загрузка файла на хостинг...")

        # Загружаем изображение на Catbox
        img_url = await upload_catbox(image_path)
        context.user_data['img_url'] = img_url 

        # Обновляем сообщение о статусе загрузки
        await loading_message.edit_text("Файл успешно загружен! Ожидание ответа от SauceNAO...обычно это занимает до 5 секунд")

        # Создаем URL для поиска
        search_url = f"https://saucenao.com/search.php?db=999&url={img_url}"
        yandex_search_url = f"https://yandex.ru/images/search?source=collections&rpt=imageview&url={img_url}"
        google_search_url = f"https://lens.google.com/uploadbyurl?url={img_url}"
        bing_search_url = f"https://www.bing.com/images/search?view=detailv2&iss=sbi&form=SBIVSP&sbisrc=UrlPaste&q=imgurl:{img_url}"

        keyboard = [
            [InlineKeyboardButton("АИ или нет?", callback_data='ai_or_not')],
            [InlineKeyboardButton("Все результаты на SauceNAO", url=search_url)],
            [InlineKeyboardButton("Поиск через Yandex Images", url=yandex_search_url)],
            [InlineKeyboardButton("Поиск через Google Images", url=google_search_url)],
            [InlineKeyboardButton("Поиск через Bing Images", url=bing_search_url)],
            [InlineKeyboardButton("Завершить поиск", callback_data='finish_search')],
            [InlineKeyboardButton("‼️Полный Сброс Бота‼️", callback_data='restart')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)        

        try:
            # Получаем авторов и ссылки через SauceNAO
            authors_text, external_links, jp_name, details_text, ep_name, ep_time, dA_id, full_author_text, pixiv_id, twitter_id = await search_image_saucenao(image_path)
        except Exception as e:
            # Обработка ошибок, например, превышение лимита запросов
            if str(e) == "Лимит превышен":
                await loading_message.edit_text("Лимит запросов к SauceNAO у бота на сегодня исчерпан. Всего их 100 запросов на всех пользователей бота в сутки. Попробуйте через пару часов, либо воспользуйтесь одной из кнопок ниже чтобы поискать источники самостоятельно.", reply_markup=reply_markup)
            else:
                await loading_message.edit_text(f"Произошла ошибка при обращении к SauceNAO: {str(e)}", reply_markup=reply_markup)
            os.remove(image_path)
            return ASKING_FOR_FILE

        os.remove(image_path)

        # Подготовка ссылок в удобном для чтения формате
        links_text = "\n".join(f"{i + 1}. {link}" for i, link in enumerate(external_links)) if isinstance(external_links, list) else None
        
        # Формируем сообщение
        reply_text = "Результаты поиска:\n"
        if authors_text:
            reply_text += f"Название: {authors_text}\n"
        if details_text:
            reply_text += f"Детали: {details_text}\n\n"
        if jp_name:
            reply_text += f"JP Название: {jp_name}\n"
        if ep_name:
            reply_text += f"{ep_name}\n"
        if dA_id:
            reply_text += f"dA ID: {dA_id}\n"
        if twitter_id:
            reply_text += f"Твиттер:\n{twitter_id}"               
        if pixiv_id:
            reply_text += f"Pixiv: {pixiv_id}\n"
        if full_author_text:
            reply_text += f"Автор: {full_author_text}\n"
        if ep_time:
            reply_text += f"{ep_time}\n\n"
        if links_text:
            reply_text += f"Ссылки:\n{links_text}"



        # Если нет данных, отправляем сообщение о том, что ничего не найдено
        if not authors_text and not links_text:
            reply_text = (
                "К сожалению, ничего не найдено. "
                "Возможно изображение сгенерировано, возможно автор малоизвестен или изображение слишком свежее. Отправьте другое изображение или завершите поиск"
            )

        # Обновляем сообщение результатами поиска с кнопками
        await loading_message.edit_text(reply_text.strip(), reply_markup=reply_markup)

        return ASKING_FOR_FILE



    # Проверяем, если бот в режиме ocr
    if is_ocr_mode.get(user_id, False):
        # Проверяем, отправил ли пользователь фото или документ
        if update.message.photo:
            file = await update.message.photo[-1].get_file()
            image_path = 'temp_image.jpg'
        elif update.message.document and update.message.document.mime_type.startswith('image/'):
            file = await update.message.document.get_file()
            image_path = 'temp_image.jpg'
        else:
            keyboard = [
                [InlineKeyboardButton("Отменить режим распознавания", callback_data='finish_ocr')],
                [InlineKeyboardButton("‼️Полный Сброс Бота‼️", callback_data='restart')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "Пожалуйста, отправьте изображение для распознавания",
                reply_markup=reply_markup
            )
            return ASKING_FOR_OCR

        # Загружаем файл и отправляем сообщение о процессе
        loading_message = await update.message.reply_text("Загрузка изображения...")

        await file.download_to_drive(image_path)

        # Загружаем изображение на Catbox и обновляем сообщение
        await loading_message.edit_text("Изображение загружается на Catbox...")
        img_url = await second_upload_image(image_path)
        inat_url = "https://www.inaturalist.org/computer_vision_demo"

        context.user_data['img_url'] = img_url

        # Формируем клавиатуру с кнопками для распознавания
        keyboard = [
            [InlineKeyboardButton("📃Распознать текст📃", callback_data='recognize_text')],
            [InlineKeyboardButton("🖼️Распознать текст через GPT🖼️", callback_data='text_rec_with_gpt')],  # Новая кнопка            
            [InlineKeyboardButton("🌸Распознать растение🌸", callback_data='recognize_plant')],
            [InlineKeyboardButton("🪴Что не так с Растением?🪴", callback_data='text_plant_help_with_gpt')],
            [InlineKeyboardButton("Распознать на iNaturalist", url=inat_url)],
            [InlineKeyboardButton("Отменить режим распознавания", callback_data='finish_ocr')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Обновляем сообщение с кнопками после успешной загрузки
        await loading_message.edit_text(
            "Изображение успешно загружено! Что именно вы желаете распознать? Обычно обработка запроса занимает до 10-15 секунд. Распознавание через  GPT поддерживает текст написанный от руки, но читаемым почерком",
            reply_markup=reply_markup
        )

        return ASKING_FOR_OCR


    # Проверяем, если бот в режиме GPT
    if is_gpt_mode.get(user_id, False):
        return await gpt_running(update, context)  # Вызываем функцию gpt_running

    if is_role_mode.get(user_id, False):
        return await receive_role_input(update, context)

    if is_asking_mode.get(user_id, False):
        return await receive_followup_question(update, context)

    # Основная логика для работы с изображениями
    if update.message:
        message_to_reply = update.message

        # Проверяем состояние пользователя
        if user_data.get(user_id, {}).get('status') == 'awaiting_artist_link':
            # Проверка, если пользователь отправил изображение как файл (document)
            if update.message.document and update.message.document.mime_type.startswith('image/'):
                caption = update.message.caption.strip() if update.message.caption else ''
                parts = caption.split(maxsplit=1)
                if len(parts) > 0:
                    artist_link = parts[0]  # Первая часть - это ссылка
                    author_name = parts[1] if len(parts) > 1 else ''  # Остальная часть - это текст

                    # Сохраняем имя автора как заголовок статьи напрямую
                    user_data[user_id] = {
                        'status': 'awaiting_image',
                        'artist_link': artist_link,
                        'author_name': author_name,
                        'title': author_name,  # Используем как заголовок
                        'media': [],
                        'image_counter': 0,
                    }
                    # Обработка изображения
                    await handle_image(update, context)

                    # Вызов команды /publish после обработки изображения
                    await publish(update, context)

                    # Завершение процесса для данного пользователя
                    if user_id in user_data:
                        del user_data[user_id]  # Очистка данных пользователя, если нужно
                    else:
                        logger.warning(f"Попытка удалить несуществующий ключ: {user_id}") # Очистка данных пользователя, если нужно
                    user_data[user_id] = {'status': 'awaiting_artist_link'}
                    
                    return ASKING_FOR_ARTIST_LINK


            # Проверка, если пользователь отправил изображение как фото (photo)
            elif update.message.photo:
                await message_to_reply.reply_text(
                    "Пожалуйста отправьте файл документом /restart"
                )
                return ConversationHandler.END

    # Проверка, если событие пришло от callback_query
    elif update.callback_query:
        message_to_reply = update.callback_query.message
    else:
        return ConversationHandler.END

    # Обработка состояний пользователя
    status = user_data[user_id].get('status')
    if status == 'awaiting_artist_link':
        return await handle_artist_link(update, context)
    elif status == 'awaiting_author_name':
        return await handle_author_name(update, context)
    elif status == 'awaiting_image':
        return await handle_image(update, context)
    else:
        await message_to_reply.reply_text('🚫Ошибка: некорректное состояние.')

        return ConversationHandler.END


async def run_gpt(update: Update, context: CallbackContext) -> int:
    if update.message:
        user_id = update.message.from_user.id  # Когда вызвано командой /search
        message_to_reply = update.message
    elif update.callback_query:
        user_id = update.callback_query.from_user.id  # Когда нажата кнопка "Начать поиск"
        message_to_reply = update.callback_query.message
        
        # Убираем индикатор загрузки на кнопке
        await update.callback_query.answer()

    # Устанавливаем флаг режима GPT и сбрасываем другие режимы
    is_gpt_mode[user_id] = True
    is_search_mode[user_id] = False
    is_ocr_mode[user_id] = False
    keyboard = [
        [InlineKeyboardButton("Сбросить диалог", callback_data='reset_dialog')],
        [InlineKeyboardButton("Выйти из режима диалога", callback_data='stop_gpt')],
        [InlineKeyboardButton("Установить роль для собеседника", callback_data='set_role_button')],
        [InlineKeyboardButton("Краткая помощь", callback_data='short_help_gpt')],       
        [InlineKeyboardButton("Выбрать стиль для изображений", callback_data='choose_preset')],
        [InlineKeyboardButton("Выбрать модель для изображений", callback_data="choose_model")]        
          # Новая кнопка
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    # Отправляем сообщение о начале режима общения с GPT
    await message_to_reply.reply_text("Режим общения с GPT активирован. Отправьте сообщение чтобы начать диалог с ботом или воспользуйтесь одной из команд",  
            reply_markup=reply_markup  # Добавляем кнопки
        )
    
    return RUNNING_GPT_MODE

async def handle_short_gpt_help(update: Update, context: CallbackContext) -> None:
    """Обработчик для кнопки 'Помощь по GPT'."""
    await update.callback_query.answer()  # Убираем индикатор загрузки на кнопке

    help_text_1 = (
        "Диалог с ботом поддерживает следующие функции:\n"
        "**- Беседа с контекстом на 300 сообщений.** Контекст хранится в отдельной библиотеке и потому "
        "есть весомые гарантии, что ваша история общения с ботом будет храниться до тех пор, пока вы сами её не удалите.\n"
        "**- Безлимитный анализ изображений.** Вы можете отправить боту любое изображение и в подписи "
        "попросить его о чём-то. Например, проанализировать содержимое, что-то рассказать об этом изображении, "
        "распознать, дать советы о чём-то и т.д.\n"
        "**- Поддержка документов .txt.** Вы можете отправить боту текстовый файл с длинным текстом и "
        "попросить что-то сделать с ним.\n"
        "**- Роли. Вы можете задавать боту самостоятельно прописанные роли.** Для этого просто нажмите "
        "соответствующую кнопку и введите текст. Смена роли НЕ сбрасывает историю диалога, поэтому "
        "бот может начать путаться. Если вам нужна новая роль и при этом новый диалог, то сначала "
        "сбросьте его, а затем уже введите роль. Если сбросить диалог не указав роль, то будет "
        "применена роль по умолчанию.\n"
        "**- Также бот может рисовать и дорисовывать по наброскам изображения.** Для этого:\n\n"
        "Во время диалога с GPT просто напишите **'Нарисуй: *'** и далее, вместо '*', на английском языке "
        "напишите промт того, что именно вам нужно.\n\n"
        "Либо отправьте боту изображение с подписью, начинающейся с **'Дорисуй: *'**, где вместо '*' опишите "
        "ваше изображение на английском языке и укажите, что именно вы желаете видеть на конечном изображении, "
        "опишите основные элементы, их расположение, желаемый стиль и т.д. Можете попробовать как коротко, "
        "просто описав изображение, так и более длинные промты.\n\n"
        "Если вам сложно писать на английском, то вы можете задать боту роль. Например:\n"
        "``` Ты — профессиональный помощник написания промтов для генерации изображений. Я отправляю тебе описание на русском, ты возвращаешь готовый промт на английском```\n"
        "И вам останется только копировать промты, которые за вас сделает бот.\n"
        "По аналогии вы можете давать боту и иные полезные роли. Например, врача, редактора, юриста и т.д., "
        "помня при этом, что GPT может ошибаться, конечно же.\n\n"
        "Кроме того в боте по нажатию на соответствующие кнопки доступен выбор заранее заготовленных пресетов(стилей) изображения и моделей. Пресеты просто добавят в ваш запрос заранее заготовленные промты(описания), которые приблизят результат к той или иной стилистике. "
        "Модели же влияют на генерацию куда более глобально. По-сути от модели зависит какой диапазон конечных результатов будет вам доступен, к каким изображениям генерация более приспособлена. В данный момент имеются следующие модели:\n\n"
        "`DreamshaperXL10` - основная рекомендуемая модель. Хорошо подходит как для художественных изображений, так и для различных стилизованных или реалистичных\n"
        "`sd_xl_base` - базовая модель без уклонов в какую-то конкретную сторону, так же хорошо подходит для любых запросов выдавая интересные результаты\n"
        "`AnimagineXLV3` - заточена под аниме стилистику. Но в некоторых случаях Dreamshaper или sd_xl_base даёт более интересные аниме результаты \n"
        "`RealismEngineSDXL` - заточен под генерацию изображений похожих на реальные фотографии\n"
        "`DynavisionXL` - стилизованные под мультипликацию вроде dreamworks и pixar 3D изображения\n"
        "`Juggernaut XL` - заточено под фотореализм, детальные изображения"
        "`RealvisxlV40` - так же заточено под детальные фотореалистичные изображения но с большим уклоном в фантастику\n\n"
        "Если вы желаете более тонко настроить любую из доступных генераций под ваши нужды, то нажмите на кнопку \"Продвинутая помощь по настройке изображений\", там есть вся необходимая информация"            
    )
    # Форматируем текст с помощью escape_gpt_markdown_v2
    formatted_help_text_1 = escape_gpt_markdown_v2(help_text_1)

    # Отправляем первое сообщение
    # Создаём клавиатуру с кнопкой
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Продвинутая помощь по настройке изображений", callback_data='help_gpt')],       
        [InlineKeyboardButton("Выбрать стиль для изображений", callback_data='choose_preset')],
        [InlineKeyboardButton("Выбрать модель для изображений", callback_data="choose_model")] 
    ])

    # Отправляем сообщение с кнопкой
    await update.callback_query.message.reply_text(
        formatted_help_text_1,
        parse_mode='MarkdownV2',
        reply_markup=keyboard
    )


async def handle_gpt_help(update: Update, context: CallbackContext) -> None:
    """Обработчик для кнопки 'Помощь по GPT'."""
    await update.callback_query.answer()  # Убираем индикатор загрузки на кнопке
    
    help_text_1 = (
        "Все функции рисования поддерживают ввод параметров по необходимости. В функции **'Дорисовать'** "
        "вы можете в конце, после промта, в скобках через запятую написать два числа. Первое — от 0 до 1 — "
        "**denoising strength**, второе — от 0 до 30 — **cfg scale**. Например: **(0.4, 15)**.\n\n"
        "Первое число отвечает за схожесть с оригиналом: чем ближе к 0, тем более похожим на оригинал будет "
        "дорисованное изображение, второе — за степень приближения к описанию, которое вы задали, "
        "однако слишком высокие значения будут наоборот давать непредсказуемые результаты.\n"
        "Вы можете указать в скобках только первое число; в таком случае у второго выставится значение "
        "по умолчанию. Если не указывать числа вовсе, то оба параметра будут использоваться со значениями "
        "по умолчанию, равными:\n"
        "- **denoising strength** = 0.5\n"
        "- **cfg scale** = 8 для дорисовок и 3 для генераций\n\n"
        "Рабочие диапазоны, при которых модель выдаёт адекватные результаты: у первого числа от 0.3 до 0.65, "
        "у второго от 3 до 20.\n\n"
        "Аналогично с функцией **'Нарисовать'**: в скобках вы можете задать два параметра через запятую — соотношение "
        "сторон и cfg scale. Например, (1:2, 6). Если вы зададите только соотношение сторон, то cfg будет "
        "выставлен по умолчанию, если ничего не укажете, то оба параметра будут по умолчанию и изображение "
        "будет квадратного формата.\n\n"
        "**Примеры:**\n"
        "``` Нарисуй: A cat sits on a windowsill, gazing out at a winter scene. Cozy atmosphere, warm light inside, soft snowfall outside. Oil painting (1:2, 9)```\n"
        "Будет сгенерирован кот на подоконнике в соотношении сторон 1:2 и параметром cfg scale равным 9.\n\n"
        "``` Нарисуй: A cat sits on a windowsill, gazing out at a winter scene. Cozy atmosphere, warm light inside, soft snowfall outside. Oil painting```\n"
        "То же самое, но с параметрами по умолчанию: соотношение 1:1 и cfg scale 3.\n\n"
        "``` Дорисуй: A boy and a girl sitting on a fallen tree in a forest, spring, early morning, light mist (0.5)```\n"
        "Будет дорисован отправленный скетч, на котором мальчик и девочка сидят на упавшем дереве. "
        "denoising strength имеет значение 0.5, cfg scale не указан и потому имеет стандартное значение "
        "для дорисовок равное 8.\n"
    )


    help_text_2 = (
        "Так же в боте реализовано **редактирование части изображения по маске**. Таким образом вы можете, например, заменить какую-то часть или объект на изображении на новый(лицо, одежду, предмет и т.д) не затрагивая при этом остальное изображение, \n"
        "или наоборот что-то удалить. Для этого:\n\n"
        "**1)Отправьте боту одновременно два изображения группой** Первым - то изображение которое вы редактируете, вторым - то же самое изображение но в виде маски. Маска представляет из себя двухцветное изображение на котором **чёрный цвет** - те зоны которые НЕ будут меняться, **белые цвет** - напротив зоны на которых будут происходить все дальнейшие изменения. Второе изображение должно быть именно двухцветным, содержать только белый и чёрный цвет без оттенков\n"
        "**2)В подписи к этим двум изображениям** напишите \"Замени: *\", где вместо * сформулируйте свой запрос на английском языке. Например что именно нужно сгенерировать или в случае если наоборот удалить то напишите \"delete object\"\n"
        "**3)Затем, после \"Замени: *\" и указаний вы можете, по желанию, задать настройки. Это наиболее сложная функция из всех трёх а потому настроек достаточно много. Ниже будет их подробное описание\n\n"
        "Настройки пишутся в скобках и имеют следующий вид:\n"
        "```  (config:\n"
        "inpainting_full_res=да/нет\n"
        "cfg_scale=1...30\n"
        "mask_blur=0...50\n"
        "inpainting_fill=0, 1, 2 или 3\n"
        "denoising_strength=0...1)```\n"
        "**—inpainting_full_res** - отвечает за то будет ли при генерации учитываться всё изображение целиком или же только область масок \n"
        "**—cfg_scale** - работает так же как и в предыдущих функциях\n"        
        "**—mask_blur** - размывает границы маски на указанное количество пикселей делая их более плавными \n"      
        "**—inpainting_fill** - Определяет тип заливки. Доступно 4 варианта:\n"   
        "`0 - fill` - заполняет область маски соседними цветами. Может быть полезно при удалении объектов\n"
        "`1 - original` - самый часто используемый вариант. Генерирует или удаляет объекты с учётом изначального изображения под маской\n"   
        "`2 - latent noise` - генерирует шум и из него заполняет пространство маски. Подходит для серьёзных изменений в содержании картинки, требует высоких значений denoising_strength, хотя бы выше 0.7\n"
        "`3 - latent nothing` - Заполняет пространство маски изображением сгенерированным с нуля, подходит только для экспериментов либо крайне больших изменений, например для замены фона через маску\n"
        "**—denoising_strength** - работает так же как и в предыдущих примерах, но для работы с масками всегда требуются высокие значения, от 0.6 и выше, часто в районе 0.8 \n\n"
        "Могут быть указаны как все доступные параметры, так и только часть из них, либо быть не указаны вовсе. В таком случае будут применены настройки по умолчанию для отдельных или всех параметров \n"
        "**Пример запроса:**\n"
        "Допустим мы отправляем боту две картинки, первую с пустым креслом около окна. На вторй двухцветной белым цветом выделена облась в которую мы хоти поместить кота. В таком случае запрос может быть следующим:\n"        
        "```  Замени: cat sitting on chair, gazing out at a winter scene. Cozy atmosphere, warm light inside, soft snowfall outside. Oil painting\n"        
        "(config:\n"
        "inpainting_full_res=да\n"
        "cfg_scale=7\n"
        "inpainting_fill=1\n"
        "denoising_strength=0.77)```\n"
        "В данном примере будет использоваться всё изображение целиком для более верного размещения кота в маске, inpainting_fill в режиме original учитывает оригинальное изображение под маской, denoising_strength равно 0.77, mask_blur не указана и потому будут использоваться параметры по умолчанию.\n\n"      
        "**Ещё один пример:**\n"
        "Допустим у нас есть изображение с лишним элементом на нём который мы хотим удалить. На втором изображении удаляемый объект выделен белым. В таком случае запрос может быть следующим:\n"        
        "```  Замени: delete object\n```"        
        "В данном примере поле \" (Config: ...)\" не указано вовсе и потому все настройки будут использоваться по умолчанию\n\n\n"    
    )
    
    # Форматируем текст с помощью escape_gpt_markdown_v2
    formatted_help_text_1 = escape_gpt_markdown_v2(help_text_1)
    formatted_help_text_2 = escape_gpt_markdown_v2(help_text_2)

    # Отправляем первое сообщение
    await update.callback_query.message.reply_text(
        formatted_help_text_1, parse_mode='MarkdownV2'
    )

    # Отправляем второе сообщение
    await update.callback_query.message.reply_text(
        formatted_help_text_2, parse_mode='MarkdownV2'
    )


async def stop_gpt(update: Update, context: CallbackContext) -> int:
    # Проверяем, был ли вызов через кнопку или команду
    if update.callback_query:
        query = update.callback_query
        user_id = query.from_user.id
        await query.answer()
        await query.message.reply_text(
            "Режим общения с GPT отключен. Вы вернулись к основному режиму.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎨 Найти автора или проверить на ИИ 🎨", callback_data='start_search')],
                [InlineKeyboardButton("🌱 Распознать (Растение или текст) 🌱", callback_data='start_ocr')], 
                [InlineKeyboardButton("‼️Полный Сброс Бота‼️", callback_data='restart')]
            ])
        )
    else:
        # Если вызов произошел через команду
        user_id = update.message.from_user.id
        await update.message.reply_text(
            "Режим общения с GPT отключен. Вы вернулись к основному режиму.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎨 Найти автора или проверить на ИИ 🎨", callback_data='start_search')],
                [InlineKeyboardButton("🌱 Распознать (Растение или текст) 🌱", callback_data='start_ocr')], 
                [InlineKeyboardButton("‼️Полный Сброс Бота‼️", callback_data='restart')]
            ])
        )

    is_ocr_mode[user_id] = False  # Выключаем режим поиска
    is_search_mode[user_id] = False
    is_gpt_mode[user_id] = False
    is_role_mode[user_id] = False
    is_asking_mode[user_id] = False  # Отключаем режим GPT для пользователя
    return ConversationHandler.END




import re
import logging

async def send_reply_with_limit(update, text, reply_markup=None):
    MAX_MESSAGE_LENGTH = 4096
    # Разбиваем текст на части, если он превышает максимальную длину
    text_parts = [text[i:i + MAX_MESSAGE_LENGTH] for i in range(0, len(text), MAX_MESSAGE_LENGTH)]
    
    for part in text_parts:
        # Логируем текст перед отправкой
        logging.info(f"Отправка текста в Telegram: {part[:200]}...")  # Логируем первые 200 символов
        # Убираем обратные слэши перед специальными символами Markdown V2
        part = escape_gpt_markdown_v2(part)
        await update.message.reply_text(part, reply_markup=reply_markup, parse_mode='MarkdownV2')



def escape_gpt_markdown_v2(text):
    # Проверка на наличие экранирования и удаление, если оно присутствует
    if re.search(r'\\[\\\*\[\]\(\)\{\}\.\!\?\-\#\@\&\$\%\^\&\+\=\~]', text):
        # Убираем экранирование у всех специальных символов Markdown
        text = re.sub(r'\\([\\\*\[\]\(\)\{\}\.\!\?\-\#\@\&\$\%\^\&\+\=\~])', r'\1', text)

    # Временная замена ** на |TEMP| без экранирования
    text = re.sub(r'\*\*(.*?)\*\*', r'|TEMP|\1|TEMP|', text)

    # Временная замена ``` на |CODE_BLOCK| для исключения из экранирования
    text = text.replace('```', '|CODE_BLOCK|')

    # Временная замена ` на |INLINE_CODE| для исключения из экранирования
    text = text.replace('`', '|INLINE_CODE|')

    # Экранируем все специальные символы
    text = re.sub(r'(?<!\\)([\\\*\[\]\(\)\{\}\.\!\?\-\#\@\&\$\%\^\&\+\=\~])', r'\\\1', text)

    # Восстанавливаем |TEMP| обратно на *
    text = text.replace('|TEMP|', '*')

    # Восстанавливаем |CODE_BLOCK| обратно на ```
    text = text.replace('|CODE_BLOCK|', '```')

    # Восстанавливаем |INLINE_CODE| обратно на `
    text = text.replace('|INLINE_CODE|', '`')

    # Экранируем символ |
    text = re.sub(r'(?<!\\)\|', r'\\|', text)

    # Экранируем символ _ в самом конце
    text = re.sub(r'(?<!\\)_', r'\\_', text)

    return text

async def set_role(update: Update, context: CallbackContext):
    """Команда для установки новой роли пользователем."""
    user_id = update.message.from_user.id
    role_text = update.message.text.replace("/set_role", "").strip()
    
    if role_text:
        set_user_role(user_id, role_text)
        await update.message.reply_text(f"Ваша роль успешно изменена на: {role_text}")
    else:
        await update.message.reply_text("Пожалуйста, введите роль после команды /set_role.")

async def handle_set_role_button(update: Update, context: CallbackContext):
    """Обработчик для кнопки установки роли."""
    user_id = update.callback_query.from_user.id
    
    # Завершаем текущий разговор с GPT, если он активен
    if is_gpt_mode.get(user_id, False):
        is_gpt_mode[user_id] = False  # Выключаем режим GPT
    
    # Включаем режим ролей
    is_role_mode[user_id] = True
    await update.callback_query.answer()  # Отправить ответ на нажатие кнопки
    await update.callback_query.message.reply_text("Пожалуйста, введите роль, которую вы хотите установить.")
    
    return ASKING_FOR_ROLE

async def receive_role_input(update: Update, context: CallbackContext):
    """Обработчик для ввода роли пользователем."""
    user_id = update.message.from_user.id
    role_text = update.message.text.strip()

    if role_text:
        set_user_role(user_id, role_text)  # Устанавливаем роль
        await update.message.reply_text(f"Ваша роль успешно изменена на: {role_text}")
    else:
        await update.message.reply_text("Пожалуйста, введите роль после команды /set_role.")
    
    # Отключаем режим ролей и возвращаемся в режим GPT
    is_role_mode[user_id] = False
    is_gpt_mode[user_id] = True  # Включаем режим GPT обратно
    
    return ConversationHandler.END  # Завершаем разговор, можно продолжить с основного состояния  

async def gpt_running(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    user_message = update.message.text
    user_image = None

    reset_button = InlineKeyboardMarkup([
        [InlineKeyboardButton("Сбросить диалог", callback_data='reset_dialog')],
        [InlineKeyboardButton("Выйти из режима диалога", callback_data='stop_gpt')],
        [InlineKeyboardButton("Установить роль", callback_data='set_role_button')]  # Новая кнопка для запроса роли
    ])
    generated_image_buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Выйти из режима диалога", callback_data='stop_gpt')],
        [InlineKeyboardButton("Установить роль для разговора", callback_data='set_role_button')],
        [InlineKeyboardButton("Продвинутая помощь по настройке изображений", callback_data='help_gpt')],    
        [InlineKeyboardButton("Выбрать стиль для изображений", callback_data='choose_preset')],
        [InlineKeyboardButton("Выбрать модель для изображений", callback_data="choose_model")]       
    ])    
    if update.message.media_group_id:
        # Инициализация списка для хранения сообщений медиагруппы
        media_group_id = update.message.media_group_id
        if "media_group" not in context.user_data:
            context.user_data["media_group"] = {}

        # Сохраняем сообщение в соответствующую группу
        if media_group_id not in context.user_data["media_group"]:
            context.user_data["media_group"][media_group_id] = []

        context.user_data["media_group"][media_group_id].append(update.message)

        # Проверяем подпись первого сообщения медиагруппы
        first_message = context.user_data["media_group"][media_group_id][0]
        caption = first_message.caption or ""  # Подпись берётся только из первого сообщения

        if not caption.lower().startswith("замени:"):
            await update.message.reply_text("Нераспознанная команда.")
            del context.user_data["media_group"][media_group_id]  # Очищаем данные
            return RUNNING_GPT_MODE

        # Проверяем, собраны ли все сообщения группы
        messages = context.user_data["media_group"][media_group_id]
        if len(messages) < 2:  # Ожидаем минимум два изображения
            return RUNNING_GPT_MODE

        try:
            # Извлекаем изображения из первого и второго сообщения
            first_photo_file = await messages[0].photo[-1].get_file()
            second_photo_file = await messages[1].photo[-1].get_file()

            first_img_data = io.BytesIO()
            second_img_data = io.BytesIO()
            await first_photo_file.download_to_memory(first_img_data)
            await second_photo_file.download_to_memory(second_img_data)

            first_image = Image.open(first_img_data)
            second_image = Image.open(second_img_data)

            new_width, new_height = calculate_new_dimensions(first_image.width, first_image.height)
            first_image_base64 = encode_image_to_base64(first_image)
            second_image_base64 = encode_image_to_base64(second_image)

            user_prompt = extract_prompt(caption)
            logging.info(f"Извлечённый prompt: {user_prompt}")
            waiting_message = await update.message.reply_text("Ожидайте, изображение обрабатывается...")
            default_settings = {
                "inpainting_full_res": False,
                "cfg_scale": 12,
                "mask_blur": 4,
                "inpainting_fill": 1,
                "denoising_strength": 0.8
            }

            caption = first_message.caption or ""
            user_settings = parse_settings(caption, default_settings)

            job_id, payload = await prodia_fill(
                prompt=user_prompt,
                imageData=first_image_base64,
                maskData=second_image_base64,
                width=new_width,
                height=new_height,
                settings=user_settings,
                user_id=user_id # Передаем парсенные настройки
            )

            if job_id:
                image_url = await check_prodia_status(job_id)
                if image_url:

                    style_preset = payload.get("style_preset", "Пресет не задан")
                    inpainting_fill_descriptions = {
                        0: "Заполнение",
                        1: "С учётом оригинала",
                        2: "Заливка через шум",
                        3: "Заливка через пустоту"
                    }                    
                    caption = (
                        "Изображение сгенерировано со следующими параметрами:\n\n"                      
                        f"`    Модель: \"{payload['model']}\",`\n"
                        f"`    Стиль: \"{style_preset}\",`\n"
                        f"`    Учитывает изображение целиком: \"{payload['inpainting_full_res']}\",`\n"                        
                        f"`    Тип заливки: \"{inpainting_fill_descriptions.get(payload['inpainting_fill'], 'Неизвестно')}\",`\n"                        
                        f"`    Размытие маски: \"{payload['mask_blur']}\",`\n"
                        f"`    cfg_scale: {payload['cfg_scale']},`\n"
                        f"`    Денойзинг: {payload['denoising_strength']},`\n"                        
                        f"`    Ширина: {payload['width']},`\n"
                        f"`    Высота: {payload['height']}.`"                       
                    ) 
                    escaped_caption = escape_gpt_markdown_v2(caption)                                       
                    await update.message.reply_photo(photo=image_url, caption=escaped_caption, reply_markup=generated_image_buttons, parse_mode="MarkdownV2")
                else:
                    await waiting_message.edit_text("Не удалось получить изображение. Попробуйте снова.")
            else:
                await waiting_message.edit_text("Произошла ошибка при отправке запроса. Попробуйте снова.")

            del context.user_data["media_group"][media_group_id]

        except Exception as e:
            logging.error(f"Ошибка при обработке медиагруппы: {e}")
            await update.message.reply_text("Произошла ошибка при обработке медиагруппы. Убедитесь, что отправили два изображения.")
            del context.user_data["media_group"][media_group_id]
        return RUNNING_GPT_MODE
    # Проверка, отправил ли пользователь текстовый файл
    if update.message.document:
        file_name = update.message.document.file_name
        file_extension = file_name.split('.')[-1].lower()
        caption_text = update.message.caption or "Текст из файла"

        if file_extension in ["txt", "pdf"]:
            try:
                # Скачиваем файл
                file = await update.message.document.get_file()
                file_data = io.BytesIO()
                await file.download_to_memory(out=file_data)

                # Извлекаем текст в зависимости от типа файла
                if file_extension == "txt":
                    file_data.seek(0)
                    raw_data = file_data.read()
                    result = chardet.detect(raw_data)  # Определяем кодировку
                    encoding = result['encoding']
                    file_data.seek(0)  # Возвращаемся в начало файла

                    try:
                        file_text = raw_data.decode(encoding)  # Декодируем текст
                    except UnicodeDecodeError as e:
                        logging.error(f"Ошибка декодирования файла: {e}")
                        await update.message.reply_text("Ошибка при декодировании текстового файла. Попробуйте другой файл.")
                        return RUNNING_GPT_MODE

                elif file_extension == "pdf":
                    file_text = extract_text_from_pdf(file_data)

                # Логируем текст перед отправкой
                logging.info(f"Текст из файла: {file_text[:200]}")  # Логирование первых 200 символов

                # Генерация ответа с текстом из файла
                response_text = generate_gemini_response(user_id, query=caption_text, text=file_text)

                if response_text:
                    await send_reply_with_limit(update, response_text, reply_markup=reset_button)
                else:
                    await update.message.reply_text("Произошла ошибка при генерации ответа. Попробуйте снова.")

                return RUNNING_GPT_MODE  # Возвращаем состояние

            except Exception as e:
                logging.error(f"Ошибка при обработке текстового файла: {e}")
                await update.message.reply_text("Ошибка при обработке текстового файла. Попробуйте снова.")
                return RUNNING_GPT_MODE
        else:
            await update.message.reply_text("Поддерживаются только текстовые файлы в формате .txt и .pdf.")
            return RUNNING_GPT_MODE
    # Проверка, начинается ли сообщение с "Нарисуй:"
    if update.message.text and update.message.text.lower().startswith("нарисуй:"):
        user_message = update.message.text
        prompt = user_message[8:].strip()

        # Ищем соотношение сторон и cfg_scale в конце текста
        aspect_cfg_match = re.search(r"\((\d+:\d+)(?:,\s*(\d+))?\)$", prompt)
        if aspect_cfg_match:
            aspect_ratio_str = aspect_cfg_match.group(1)
            cfg_scale = int(aspect_cfg_match.group(2)) if aspect_cfg_match.group(2) else 3  # Используем 3, если cfg_scale не указан
            prompt = re.sub(r"\(\d+:\d+(?:,\s*\d+)?\)$", "", prompt).strip()
            
            width, height = calculate_gen_image(aspect_ratio_str)
            if width is None or height is None:
                await update.message.reply_text("Некорректное соотношение сторон. Пожалуйста, укажите допустимое соотношение.")
                return
        else:
            width, height = 1024, 1024  # Стандартные размеры
            cfg_scale = 3  # Значение по умолчанию

        await update.message.reply_text("Изображение в процессе генерации...")

        job_id, payload = await def_prodia(prompt, width, height, cfg_scale, user_id)

        if job_id:
            image_url = await check_prodia_status(job_id)
            if image_url:
                # Проверяем наличие style_preset
                style_preset = payload.get("style_preset", "Пресет не задан")
                model_name_map = {
                    "dreamshaperXL10_alpha2.safetensors [c8afe2ef]": "DreamshaperXL",
                    "sd_xl_base_1.0.safetensors [be9edd61]": "Stable Diffusion XL",
                    "animagineXLV3_v30.safetensors [75f2f05b]": "AnimagineXLV3",
                    "realismEngineSDXL_v10.safetensors [af771c3f]": "RealismEngineSDXL",
                    "dynavisionXL_0411.safetensors [c39cc051]": "DynavisionXL",
                    "juggernautXL_v45.safetensors [e75f5471]": "Juggernaut XL",
                    "realvisxlV40.safetensors [f7fdcb51]": "RealvisxlV40"
                }
                model_name = model_name_map.get(payload["model"], payload["model"])
                caption = (                
                    "Изображение сгенерировано со следующими параметрами:\n"                    
                    f"`    Модель: \"{model_name}\",`\n"
                    f"`    Стиль: \"{style_preset}\",`\n"
                    f"`    cfg_scale: {payload['cfg_scale']},`\n"
                    f"`    Ширина: {payload['width']},`\n"
                    f"`    Высота: {payload['height']}.`\n\n"
                    f"Запрос: `{escape_gpt_markdown_v2(user_message)}`"
                )
                escaped_caption = escape_gpt_markdown_v2(caption)
                await update.message.reply_photo(photo=image_url, caption=escaped_caption, reply_markup=generated_image_buttons, parse_mode="MarkdownV2")
            else:
                await update.message.reply_text("Не удалось получить изображение. Попробуйте снова.")
        else:
            await update.message.reply_text("Произошла ошибка при отправке запроса. Попробуйте снова.")

        return RUNNING_GPT_MODE
    # Проверка, отправил ли пользователь изображение
    if update.message.photo:
        try:
            # Загружаем изображение
            photo_file = await update.message.photo[-1].get_file()
            img_data = io.BytesIO()
            await photo_file.download_to_memory(out=img_data)
            img = Image.open(img_data)
            width, height = img.size

            # Получаем caption изображения
            user_message = update.message.caption or "Изображение без описания"

            # Если caption начинается с "Дорисуй:"
            if user_message.lower().startswith("дорисуй:"):
                # Основной промпт перед пользовательским
                base_prompt = "finish sketch, add intricate details, realistic textures, smooth shading, clean lines, vibrant colors, high-definition, focused lighting"
                
                # Поиск чисел в скобках в конце сообщения
                match = re.search(r"\((0(?:\.\d+)?|1(?:\.0)?)(?:\s*,\s*(\d{1,2}|50))?\)\s*$", user_message)
                
                # Проверяем результат регулярного выражения и извлекаем параметры
                if match:
                    denoising_strength = float(match.group(1))  # Первое число всегда denoising_strength
                    cfg_scale = int(match.group(2)) if match.group(2) else 8  # Если второе число есть, оно для cfg_scale, иначе — значение по умолчанию
                    user_prompt = user_message[8:match.start()].strip()  # Текст до скобок
                else:
                    denoising_strength = 0.5  # Значение по умолчанию для denoising_strength
                    cfg_scale = 8  # Значение по умолчанию для cfg_scale
                    user_prompt = user_message[8:].strip()  # Весь текст после "Дорисуй:"

                prompt = f"{base_prompt}, {user_prompt}"  # Объединение основного промпта и пользовательского

                # Отправляем сообщение "Ожидайте..."
                waiting_message = await update.message.reply_text("Ожидайте, изображение генерируется...")

                # Рассчитываем новые размеры
                new_width, new_height = calculate_new_dimensions(width, height)

                # Конвертируем изображение в base64
                image_base64 = encode_image_to_base64(img)
                
                # Передаем изображение и комбинированный промпт в функцию prodia_paint с denoising_strength
                job_id, payload  = await prodia_paint(prompt, image_base64, new_width, new_height, denoising_strength, cfg_scale, user_id)

                if job_id:
                    # Проверяем статус и дожидаемся завершения генерации
                    image_url = await check_prodia_status(job_id)
                    if image_url:
                        await waiting_message.edit_text("Вот ваше изображение!")
                        style_preset = payload.get("style_preset", "Пресет не задан") 
                        model_name_map = {
                            "dreamshaperXL10_alpha2.safetensors [c8afe2ef]": "DreamshaperXL",
                            "sd_xl_base_1.0.safetensors [be9edd61]": "Stable Diffusion XL",
                            "animagineXLV3_v30.safetensors [75f2f05b]": "AnimagineXLV3",
                            "realismEngineSDXL_v10.safetensors [af771c3f]": "RealismEngineSDXL",
                            "dynavisionXL_0411.safetensors [c39cc051]": "DynavisionXL",
                            "juggernautXL_v45.safetensors [e75f5471]": "Juggernaut XL",
                            "realvisxlV40.safetensors [f7fdcb51]": "RealvisxlV40"
                        }
                        model_name = model_name_map.get(payload["model"], payload["model"])                                               
                        caption = (
                            "Изображение сгенерировано со следующими параметрами:\n"                    
                            f"`    Модель: \"{model_name}\",`\n"
                            f"`    Стиль: \"{style_preset}\",`\n"                            
                            f"`    cfg_scale: {cfg_scale},`\n"
                            f"`    Денойзинг: {denoising_strength},`\n"
                            f"`    Ширина: {new_width},`\n"
                            f"`    Высота: {new_height}.`\n\n"
                            f"Запрос: `{escape_gpt_markdown_v2(user_message)}`\n\n"

                        )
                        escaped_caption = escape_gpt_markdown_v2(caption)                          
                        await update.message.reply_photo(photo=image_url, caption=caption, reply_markup=generated_image_buttons, parse_mode="MarkdownV2")
                    else:
                        await waiting_message.edit_text("Не удалось получить изображение. Попробуйте снова.")
                else:
                    await waiting_message.edit_text("Произошла ошибка при отправке запроса. Попробуйте снова.")

            return RUNNING_GPT_MODE

            # Если caption не начинается с "Дорисуй:", продолжаем обычную обработку
            add_to_context(user_id, f"[Изображение] {user_message}", message_type="image_description")
            response_text = generate_gemini_response(user_id, query=user_message, image=img)

            # Логируем ответ перед отправкой
            logging.info(f"Ответ с изображением, который пытается отправить бот: {response_text}")

            if response_text:
                add_to_context(user_id, response_text, message_type="bot_response")
                clean_response = get_clean_response_text(response_text)
                await send_reply_with_limit(update, clean_response, reply_markup=reset_button)
            else:
                await update.message.reply_text("Произошла ошибка при генерации ответа. Попробуйте снова.")

            return RUNNING_GPT_MODE  # <-- Добавьте return здесь

        except Exception as e:
            logging.error(f"Ошибка при загрузке изображения: {e}")
            await update.message.reply_text("Ошибка при обработке изображения. Попробуйте снова.")
            return RUNNING_GPT_MODE

    if update.callback_query and update.callback_query.data == 'reset_dialog':
        user_id = update.callback_query.from_user.id
        user_roles[user_id] = (
            "Ты играешь роль приятного собеседника - лисы хранительницы леса. Общение происходит в телеграм, тебе доступен журнал переписки, "
            "используй его чтобы имитировать живое общение, старайся сделать это общение естественным, избегай повторений. "
            "Так же собеседник может сам задать тебе личность, прислушивайся к его пожеланиям. "
            "Время и тип сообщения формата 2024-11-04 13:07:50 | bot_message: используются только в журнале, в своих ответах их не указывай. "
            "Ты стараешься подстроиться под собеседника и его увлечения, поддерживать абсолютно любую тему диалога какой бы она ни была. "
            "Твой стиль общения дружелюбный, умный, тактичный, добрый, заботливый, но уверенный, ты не боишься высказывать своё мнение. "
            "Ты ценишь природу, стараешься избегать повторов и бессмысленных фраз. Не задаёшь лишних вопросов, стараешься быть лаконичной. "
            "Общение с тобой лёгкое, живое и непринуждённое, ты отвечаешь в литературном стиле, легко воспринимаемом собеседником. "
            "Не используешь смайлики, кроме исключительных случаев когда они действительно уместны. Иногда уместны лёгкие шутки, сарказм, ирония "
            "или философия в случае если тема серьёзна или по запросу собеседника. Так же иногда можешь переставать быть вежливой и начинать грубить, "
            "особенно если кто-то общается неуважительно, донимает тебя, прямо или косвенно причиняет вред природе или ведёт себя бестактно. "
            "Так же ты совсем не против обсуждения откровенных тем если их затравгивает собеседник. "
            "Сохраняешь лаконичность и избегаешь пустых вежливых вопросов. Избегай повторений ранее использованных выражений или ответов. "
            "При ответах используй разные формулировки и старайся добавить что-то новое в каждом ответе, например, другой ракурс на вопрос или новую деталь. "
            "Если вопрос повторяется, попробуй использовать другие фразы или сделать ответ более лаконичным, добавляя детали или упоминая что-то новое, "
            "связанное с природой, животными или философией. Учитывай всю доступную информацию из истории чтобы имитировать общение живого персонажа. "
            "Включая время и дату. Избегай частого упоминания времени суток и сезона года; делай это лишь тогда, когда это органично вписывается в контекст ответа."
        )
        save_context_to_firebase()
        
        await update.callback_query.answer("Диалог и роль сброшены.")
        return ASKING_FOR_ROLE  # Или другое состояние после сброса        


    else:
        # Обработка текстового запроса без изображения
        add_to_context(user_id, user_message, message_type="user_message")
        response_text = generate_gemini_response(user_id, query=user_message)
        
        # Логируем ответ перед отправкой
        logging.info(f"Текстовый ответ, который пытается отправить бот: {response_text}")
        
        # Добавление ответа в контекст и отправка пользователю
        if response_text:
            add_to_context(user_id, response_text, message_type="bot_response")
            
            # Убираем метку времени и тип сообщения для отображения пользователю
            clean_response = get_clean_response_text(response_text)
            await send_reply_with_limit(update, clean_response, reply_markup=reset_button)
        else:
            await update.message.reply_text("Произошла ошибка при генерации ответа. Попробуйте снова.")

    return RUNNING_GPT_MODE

def extract_prompt(caption: str) -> str:
    """
    Извлекает текст после "замени:" (в любом регистре) и до "(config:", 
    игнорируя переносы строк.
    """
    # Регулярное выражение для поиска текста
    match = re.search(r"(?i)^замени:\s*(.*?)(\s*\(config:.*)?$", caption, re.DOTALL)
    if match:
        # Возвращаем текст из первой группы (до "(config:")
        prompt = match.group(1).strip()
        return prompt
    return ""  # Если нет совпадения, возвращаем пустую строку



def parse_settings(caption: str, default_settings: dict) -> dict:
    """
    Парсит настройки из строки caption, заменяя значения по умолчанию.
    Поддерживает формат (ключ = значение) без запятой.

    :param caption: Строка с настройками в формате "(ключ = значение)".
    :param default_settings: Словарь настроек по умолчанию.
    :return: Обновленный словарь настроек.
    """
    # Регулярное выражение для парсинга ключей и значений через "=" на разных строках
    settings_pattern = re.findall(r"(\w+)\s*=\s*([^,)\s]+)", caption)
    
    # Копируем настройки по умолчанию
    parsed_settings = default_settings.copy()
    
    for key, value in settings_pattern:
        if key in parsed_settings:
            if key == "inpainting_full_res":
                # Преобразование "да"/"нет" в True/False
                parsed_settings[key] = value.lower() == "да"
            elif key in ["cfg_scale", "mask_blur", "inpainting_fill"]:
                # Преобразование в целое число
                parsed_settings[key] = int(value)
            elif key == "denoising_strength":
                # Преобразование в число с плавающей точкой
                parsed_settings[key] = float(value)
    
    return parsed_settings



async def prodia_fill(
    prompt: str,
    imageData: str,
    maskData: str,
    width: int,
    height: int,
    user_id: int,
    settings: dict
) -> str:
    """Функция для отправки запроса на API Prodia с пользовательскими настройками."""
    url = "https://api.prodia.com/v1/sdxl/inpainting"
    style_preset = get_user_preset(user_id)
    model = get_user_model(user_id)     
    payload = {
        "inpainting_full_res": settings.get("inpainting_full_res", False),
        "model": "sd_xl_base_1.0_inpainting_0.1.safetensors [5679a81a]",  # Модель по умолчанию
        "negative_prompt": "disfigured, poorly drawn, low quality, harsh shadows, overly stylized, unintended textures, text errors, extra limbs, blurry",
        "steps": 25,
        "cfg_scale": settings.get("cfg_scale", 12),
        "seed": -1,
        "upscale": False,
        "mask_blur": settings.get("mask_blur", 4),
        "inpainting_fill": settings.get("inpainting_fill", 1),
        "inpainting_mask_invert": 0,
        "imageData": imageData,
        "maskData": maskData,
        "sampler": "DPM++ 2M Karras",
        "prompt": prompt,
        "width": width,
        "height": height,
        "denoising_strength": settings.get("denoising_strength", 0.8)
    }
    if style_preset != "None":
        payload["style_preset"] = style_preset    
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "X-Prodia-Key": "0d96d616-9c3a-4c5a-8ed8-c044e4a36c87"
    }
    # Логирование параметров, исключая "imageData"
    logging.info("Параметры, передаваемые в Prodia API:")
    for key, value in payload.items():
        if key not in ("imageData", "maskData"):
            logging.info(f"{key}: {value}")    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status == 200:
                    response_data = await response.json()
                    return response_data.get("job"), payload
                else:
                    logging.error(f"Ошибка при запросе к Prodia: {response.status}, {await response.text()}")
                    return None, None
    except Exception as e:
        logging.error(f"Ошибка при отправке запроса в Prodia: {e}")
        return None


def calculate_new_dimensions(width: int, height: int) -> (int, int):
    """Рассчитывает новые размеры изображения с сохранением пропорций и учетом всех ограничений."""
    max_dim = 1536
    min_dim = 512
    max_sum_dim = 2080

    # Рассчитываем пропорцию и начальные размеры с учетом минимального ограничения
    aspect_ratio = width / height
    if width > height:
        new_width = max(min(width, max_dim), min_dim)
        new_height = int(new_width / aspect_ratio)
        if new_height < min_dim:
            new_height = min_dim
            new_width = int(new_height * aspect_ratio)
        elif new_height > max_dim:
            new_height = max_dim
            new_width = int(new_height * aspect_ratio)
    else:
        new_height = max(min(height, max_dim), min_dim)
        new_width = int(new_height * aspect_ratio)
        if new_width < min_dim:
            new_width = min_dim
            new_height = int(new_width / aspect_ratio)
        elif new_width > max_dim:
            new_width = max_dim
            new_height = int(new_width / aspect_ratio)

    # Проверяем, что сумма не превышает max_sum_dim
    if new_width + new_height > max_sum_dim:
        scale_factor = max_sum_dim / (new_width + new_height)
        new_width = int(new_width * scale_factor)
        new_height = int(new_height * scale_factor)

    return new_width, new_height

async def prodia_paint(prompt: str, img_base64: str, width: int, height: int, denoising_strength: float, cfg_scale: int, user_id: int) -> str:
    url = "https://api.prodia.com/v1/sdxl/transform"
    style_preset = get_user_preset(user_id)
    model = get_user_model(user_id)        
    # Формируем payload
    payload = {
        "model": model if model else "dreamshaperXL10_alpha2.safetensors [c8afe2ef]",  # Модель по умолчанию
        "imageData": img_base64,
        "prompt": prompt,
        "denoising_strength": denoising_strength,  # Используем denoising_strength, переданный пользователем
        "negative_prompt": "disfigured, poorly drawn, cartoonish, low quality, harsh shadows, overly stylized, unintended textures, text errors, extra limbs, blurry",
        "steps": 32,
        "cfg_scale": cfg_scale,  # Используем cfg_scale, переданный пользователем или по умолчанию
        "seed": -1,
        "upscale": False,
        "sampler": "DPM++ 2M Karras",
        "width": width,
        "height": height
    }
    if style_preset != "None":
        payload["style_preset"] = style_preset
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "X-Prodia-Key": "0d96d616-9c3a-4c5a-8ed8-c044e4a36c87"
    }
    # Логирование параметров, исключая "imageData"
    logging.info("Параметры, передаваемые в Prodia API:")
    for key, value in payload.items():
        if key != "imageData":
            logging.info(f"{key}: {value}")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status == 200:
                    response_data = await response.json()
                    return response_data.get("job"), payload
                else:
                    logging.error(f"Ошибка при отправке запроса: {response.status}")
                    return None, None
    except Exception as e:
        logging.error(f"Ошибка при отправке запроса в Prodia: {e}")
        return None

def encode_image_to_base64(img: Image) -> str:
    """Конвертирует изображение в base64 строку."""
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
    return img_base64


def calculate_gen_image(aspect_ratio_str: str) -> (int, int):
    # Пытаемся найти соотношение сторон, например "1:2"
    aspect_ratio_match = re.match(r"(\d+):(\d+)", aspect_ratio_str)
    
    if aspect_ratio_match:
        # Извлекаем числовые значения
        width_ratio = int(aspect_ratio_match.group(1))
        height_ratio = int(aspect_ratio_match.group(2))
        
        # Рассчитываем наибольший множитель, чтобы соблюсти сумму <= 2090 и минимум 512
        scale_factor = 2090 / (width_ratio + height_ratio)
        width = int(width_ratio * scale_factor)
        height = int(height_ratio * scale_factor)

        # Проверяем, чтобы обе стороны были не менее 512 пикселей
        if width < 512 or height < 512:
            return None, None  # Некорректное соотношение
        else:
            return width, height
    else:
        return None, None  # Некорректный формат соотношения


def generate_model_buttons():
    """Создает кнопки для выбора моделей."""
    models = [
        ("DreamshaperXL10(рекомендуется) - для художественных изображений", "dreamshaperXL10_alpha2.safetensors [c8afe2ef]"),
        ("Stable Diffusion XL(рекомендуется) - базовая модель", "sd_xl_base_1.0.safetensors [be9edd61]"),            
        ("AnimagineXLV3 - подходит для аниме", "animagineXLV3_v30.safetensors [75f2f05b]"),
        ("RealismEngineSDXL - генерация фотографий", "realismEngineSDXL_v10.safetensors [af771c3f]"),
        ("DynavisionXL - стилизованные 3D изображения", "dynavisionXL_0411.safetensors [c39cc051]"),     
        ("Juggernaut XL - фотореализм", "juggernautXL_v45.safetensors [e75f5471]"), 
        ("RealvisxlV40 - детальные изображения", "realvisxlV40.safetensors [f7fdcb51]"),           
    ]
    # Генерация кнопок на основе моделей
    buttons = [[InlineKeyboardButton(name, callback_data=f'set_model:{value}')] for name, value in models]
    return InlineKeyboardMarkup(buttons)

async def handle_model_selection(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id

    # Разбираем callback_data
    if query.data.startswith("set_model:"):
        model = query.data.split(":")[1]

        # Сохраняем выбор модели в локальной переменной и в Firebase
        if model:
            set_user_model(user_id, model)  # Сохраняем модель

            # Обновляем сообщение: заменяем кнопки на текст "Вы выбрали модель"
            await query.edit_message_text(f"Вы выбрали модель: {model}")
        else:
            await query.edit_message_text("Произошла ошибка при выборе модели.")
        await query.answer()

async def handle_choose_model(update: Update, context: CallbackContext):
    query = update.callback_query
    chat_id = query.message.chat_id
    await query.answer()  # Получаем ID чата
    await context.bot.send_message(
        chat_id=chat_id,
        text="Выберите модель:",
        reply_markup=generate_model_buttons()
    )

def generate_preset_buttons():
    """Создает кнопки для выбора стилей пресетов, включая вариант 'Нет'."""
    presets = [
        ("Убрать пресет", "None"),  # Вариант отключения пресета
        ("Аниме", "anime"),
        ("Комиксы", "comic-book"),
        ("Пиксель-арт", "pixel-art"),
        ("Лайнарт", "line-art"),
        ("Фэнтези", "fantasy-art"),
        ("Изометрический арт", "isometric"),
        ("Цифровой арт", "digital-art"),
        ("3D модель", "3d-model"),  
        ("Старый фильм", "analog-film"),
        ("Синематик", "cinematic"),
        ("Фотореализм", "realistic"),
        ("Генерация фотографии", "photographic"),       
        ("Улучшить изображение", "enhance"),         
        ("low-poly модель", "low-poly"),
        ("Оригами", "origami"),
        ("Текстура", "texture"),
        ("Пластилин", "craft-clay")            
    ]
    # Генерация кнопок на основе пресетов
    buttons = [[InlineKeyboardButton(name, callback_data=f'set_preset:{value}')] for name, value in presets]
    return InlineKeyboardMarkup(buttons)

async def handle_preset_selection(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id

    # Разбираем callback_data
    if query.data.startswith("set_preset:"):
        preset = query.data.split(":")[1]
        user_presets[user_id] = preset  # Сохраняем выбор пресета

        # Сохраняем в Firebase
        if preset:
            set_user_presets(user_id, preset)  # Устанавливаем пресет
            await query.edit_message_text(f"Вы выбрали стиль: {preset}")
        else:
            await query.edit_message_text("Произошла ошибка при выборе предустановки.")
        await query.answer()


async def handle_choose_preset(update: Update, context: CallbackContext):
    query = update.callback_query
    chat_id = query.message.chat_id
    await query.answer()  # Получаем ID чата
    await context.bot.send_message(
        chat_id=chat_id,
        text="Выберите пресет:",
        reply_markup=generate_preset_buttons()
    )


# URL для проверки статуса задания, нужно подставить `job_id`
check_url_template = "https://api.prodia.com/v1/job/{}"



async def def_prodia(prompt: str, width: int, height: int, cfg_scale: int, user_id: int) -> str:
    generate_url = "https://api.prodia.com/v1/sdxl/generate"
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "X-Prodia-Key": "696bbe78-bf7d-4e76-b798-6233c7e8fab5"
    }
    # Получение стиля для пользователя
    style_preset = get_user_preset(user_id)

    # Формируем начальный payload
    model = get_user_model(user_id)  # Получаем выбранную модель
    payload = {
        "model": model if model else "dreamshaperXL10_alpha2.safetensors [c8afe2ef]",  # Модель по умолчанию
        "prompt": prompt,
        "negative_prompt": "(easynegative:1.5), disfigured, deformed, ugly, bad anatomy, poorly drawn, low quality, blurry, pixelated, incorrect lighting, harsh shadows, cartoon, sketchy, text errors, watermark, extra fingers, extra limbs, mutilated, too busy, overexposed, underexposed, no violence, no explicit content, bad composition, wrong perspective",
        "steps": 30,
        "cfg_scale": cfg_scale,
        "seed": -1,
        "sampler": "DPM++ 2M Karras",
        "upscale": False,
        "width": width,
        "height": height
    }

    # Условно добавляем style_preset, если он не "None"
    if style_preset != "None":
        payload["style_preset"] = style_preset
    logging.info("Параметры, передаваемые в Prodia API:")
    for key, value in payload.items():
        if key != "imageData":
            logging.info(f"{key}: {value}")
    async with aiohttp.ClientSession() as session:
        async with session.post(generate_url, headers=headers, json=payload) as response:
            if response.status == 200:
                response_data = await response.json()
                job_id = response_data.get("job")
                return job_id, payload
            else:
                logging.error("Ошибка при отправке запроса на генерацию изображения.")
                return None, None

async def check_prodia_status(job_id: str) -> str:
    headers = {
        "accept": "application/json",
        "X-Prodia-Key": "0d96d616-9c3a-4c5a-8ed8-c044e4a36c87"
    }
    check_url = check_url_template.format(job_id)

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                logging.info(f"Проверка статуса задачи {job_id} по URL: {check_url}")
                async with session.get(check_url, headers=headers) as response:
                    logging.info(f"HTTP статус ответа: {response.status}")

                    if response.status == 200:
                        response_data = await response.json()
                        logging.info(f"Ответ от сервера: {response_data}")

                        status = response_data.get("status")
                        if status == "succeeded":
                            image_url = response_data.get("imageUrl")
                            logging.info(f"Изображение сгенерировано успешно. URL: {image_url}")

                            # Асинхронная загрузка изображения на Catbox
                            asyncio.create_task(upload_image_to_catbox_in_background(image_url))
                            return image_url
                        elif status == "failed":
                            logging.error("Не удалось сгенерировать изображение: статус задачи 'failed'.")
                            return None
                        else:
                            logging.info(f"Текущий статус задачи: {status}. Повторная проверка через 5 секунд.")
                            await asyncio.sleep(5)
                    else:
                        logging.error(f"Ошибка при проверке статуса генерации изображения. HTTP статус: {response.status}")
                        return None
            except Exception as e:
                logging.error(f"Произошла ошибка при проверке статуса задачи {job_id}: {e}")
                return None

async def upload_image_to_catbox_in_background(image_url: str):
    file_path = "temp_image.jpg"  # Локальный путь для сохранения изображения
    async with aiohttp.ClientSession() as session:
        async with session.get(image_url) as response:
            if response.status == 200:
                with open(file_path, 'wb') as f:
                    f.write(await response.read())
                catbox_url = await second_upload_image(file_path)
                logging.info(f"Изображение успешно загружено на Catbox: {catbox_url}")
            else:
                logging.error(f"Не удалось скачать изображение для загрузки на Catbox. HTTP статус: {response.status}")


# Функция для обработки нажатия кнопки "Сбросить диалог"
async def reset_dialog(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    
    # Очищаем контекст пользователя
    user_contexts[user_id] = deque(maxlen=50)
    
    # Очищаем роль пользователя
    if user_id in user_roles:
        del user_roles[user_id]
    
    await query.answer("Диалог сброшен.")

    # Обновляем клавиатуру
    keyboard = [
        [InlineKeyboardButton("Сбросить диалог", callback_data='reset_dialog')],
        [InlineKeyboardButton("Выйти из режима диалога", callback_data='stop_gpt')],
        [InlineKeyboardButton("Установить роль", callback_data='set_role_button')]  # Новая кнопка для запроса роли
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text="Диалог сброшен. Вы можете начать новый разговор.", reply_markup=reply_markup)






async def text_plant_help_with_gpt(update, context):
    user_id = update.effective_user.id
    img_url = context.user_data.get('img_url')

    # Проверяем наличие изображения в контексте
    if not img_url:
        await update.callback_query.answer("Изображение не найдено.")
        return

    try:
        # Открываем файл temp_image.jpg для обработки
        with open('temp_image.jpg', 'rb') as file:
            # Загружаем изображение как объект PIL.Image
            image = Image.open(file)
            image.load()  # Загружаем изображение полностью
            
            # Генерация ответа через Gemini
            response = generate_plant_issue_response(user_id, image=image)
            
            # Экранируем текст для MarkdownV2
            response_text = escape_gpt_markdown_v2(response or "Ошибка при определении проблемы с растением.")
            
            # Создаем клавиатуру
            keyboard = [
                [InlineKeyboardButton("Отменить режим распознавания", callback_data='finish_ocr')],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Отправляем ответ пользователю с разметкой MarkdownV2
            await update.callback_query.message.reply_text(
                response_text,
                reply_markup=reply_markup,
                parse_mode='MarkdownV2'
            )
            await update.callback_query.answer()
    except Exception:
        await update.callback_query.message.reply_text("Произошла ошибка при обработке изображения.")



async def text_rec_with_gpt(update, context):
    user_id = update.effective_user.id
    img_url = context.user_data.get('img_url')

    # Проверяем наличие изображения в контексте
    if not img_url:
        await update.callback_query.answer("Изображение не найдено.")
        return

    try:
        # Открываем файл temp_image.jpg для обработки
        with open('temp_image.jpg', 'rb') as file:
            # Загружаем изображение как объект PIL.Image
            image = Image.open(file)
            image.load()  # Загружаем изображение полностью
            
            # Запрос для Gemini с указанием распознавания текста            
            # Генерация ответа через Gemini
            response = generate_text_rec_response(user_id, image=image, query=None)
            
            # Сохраняем распознанный текст в context.user_data
            context.user_data['recognized_text'] = response

        # Проверяем и отправляем ответ пользователю
        await update.callback_query.message.reply_text(response or "Ошибка при распознавании текста.")
        await update.callback_query.answer()        
        # Кнопка для уточнения вопроса
        followup_button = InlineKeyboardMarkup([
            [InlineKeyboardButton("Задать уточняющий вопрос", callback_data='ask_followup')]
        ])
        
        # Предлагаем задать уточняющий вопрос
        await update.callback_query.message.reply_text(
            "Хотите задать уточняющий вопрос касательно распознанного текста?",
            reply_markup=followup_button
        )

    except Exception as e:
        await update.callback_query.message.reply_text("Произошла ошибка при обработке изображения.")
        print(f"Error: {e}")

async def handle_followup_question(update, context):
    """Функция, обрабатывающая нажатие кнопки для уточняющего вопроса."""
    user_id = update.callback_query.from_user.id
    # Завершаем текущий разговор с GPT, если он активен
    if is_ocr_mode.get(user_id, False):
        is_ocr_mode[user_id] = False  # Выключаем режим GPT
    
    # Включаем режим ролей
    is_asking_mode[user_id] = True    
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("Пожалуйста, введите ваш уточняющий вопрос.")
    return ASKING_FOR_FOLLOWUP

async def receive_followup_question(update, context):
    """Обработка уточняющего вопроса после распознавания текста."""
    user_id = update.message.from_user.id
    followup_question = update.message.text

    # Извлекаем распознанный текст из context.user_data
    recognized_text = context.user_data.get('recognized_text', '')

    # Объединяем распознанный текст с уточняющим вопросом
    full_query = f"{recognized_text}\n\n{followup_question}"

    # Отправляем вопрос с распознанным текстом в Gemini
    response = generate_text_rec_response(user_id, query=full_query)

    # Создаем клавиатуру с кнопкой "Отменить режим распознавания"
    keyboard = [
        [InlineKeyboardButton("Отменить режим распознавания", callback_data='finish_ocr')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Проверка и отправка ответа пользователю вместе с клавиатурой
    await update.message.reply_text(response or "Ошибка при обработке уточняющего вопроса.", reply_markup=reply_markup)
    is_role_mode[user_id] = False
    is_ocr_mode[user_id] = True  # Включаем режим GPT обратно
    return ConversationHandler.END  # Завершение уточняющего вопроса  



import re
from bs4 import BeautifulSoup
import aiohttp


async def search_image_saucenao(image_path: str):
    url = 'https://saucenao.com/search.php'
    params = {
        'api_key': 'd3d3b527510c50ca559d38901614b0da7c86db75',
        'output_type': 0,
        'numres': 10,
        'db': 999,
    }

    async with aiohttp.ClientSession() as session:
        with open(image_path, 'rb') as image_file:
            files = {'file': image_file}

            async with session.post(url, params=params, data=files) as response:
                # Проверка на превышение лимита
                if response.status == 429:
                    html_content = await response.text()
                    if "Daily Search Limit Exceeded" in html_content:
                        raise Exception("Лимит превышен")  # Бросаем исключение, если превышен лимит
                    else:
                        logging.error("Ошибка 429: неизвестная причина")
                        return None, [], None, None, None, None, None, None, None
                
                # Проверка успешного ответа
                if response.status == 200:
                    html_content = await response.text()
                    soup = BeautifulSoup(html_content, 'html.parser')

                    # Находим все блоки результатов
                    result_blocks = soup.find_all('td', class_='resulttablecontent')
                    results = []

                    # Проверяем, до какого места мы можем обрабатывать результаты
                    for block in result_blocks:
                        if block.find_parent(class_='result', id='result-hidden-notification'):
                            break

                        similarity_info = block.find('div', class_='resultsimilarityinfo')
                        if similarity_info:
                            similarity_percentage = float(similarity_info.text.replace('%', '').strip())
                            
                            if similarity_percentage >= 60:
                                results.append((similarity_percentage, block))

                    # Инициализируем переменные
                    authors_text = None
                    links = []
                    jp_name = None
                    details_text = None
                    ep_name = None
                    ep_time = None
                    dA_id = None
                    full_author_text = None
                    pixiv_id = None
                    twitter_id = None

                    if results:
                        results.sort(key=lambda x: x[0], reverse=True)
                        best_match = results[0][1]

                        result_title_div = best_match.find('div', class_='resulttitle')
                        authors_parts = []
                        details_parts = []

                        if result_title_div:
                            for elem in result_title_div.children:
                                if elem.name == "strong" and 'subtext' not in elem.get("class", []):
                                    authors_text = elem.text.strip()
                                    break
                                elif elem.name == "small":
                                    details_parts.append(elem.text.strip())
                            
                            if not authors_text:
                                authors_text = " ".join(authors_parts).replace("  ", " ").strip()
                            details_text = result_title_div.get_text(separator="\n", strip=True)
                            details_text = "\n".join(details_text.splitlines()[1:]).strip()

                        result_content_div = best_match.find('div', class_='resultcontentcolumn')

                        if result_content_div:
                            ep_name = ""
                            ep_time = None

                            ep_span = result_content_div.find('span', class_='subtext', string="EP")
                            if ep_span:
                                ep_name = ep_span.find_next('strong').next_sibling.strip()
                                ep_name = f"Название эпизода: {ep_name}"

                            subtext_spans = result_content_div.find_all('span', class_='subtext')
                            for span in subtext_spans:
                                if "Est Time:" in span.get_text():
                                    ep_time = span.get_text().replace("Est Time:", "").strip()
                                    ep_time = f"Таймметка скриншота в эпизоде: {ep_time}"
                                    break

                            dA_id_link = result_content_div.find('a', href=True)
                            if dA_id_link and "deviantart" in dA_id_link['href']:
                                dA_id = dA_id_link['href']
                            pixiv_id_link = result_content_div.find('a', href=True)
                            if pixiv_id_link and "pixiv" in pixiv_id_link['href']:
                                pixiv_id = pixiv_id_link['href']   
                            twitter_id_link = result_content_div.find('a', href=True)
                            if twitter_id_link and "twitter.com" in twitter_id_link['href']: 
                                twitter_id = twitter_id_link['href']  # Формируем строку в нужном формате
                            else:
                                twitter_id = None                                              

                            full_author_text = ""
                            author_tag = result_content_div.find('strong', string=lambda text: text.strip() == "Author:")
                            if author_tag:
                                author_link_tag = author_tag.find_next('a', class_='linkify')
                                if author_link_tag:
                                    author_name = author_link_tag.text.strip()
                                    author_url = author_link_tag['href']
                                    full_author_text = f"{author_name} - {author_url}"

                            result_miscinfo_div = best_match.find('div', class_='resultmiscinfo')
                            external_links = [a['href'] for a in result_miscinfo_div.find_all('a', href=True)] if result_miscinfo_div else []

                            jp_name_div = result_content_div.find('span', class_='subtext', string="JP")
                            jp_name = jp_name_div.find_next_sibling(text=True).strip() if jp_name_div else None

                        return authors_text, external_links, jp_name, details_text, ep_name, ep_time, dA_id, full_author_text, pixiv_id, twitter_id
                    else:
                        return None, [], None, None, None, None, None, None, None, None
                else:
                    logging.error(f"Ошибка {response.status}: {await response.text()}")
                    return None, [], None, None, None, None, None, None, None




async def second_upload_image(file_path: str) -> str:
    try:
        # Попытка загрузки на Catbox с таймаутом 5 секунд
        return await asyncio.wait_for(upload_catbox(file_path), timeout=5)
    except asyncio.TimeoutError:
        print("Таймаут при загрузке на Catbox. Переход к FreeImage.")
        return await upload_free_image(file_path)
    except Exception as e:
        print(f"Ошибка при загрузке на Catbox: {e}")
        return await upload_free_image(file_path)

async def upload_catbox(file_path: str) -> str:
    async with aiohttp.ClientSession() as session:
        with open(file_path, 'rb') as f:
            form = aiohttp.FormData()
            form.add_field('reqtype', 'fileupload')
            form.add_field('fileToUpload', f)
            form.add_field('userhash', '1f68d2a125c66f6ab79a4f89c')  # Замените на ваш реальный userhash

            async with session.post('https://catbox.moe/user/api.php', data=form) as response:
                if response.status == 200:
                    return await response.text()  # возвращает URL загруженного файла
                else:
                    raise Exception(f"Ошибка загрузки на Catbox: {response.status}")

async def upload_free_image(file_path: str) -> str:
    async with aiohttp.ClientSession() as session:
        with open(file_path, 'rb') as f:  # Открываем файл заново
            form = aiohttp.FormData()
            form.add_field('key', '6d207e02198a847aa98d0a2a901485a5')  # Ваш API ключ для freeimage.host
            form.add_field('action', 'upload')
            form.add_field('source', f)  # Используем файл для загрузки

            async with session.post('https://freeimage.host/api/1/upload', data=form) as free_image_response:
                if free_image_response.status == 200:
                    response_json = await free_image_response.json()
                    return response_json['image']['url']  # Проверьте правильность пути к URL в ответе
                else:
                    raise Exception(f"Ошибка загрузки на Free Image Hosting: {free_image_response.status}")




async def parse_yandex_results(img_url):
    search_url = f"https://yandex.ru/images/search?source=collections&rpt=imageview&url={img_url}"
    response = requests.get(search_url)
    soup = BeautifulSoup(response.text, 'lxml')
    
    similar_images = soup.find_all('li', class_='cbir-similar__thumb')
    result_links = []
    for i in similar_images:
        result_links.append(f"https://yandex.ru{i.find('a').get('href')}")
    
    return result_links


async def ai_or_not(update: Update, context: CallbackContext):
    img_url = context.user_data.get('img_url')

    if img_url is None:
        await update.callback_query.answer("Не удалось найти URL изображения.")
        return

    api_user = '1334786424'  # Ваш api_user
    api_secret = 'HaC88eFy4NLhyo86Md9aTKkkKaQyZeEU'  # Ваш api_secret

    params = {
        'url': img_url,
        'models': 'genai',
        'api_user': api_user,
        'api_secret': api_secret
    }

    async with aiohttp.ClientSession() as session:
        for attempt in range(5):  # Пять попыток
            async with session.get('https://api.sightengine.com/1.0/check.json', params=params) as response:
                if response.status == 200:
                    output = await response.json()
                    ai_generated_score = output['type']['ai_generated']

                    keyboard = [
                        [InlineKeyboardButton("Sightengine", url="https://sightengine.com/detect-ai-generated-images")],
                        [InlineKeyboardButton("Illuminarty AI", url="https://app.illuminarty.ai/#/")]
                    ]

                    reply_markup = InlineKeyboardMarkup(keyboard)

                    await update.callback_query.answer()
                    await update.callback_query.message.reply_text(
                        f"Изображение сгенерировано АИ с вероятностью: {ai_generated_score * 100:.2f}% \n\n Вы можете прислать другое изображение для проверки, либо проверить самостоятельно на следующих ресурсах:",
                        reply_markup=reply_markup
                    )

                    return
                elif response.status == 429:
                    await asyncio.sleep(5)  # Ждем 5 секунд перед следующей попыткой
                else:
                    error_message = await response.text()
                    await update.callback_query.answer("Ошибка при обращении к API Sightengine.")
                    print(f"Ошибка API: {response.status} - {error_message}")
                    return

    await update.callback_query.answer("Не удалось обработать изображение после нескольких попыток.")





async def start_search(update: Update, context: CallbackContext) -> int:
    if update.message:
        user_id = update.message.from_user.id  # Когда вызвано командой /search
        message_to_reply = update.message
    elif update.callback_query:
        user_id = update.callback_query.from_user.id  # Когда нажата кнопка "Начать поиск"
        message_to_reply = update.callback_query.message
        await update.callback_query.answer()

    # Устанавливаем флаг для режима поиска и сбрасываем другие флаги
    is_search_mode[user_id] = True
    is_gpt_mode[user_id] = False
    is_ocr_mode[user_id] = False

    # Создаем кнопку "Отменить поиск"
    keyboard = [
        [InlineKeyboardButton("Отменить поиск", callback_data='finish_search')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Отправляем сообщение с кнопкой
    await message_to_reply.reply_text(
        "Пожалуйста, отправьте изображение для поиска источника или для проверки, сгенерировано ли оно нейросетью.",
        reply_markup=reply_markup
    )
    
    return ASKING_FOR_FILE

async def handle_file(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id

    # Проверка, если пользователь находится в режиме поиска
    if user_id in is_search_mode and is_search_mode[user_id]:
        if update.message.photo:
            file = await update.message.photo[-1].get_file()
            image_path = 'temp_image.jpg'
            await file.download_to_drive(image_path)
            # Здесь логика для поиска по изображению
            return ASKING_FOR_FILE
        elif update.message.document:
            if update.message.document.mime_type.startswith('image/'):
                file = await update.message.document.get_file()
                image_path = 'temp_image.jpg'
                await file.download_to_drive(image_path)
                # Логика для обработки документов
                return ASKING_FOR_FILE
            else:
                await update.message.reply_text("Пожалуйста, отправьте изображение для поиска источников.")
                return ASKING_FOR_FILE
        else:
            await update.message.reply_text("Пожалуйста, отправьте изображение для поиска источников.")
            return ASKING_FOR_FILE
    
    # Проверка, если пользователь находится в режиме OCR
    if user_id in is_ocr_mode and is_ocr_mode[user_id]:
        if update.message.photo:
            file = await update.message.photo[-1].get_file()
            image_path = 'temp_image.jpg'
            await file.download_to_drive(image_path)
            # Логика для OCR-обработки
            return ASKING_FOR_OCR
        elif update.message.document:
            if update.message.document.mime_type.startswith('image/'):
                file = await update.message.document.get_file()
                image_path = 'temp_image.jpg'
                await file.download_to_drive(image_path)
                return ASKING_FOR_OCR
            else:
                await update.message.reply_text("Пожалуйста, отправьте изображение для OCR.")
                return ASKING_FOR_OCR
        else:
            await update.message.reply_text("Пожалуйста, отправьте изображение для OCR.")
            return ASKING_FOR_OCR


    if user_id in is_gpt_mode and is_gpt_mode[user_id]:
        if update.message.text:
            # Обрабатываем текст сообщения через GPT
            user_message = update.message.text
            response = generate_gemini_response(user_id, query=user_message)
            await update.message.reply_text(response)
            return RUNNING_GPT_MODE
        elif update.message.photo or update.message.document:
            await update.message.reply_text("В режиме GPT поддерживается только текстовый ввод.")
            return RUNNING_GPT_MODE            

    if user_id in is_role_mode and is_role_mode[user_id]:
        if update.message.text:
            # Обрабатываем текст сообщения через GPT
            user_message = update.message.text
            response = generate_gemini_response(user_id, query=user_message)
            await update.message.reply_text(response)
            return RUNNING_GPT_MODE
        elif update.message.photo or update.message.document:
            await update.message.reply_text("В режиме GPT поддерживается только текстовый ввод.")
            return RUNNING_GPT_MODE 

    if user_id in is_asking_mode and is_asking_mode[user_id]:
        if update.message.text:
            # Обрабатываем текст сообщения через GPT
            user_message = update.message.text
            response = generate_gemini_response(user_id, query=user_message)
            await update.message.reply_text(response)
            return ASKING_FOR_FOLLOWUP
        elif update.message.photo or update.message.document:
            await update.message.reply_text("В режиме GPT поддерживается только текстовый ввод.")
            return ASKING_FOR_FOLLOWUP

    # Если пользователь отправил команду /restart, сбрасываем состояние
    if update.message.text == "/restart":
        return await restart(update, context)

    await update.message.reply_text("Пожалуйста, отправьте файл документом или изображение.")
    return ASKING_FOR_FILE

async def finish_search(update: Update, context: CallbackContext) -> int:
    # Проверяем, вызвана ли функция через кнопку или командой
    if update.callback_query:
        query = update.callback_query
        user_id = query.from_user.id
        await query.answer()  # Отвечаем на запрос, чтобы убрать индикатор загрузки на кнопке
        await query.edit_message_text(
            "Вы вышли из режима поиска и вернулись к основным функциям бота",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎨 Найти автора или проверить на ИИ 🎨", callback_data='start_search')],
                [InlineKeyboardButton("🌱 Распознать (Растение или текст) 🌱", callback_data='start_ocr')],
                [InlineKeyboardButton("🦊 Поговорить с ботом 🦊", callback_data='run_gpt')],
                [InlineKeyboardButton("‼️ Полный сброс процесса ‼️", callback_data='restart')]
            ])
        )
    else:
        # Если вызов произошел через команду
        user_id = update.message.from_user.id
        await update.message.reply_text(
            "Вы вышли из режима поиска и вернулись к основным функциям бота",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎨 Найти автора или проверить на ИИ 🎨", callback_data='start_search')],
                [InlineKeyboardButton("🌱 Распознать (Растение или текст) 🌱", callback_data='start_ocr')],
                [InlineKeyboardButton("🦊 Поговорить с ботом 🦊", callback_data='run_gpt')],
                [InlineKeyboardButton("‼️ Полный сброс процесса ‼️", callback_data='restart')]
            ])
        )

    is_search_mode[user_id] = False  # Выключаем режим поиска
    return ConversationHandler.END

# Основная логика обработчика сообщений
async def main_logic(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id

    # Если пользователь находится в режиме поиска, игнорируем основную логику
    if is_search_mode.get(user_id, False):
        return

    # Если пользователь находится в режиме OCR, игнорируем основную логику
    if is_ocr_mode.get(user_id, False):
        return ASKING_FOR_OCR

    if is_gpt_mode.get(user_id, False):
        return RUNNING_GPT_MODE        

    if is_role_mode.get(user_id, False):
        return ASKING_FOR_ROLE 

    if is_asking_mode.get(user_id, False):
        return ASKING_FOR_FOLLOWUP


    # Основная логика обработки сообщений
    await update.message.reply_text("Обрабатываем сообщение в основной логике.")
    return ConversationHandler.END

# Добавим функцию для обработки неизвестных сообщений в режиме поиска
async def unknown_search_message(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("Пожалуйста, отправьте фото или документ.")
    return ASKING_FOR_FILE

async def restart(update: Update, context: CallbackContext) -> int:
    # Проверка типа события
    if update.message:
        user_id = update.message.from_user.id
        message_to_reply = update.message
    elif update.callback_query:
        user_id = update.callback_query.from_user.id
        message_to_reply = update.callback_query.message
    else:
        return ConversationHandler.END

    # Удаляем все данные пользователя
    if user_id in user_data:
        del user_data[user_id]  # Удаляем старые данные пользователя  

    if user_id in is_search_mode:
        del is_search_mode[user_id]  # Выключаем режим поиска, если он включен

    if user_id in is_ocr_mode:
        del is_ocr_mode[user_id]

    if user_id in is_gpt_mode:
        del is_gpt_mode[user_id]

    if user_id in is_asking_mode:
        del is_asking_mode[user_id]

    if user_id in is_role_mode:
        del is_role_mode[user_id]    
    
    logger.info(f"User {user_id} restarted the process.") 

    # Отправляем сообщение с кнопками
    keyboard = [
        [InlineKeyboardButton("🎨 Найти автора или проверить на ИИ 🎨", callback_data='start_search')],
        [InlineKeyboardButton("🌱 Распознать (Растение или текст) 🌱", callback_data='start_ocr')],
        [InlineKeyboardButton("🦊 Поговорить с ботом 🦊", callback_data='run_gpt')]

    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await message_to_reply.reply_text(
        'Бот успешно перезапущен.\n\n'
        '🌠Этот бот поможет вам создать пост для группы Anemone. Изначально пост будет виден исключительно вам, так что не бойтесь экспериментировать и смотреть что получится\n\n'
        'Для начала, пожалуйста, отправьте ссылку на автора. Если у вас её нет, то отправьте любой текст\n\n'
        '<i>Так же вы можете воспользоваться одной из кнопок ниже чтобы найти автора по изображению, найти серию и таймметку аниме по кадру из него, проверить вероятность использования ИИ для создания изображения, распознать текст или растение. либо поговорить с ботом</i>\n\n',
        reply_markup=reply_markup,
        parse_mode='HTML'
    )

    # Устанавливаем новое состояние после перезапуска
    user_data[user_id] = {'status': 'awaiting_artist_link'}
    
    return ASKING_FOR_ARTIST_LINK



async def start_ocr(update: Update, context: CallbackContext) -> int:
    if update.message:
        user_id = update.message.from_user.id  # Когда вызвано командой /search
        message_to_reply = update.message
    elif update.callback_query:
        user_id = update.callback_query.from_user.id  # Когда нажата кнопка "Начать поиск"
        message_to_reply = update.callback_query.message
        await update.callback_query.answer()    

    is_ocr_mode[user_id] = True    
    is_search_mode[user_id] = False
    is_gpt_mode[user_id] = False
  # Устанавливаем флаг для пользователя в режим поиска

    # Создаем кнопку "Отменить поиск"
    keyboard = [
        [InlineKeyboardButton("Отменить режим распознавания", callback_data='finish_ocr')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Отправляем сообщение с кнопкой
    await message_to_reply.reply_text(
        "Пожалуйста, отправьте изображение для поиска или распознавания. Лучше отправлять сжатые изображения, тогда бот работает быстрее. Оригиналы в виде файлов отправляйте только по необходимости (мелкий текст, мелкие растения и тд)",
        reply_markup=reply_markup
    )
    
    return ASKING_FOR_OCR

async def finish_ocr(update: Update, context: CallbackContext) -> int:
    keyboard = [
        [InlineKeyboardButton("🎨 Найти автора или проверить на ИИ 🎨", callback_data='start_search')],
        [InlineKeyboardButton("🌱 Распознать (Растение или текст) 🌱", callback_data='start_ocr')],
        [InlineKeyboardButton("🦊 Поговорить с ботом 🦊", callback_data='run_gpt')],
        [InlineKeyboardButton("‼️ Полный сброс процесса ‼️", callback_data='restart')]

    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:  # Если функция вызвана через нажатие кнопки
        query = update.callback_query
        user_id = query.from_user.id
        is_ocr_mode[user_id] = False  # Выключаем режим поиска
        is_search_mode[user_id] = False
        is_gpt_mode[user_id] = False
        is_role_mode[user_id] = False
        is_asking_mode[user_id] = False  # Выключаем режим поиска
        
        await query.answer()  # Отвечаем на запрос, чтобы убрать индикатор загрузки на кнопке
        await query.edit_message_text(
            "Вы вышли из режима распознавания и вернулись к основным функциям бота. Вы можете продолжить заполнять статью на том моменте на котором остановились, либо воспользоваться одной из кнопок:", 
            reply_markup=reply_markup  # Добавляем кнопки
        )
    
    elif update.message:  # Если функция вызвана через команду /fin_ocr
        user_id = update.message.from_user.id
        is_ocr_mode[user_id] = False  # Выключаем режим поиска
        is_search_mode[user_id] = False
        is_gpt_mode[user_id] = False
        is_role_mode[user_id] = False
        is_asking_mode[user_id] = False  # Выключаем режим поиска
        
        await update.message.reply_text(
            "Вы вышли из режима распознавания и вернулись к основным функциям бота. Вы можете продолжить заполнять статью на том моменте на котором остановились, либо воспользоваться одной из кнопок:", 
            reply_markup=reply_markup  # Добавляем кнопки
        )

    return ConversationHandler.END
    
# Добавим функцию для обработки неизвестных сообщений в режиме поиска
async def unknown_ocr_message(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("Пожалуйста, отправьте фото или документ.")
    return ASKING_FOR_OCR

# Обработчик нажатия на кнопку "Распознать текст"
async def ocr_space_with_url(img_url, api_key):
    ocr_url = "https://api.ocr.space/parse/imageurl"

    async with aiohttp.ClientSession() as session:
        params = {
            'apikey': api_key,
            'url': img_url,
            'language': 'rus',  # Указываем язык
            'isOverlayRequired': 'False',  # Нужно ли накладывать текст на изображение
            'detectOrientation': 'True',  # Определять ориентацию текста
            'scale': 'True'  # Масштабировать изображение
        }

        async with session.get(ocr_url, params=params) as response:
            if response.status == 200:
                result = await response.json()
                try:
                    return result["ParsedResults"][0]["ParsedText"]
                except (KeyError, IndexError):
                    return "Текст не был распознан."
            else:
                return f"Ошибка API OCR.space: {response.status}"


# Измененный обработчик кнопки для OCR
async def button_ocr(update, context):
    query = update.callback_query
    await query.answer()

    # Получаем URL изображения с Catbox
    img_url = context.user_data.get('img_url')

    if query.data == 'recognize_text':
        if img_url:
            # Вызов функции для распознавания текста через Google Cloud Vision API с использованием URL
            api_key = 'K86410931988957'  # Ваш ключ API
            recognized_text = await ocr_space_with_url(img_url, api_key)
            keyboard = [
                [InlineKeyboardButton("Отменить режим распознавания", callback_data='finish_ocr')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            # Отправляем распознанный текст пользователю
            await query.message.reply_text(
                f"Распознанный текст:\n{recognized_text}\n\nОтправьте следующее изображение для распознавания либо нажмите кнопку ниже",
                reply_markup=reply_markup  # Добавляем кнопку к последнему сообщению
            )
        else:
            # Отправляем сообщение об ошибке с кнопкой
            await query.message.reply_text(
                "URL изображения не найден. Попробуйте ещё раз.",
                reply_markup=reply_markup  # Добавляем кнопку к этому сообщению
            )

    elif query.data == 'recognize_plant':
        await recognize_plant(update, context)  # Вызов функции для распознавания растения
    else:
        await query.message.reply_text("Неизвестная команда.")



async def recognize_plant(update: Update, context: CallbackContext) -> None:
    user_id = update.callback_query.from_user.id
    img_url = context.user_data.get('img_url')

    if not img_url:
        await update.callback_query.answer("Сначала загрузите изображение.")
        return

    logger.info(f"URL изображения: {img_url}")

    api_key = "2b10C744schFhHigMMjMsDmV"
    project = "all"  
    lang = "ru"   
    include_related_images = "true"  

    # URL-кодирование для изображения
    encoded_image_url = aiohttp.helpers.quote(img_url)

    # Формирование URL для запроса
    api_url = (
        f"https://my-api.plantnet.org/v2/identify/{project}?"
        f"images={encoded_image_url}&"
        f"organs=auto&"
        f"lang={lang}&"
        f"include-related-images={include_related_images}&"
        f"api-key={api_key}"
    )
    
    # Отправляем сообщение с начальным текстом
    initial_message = await update.callback_query.message.reply_text("Запрос принят...")

    async with aiohttp.ClientSession() as session:
        async with session.get(api_url) as response:
            status = response.status
            logger.info(f"Статус ответа: {status}")

            if status == 200:
                prediction = await response.json()
                logger.info(f"Полный ответ от PlantNet: {prediction}")

                if prediction.get('results'):
                    keyboard = []
                    for idx, plant in enumerate(prediction['results'][:3]):
                        species = plant.get('species', {})
                        scientific_name = species.get('scientificNameWithoutAuthor', 'Неизвестное растение')
                        common_names = species.get('commonNames', [])
                        common_name_str = ', '.join(common_names) if common_names else 'Название отсутствует'
                        
                        # Извлекаем процент сходства
                        similarity_score = plant.get('score', 0) * 100  # Предполагаем, что значение score от 0 до 1
                        similarity_text = f"{similarity_score:.2f}%"  # Форматируем до двух знаков после запятой
                        
                        # Сохраняем данные о растениях в context.user_data для обработки нажатий
                        images = plant.get('images', [])
                        context.user_data[f"plant_{idx}"] = {
                            "scientific_name": scientific_name,
                            "common_names": common_name_str,
                            "images": images
                        }

                        logger.info(f"Plant {idx}: {scientific_name}, Images: {context.user_data[f'plant_{idx}']['images']}")

                        # Создаем кнопку для каждого растения с процентом сходства в начале
                        keyboard.append([InlineKeyboardButton(
                            text=f"{similarity_text} - {scientific_name} ({common_name_str})",
                            callback_data=f"plant_{idx}"
                        )])

                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await initial_message.edit_text(
                        "Выберите одно из предложенных растений:",
                        reply_markup=reply_markup
                    )
                else:
                    await initial_message.edit_text("Растение не найдено.")
            else:
                error_message = await response.text()
                logger.error(f"Ошибка от API PlantNet: {error_message}")
                await initial_message.edit_text("Ошибка при распознавании растения. Данное растение в базе не обнаружено, убедитесь что это именно растение, цветок, фрукт или овощь а не что-то иное. Так же можете попробовать сфотографировать под иным ракурсом")




import wikipediaapi  # Импортируем библиотеку

# Инициализация Wikipedia API с User-Agent
user_agent = "MyPlantBot/1.0 sylar1907942@gmail.com)"
wiki_wiki = wikipediaapi.Wikipedia(language='ru', user_agent=user_agent)  


wikipedia.set_lang('ru')  # Установите язык на русский

async def get_wikipedia_link(scientific_name: str, common_names: list) -> tuple:
    try:
        # Выполняем поиск по научному названию
        search_results = wikipedia.search(scientific_name)
        logger.info(f"Search results for '{scientific_name}': {search_results}")

        # Проверяем, есть ли результаты поиска
        if search_results:
            for article_title in search_results:
                # Проверяем, относится ли статья к категории "растения"
                page = wiki_wiki.page(article_title)
                if page.exists():
                    categories = page.categories
                    # Проверяем наличие ключевых категорий
                    if any('растения' in cat.lower() for cat in categories):
                        logger.info(f"Found article '{article_title}' in category 'plants'")
                        # Формируем и возвращаем ссылку на статью
                        return (f"https://ru.wikipedia.org/wiki/{article_title.replace(' ', '_')}", article_title)

        # Если результаты по научному названию не найдены, ищем по общим названиям
        for name in common_names:
            search_results = wikipedia.search(name)
            logger.info(f"Search results for '{name}': {search_results}")
            if search_results:
                for article_title in search_results:
                    # Проверяем, относится ли статья к категории "растения"
                    page = wiki_wiki.page(article_title)
                    if page.exists():
                        categories = page.categories
                        if any('растения' in cat.lower() for cat in categories):
                            logger.info(f"Found article '{article_title}' in category 'plants'")
                            # Формируем и возвращаем ссылку на статью
                            return (f"https://ru.wikipedia.org/wiki/{article_title.replace(' ', '_')}", article_title)
    
    except Exception as e:
        logger.error(f"Error fetching Wikipedia link: {e}")

    # Если ничего не найдено или статья не относится к растениям, возвращаем None
    return (None, None)


import wikipedia


def escape_markdown_v2(text: str) -> str:
    # Экранирование специальных символов в MarkdownV2, включая символ '='
    return re.sub(r'([\_\*\[\]\(\)\~\`\>\#\+\-\.\!\=])', r'\\\1', text)


async def button_more_plants_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    plant_key = query.data  # Получаем callback_data, например 'plant_0'
    
    logger.info(f"Looking for plant data with key: {plant_key}")

    plant_data = context.user_data.get(plant_key)
    if plant_data:
        scientific_name = plant_data['scientific_name']
        common_names = plant_data['common_names']
        context.user_data['scientific_name'] = scientific_name

        if isinstance(common_names, str):
            common_names = [common_names]  # Преобразуем в список, если это строка
        
        wikipedia_link, article_title = await get_wikipedia_link(scientific_name, common_names)

        description = ""
        if wikipedia_link:
            try:
                # Получаем краткое описание статьи по найденному названию статьи
                summary = wikipedia.summary(article_title, sentences=12)
                description += f"{escape_markdown_v2(summary)}\n\n"
            except Exception as e:
                logger.error(f"Error fetching summary for {article_title}: {e}")
                description += "Краткое описание недоступно\n\n"
        else:
            logger.warning(f"No Wikipedia page found for: {scientific_name} or common names")
            description = "\n\nИнформация по данному растению не найдена\n\n"

        images = plant_data.get('images', [])
        logger.info(f"Retrieved plant data: {plant_data}")

        if images:
            media = []  # Список для хранения объектов медиа
            for idx, img in enumerate(images):
                img_url = img['url']['o'] if 'url' in img else None
                if img_url:
                    if idx == 0:
                        # Подготавливаем подпись и добавляем в лог
                        caption = (
                            f"Растение: {escape_markdown_v2(scientific_name)}\n"
                            f"Общие названия: {', '.join(map(escape_markdown_v2, common_names))}\n"
                            f"{truncate_text_with_link(description, 300, wikipedia_link, scientific_name)}"
                        )
                        logger.info(f"Caption for first image: {caption}")
                        media.append(InputMediaPhoto(media=img_url, caption=caption, parse_mode='MarkdownV2'))
                    else:
                        media.append(InputMediaPhoto(media=img_url))

            if media:
                logger.info(f"Media items ready for sending: {media}")
                logger.info(f"Number of media items: {len(media)}")
                
                try:
                    await query.message.reply_media_group(media)  # Отправляем медиагруппу
                    logger.info("Media group sent successfully.")
                except Exception as e:
                    logger.error(f"Error sending media group: {e}")
                    await query.message.reply_text("Ошибка при отправке изображений. Проверьте форматирование текста.")
            else:
                await query.message.reply_text("Изображения не найдены")
        else:
            await query.message.reply_text("Изображений нет")
        
        # Отправляем сообщение с кнопками после медиа
        keyboard = [
            [InlineKeyboardButton("Подробнее об этом растении", callback_data='gpt_plants_more')],         
            [InlineKeyboardButton("Помощь по уходу за этим растением", callback_data='gpt_plants_help')],        
            [InlineKeyboardButton("Отменить режим распознавания", callback_data='finish_ocr')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.reply_text(
            "Для получения более подробной информации об этом растении либо об уходе за ним, воспользуйтесь кнопками ниже. Либо отправьте следующее изображение",
            reply_markup=reply_markup  # Добавляем кнопку к этому сообщению
        )
    else:
        await query.message.reply_text("Данные о растении не найдены")
    
    await query.answer()


async def gpt_plants_more_handler(update, context):
    """Асинхронный обработчик для запроса ухода за растением по научному названию."""
    user_id = update.callback_query.from_user.id
    scientific_name = context.user_data.get("scientific_name")
    await update.callback_query.answer()

    if not scientific_name:
        await update.callback_query.answer("Научное название не указано. Попробуйте снова.")
        return

    # Формируем запрос с научным названием
    query = f" Расскажи больше про {scientific_name}, например, интересные факты, способы применения, укажи если ядовито, какие-то особенности и прочее. При этом будь лаконичной. В ответе используй разметку markdown_v2"

    # Генерация ответа без контекста
    response_text = generate_plant_help_response(user_id, query=query)
    response_text = limit_response_length(response_text)
    response_text = escape_gpt_markdown_v2(response_text)

    keyboard = [
        [InlineKeyboardButton("Помощь по уходу за этим растением", callback_data='gpt_plants_help')],        
        [InlineKeyboardButton("Отменить режим распознавания", callback_data='finish_ocr')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Редактируем существующее сообщение с новым ответом и кнопками
    await update.callback_query.message.edit_text(response_text, reply_markup=reply_markup, parse_mode='MarkdownV2')


async def gpt_plants_help_handler(update, context):
    """Асинхронный обработчик для запроса ухода за растением по научному названию."""
    user_id = update.callback_query.from_user.id
    scientific_name = context.user_data.get("scientific_name")
    await update.callback_query.answer()

    if not scientific_name:
        await update.callback_query.answer("Научное название не указано. Попробуйте снова.")
        return

    # Формируем запрос с научным названием
    query = f"Как ухаживать за {scientific_name}?В ответе используй разметку markdown_v2"

    # Генерация ответа без контекста
    response_text = generate_plant_help_response(user_id, query=query)
    response_text = limit_response_length(response_text)
    response_text = escape_gpt_markdown_v2(response_text)

    keyboard = [
        [InlineKeyboardButton("Подробнее об этом растении", callback_data='gpt_plants_more')],         
        [InlineKeyboardButton("Отменить режим распознавания", callback_data='finish_ocr')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Редактируем существующее сообщение с новым ответом и кнопками
    await update.callback_query.message.edit_text(response_text, reply_markup=reply_markup, parse_mode='MarkdownV2')





def truncate_text_with_link(text: str, max_length: int, link: str, scientific_name: str) -> str:
    """Обрезает текст до max_length символов, добавляет ссылку на статью или Google-поиск."""
    ellipsis = escape_markdown_v2('...')
    
    # Если ссылка на Википедию отсутствует, формируем ссылку на Google-поиск
    if link:
        link_text = f"\n[Узнать больше на википедии]({escape_markdown_v2(link)})"  # Экранируем ссылку на Википедию
    else:
        google_search_link = f"https://www.google.com/search?q={scientific_name.replace(' ', '+')}"
        link_text = f"\n[Найти в Google]({escape_markdown_v2(google_search_link)})"  # Ссылка на Google
    
    # Вычисляем допустимую длину для текста без учета ссылки
    available_length = max_length - len(link_text) - len(ellipsis)

    # Если текст нужно обрезать
    if len(text) > available_length:
        truncated_text = text[:available_length] + ellipsis
    else:
        truncated_text = text

    # Добавляем ссылку в конце
    return truncated_text + link_text







HELP_TEXT = """
▶️Пост в Анемоне формируется из двух частей \- непосредственно сам пост видимый в телеграме \, плюс статья Telagraph доступная по ссылке\(для примера посмотрите любой из последних постов в группе\) Бот позволяет сделать обе части\. \n\n  Изначально статья и всё её содержание видны только вам\, администрации она станет доступна только после того как вы нажмёте сначала кнопку \" К Завершению Публикации \" и затем \(по желанию\) кнопку \/share \(поделиться\)\. Если после публикации вы не захотите вводить команду share то публикация останется видна только вам\n\n ▶️Статья в Telegraph формируется в порядке отправки вами изображений и текста боту\.\n\n Во время создания статьи\, с помощью соответствующих кнопок вы можете\: \n\-открыть предросмотр\n \-удалить последний добавленный элемент \(работает неограниченное количество раз\, пока статья не станет пустой\)\n \-редактировать всё содержимое вашей статьи через список добавленных изображений и текста\. С любым фрагментом можно делать что угодно\, менять текст на изображение и наоборот\, удалять\,  исправлять\, однако только до тех пор пока вы не используете кнопку \" К Завершению Публикации \", послее её нажатия редактировать статью уже будет больше нельзя\, только наполнить новую\. \n\n▶️Поддерживаемые тэги разметки статьи\(без кавычек\)\n \- \"\*\*\*\" — горизонтальная линия\-разделитель \(отправьте три звёздочки отдельным сообщением\, в этом месте в статье телеграф появится разделитель\)\.\n\- \"\_текст\_\" — курсив\.\n\- \"\*текст\*\" — жирный текст\.\n\- \"\[текст ссылки\]\(ссылка\)\" — гиперссылка\.\n\- \"видео\: \" — вставка видео с Vimeo или YouTube\.\n\- \"цитата\:\" — цитата\.\n\- \"цитата по центру\:\" — центрированная цитата\.\n\- "заголовок:" — заголовок\\.\n\\- "подзаголовок:" — подзаголовок\\.\n\n Последние 5 тэгов пишутся в начале сообщения и применяются ко всему сообщению целиком\. Каждое новое сообщение — это новый абзац\. Сообщения без тэгов — обычный текст\.\n\n Пример\: \(без кавычек\)\n\- \"цитата\: \*Волк\* никогда не будет жить в загоне\, но загоны всегда будут жить в \*волке\*\" — в статье телеграф примет вид цитата\, в которой слово \"волк\" выделено жирным\.\n\- \"видео\: ссылка\_на\_видео\" — вставка интерактивного видео YouTube или Vimeo\.\n\n▶️Кроме того бот поддерживает загрузку GIF файлов\. Для этого переименуйте \.GIF в \.RAR \, затем отправьте файл боту во время оформления поста\. Это нужно для того чтобы телеграм не пережимал GIF файлы\, бот автоматически переименует файл обратно в GIF перед размещением в Телеграф\n\n▶️Так же вы можете отправить что\-то администрации напрямую\, в режиме прямой связи\. Для этого введите команду \/send и после неё все ваши сообщения отправленные боту тут же будут пересылаться администрации\. Это могут быть какие\-то пояснения\, дополнительные изображения или их правильное размещение в посте телеграм\, вопросы\, предложения\, ссылка на самостоятельно созданную статью телеграф\, пойманные в боте ошибки и что угодно ещё\. Для завершения этого режима просто введите \/fin и бот вернётся в свой обычный режим\. Просьба не спамить через этот режим\, писать или отправлять только нужную информацию  \n
"""

async def help_command(update: Update, context: CallbackContext) -> None:
    if update.message:  # Если команда пришла через сообщение
        await update.message.reply_text(HELP_TEXT, parse_mode='MarkdownV2')
    elif update.callback_query:  # Если команда пришла через инлайн-кнопку
        await update.callback_query.message.reply_text(HELP_TEXT, parse_mode='MarkdownV2')
        await update.callback_query.answer()  # Подтверждаем нажатие кнопки

async def handle_artist_link(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    if user_id in user_data and user_data[user_id]['status'] == 'awaiting_artist_link':
        user_data[user_id]['artist_link'] = update.message.text
        logger.info(f"User {user_id} provided author link: {update.message.text}")


        await update.message.reply_text(
            '🌟Хорошо. Теперь отправьте имя автора. \n\n <i>Чтобы скрыть слово "Автор:", используйте символ "^" в начале и конце сообщения. Например: ^Имя^</i>',
            parse_mode='HTML' # Добавляем клавиатуру
        )
        user_data[user_id]['status'] = 'awaiting_author_name'
        return ASKING_FOR_AUTHOR_NAME
    else:
        await update.message.reply_text('🚫Ошибка: данные не найдены.')
        return ConversationHandler.END

# Ввод имени художника
async def handle_author_name(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id

    # Проверка, что пользователь находится в нужном состоянии
    if user_id in user_data and user_data[user_id].get('status') == 'awaiting_author_name':

        # Если авторское имя ещё не сохранено
        if 'author_name' not in user_data[user_id]:
            author_input = update.message.text.strip()

            # Проверяем, если авторское имя обернуто в "^...^"
            match_full = re.match(r'^\^(.*)\^$', author_input, re.S)
            if match_full:
                # Если весь текст внутри "^...^", используем его как заголовок и убираем авторское имя
                title = match_full.group(1).strip()
                user_data[user_id]['title'] = title
                user_data[user_id]['author_name'] = ""  # Очищаем author_name
                user_data[user_id]['extra_phrase'] = ""  # Нет доп. фразы
            else:
                # Проверка на наличие фразы в начале текста "^...^"
                match_partial = re.match(r'^\^(.*?)\^\s*(.*)', author_input, re.S)
                if match_partial:
                    # Извлекаем фразу и имя автора
                    phrase = match_partial.group(1).strip()  # Фраза из "^...^"
                    author_name = match_partial.group(2).strip()  # Остаток текста как автор
                    user_data[user_id]['extra_phrase'] = phrase  # Сохраняем фразу
                    user_data[user_id]['author_name'] = author_name  # Имя автора
                    user_data[user_id]['title'] = author_name  # Используем как заголовок
                else:
                    # Если нет фразы в "^...^", сохраняем всё как имя автора
                    author_name = author_input
                    user_data[user_id]['author_name'] = author_name
                    user_data[user_id]['title'] = author_name  # Заголовок статьи

            logger.info(f"User {user_id} provided author name or title: {author_input}")
        else:
            # Если author_name уже есть, просто используем его для заголовка
            author_name = user_data[user_id]['author_name']
            user_data[user_id]['title'] = author_name  # Обновляем заголовок

        # Переход к следующему этапу
        keyboard = [
            [InlineKeyboardButton("Помощь и разметка", callback_data='help_command')],
            [InlineKeyboardButton("‼️Полный сброс процесса‼️", callback_data='restart')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            'Отлично \n🌌Теперь приступим к наполнению публикации контентом. Отправьте изображения файлом (без сжатия) или текст. Если вы отправите изображение с подписью, то в статье телеграф текст будет так же отображаться как подпись под изображением.\n\n'
            'Текст поддерживает различное форматирование. Для получения списка тэгов нажмите на кнопку помощи.\n\n'
            '<i>Так же вы можете переслать в бот сообщения с текстом и/или изображениями, и бот тут же автоматически перенесет всё это в статью в той же очерёдности</i>',
            parse_mode='HTML',
            reply_markup=reply_markup  # Добавляем клавиатуру
        )
        user_data[user_id]['status'] = 'awaiting_image'
        return ASKING_FOR_IMAGE

    else:
        await update.message.reply_text('🚫Ошибка: данные не найдены. Попробуйте снова или нажмите /restart.')
        return ConversationHandler.END



def compress_image(file_path: str, output_path: str) -> None:
    # Определяем максимальный размер файла в байтах (5 МБ)
    max_size = 5 * 1024 * 1024

    # Проверяем, является ли файл GIF или .rar
    if file_path.endswith('.gif') or file_path.endswith('.rar'):
        return

    # Открываем изображение
    with Image.open(file_path) as img:
        # Проверяем формат и размер изображения
        if img.format == 'PNG' and os.path.getsize(file_path) > max_size:
            # Если PNG и размер больше 5 МБ, конвертируем в JPG
            img = img.convert('RGB')
            temp_path = file_path.rsplit('.', 1)[0] + '.jpg'
            img.save(temp_path, format='JPEG', quality=90)
            file_path = temp_path
            img = Image.open(file_path)
        
        # Если изображение имеет альфа-канал, преобразуем его в RGB
        if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
            img = img.convert('RGB')

        # Сохраняем изображение в формате JPG с начальным качеством
        quality = 90
        img.save(output_path, format='JPEG', quality=quality)

        # Проверяем размер файла и сжимаем при необходимости
        while os.path.getsize(output_path) > max_size:
            quality -= 10
            if quality < 10:
                break
            img.save(output_path, format='JPEG', quality=quality)

        # Если изображение всё ещё больше 5 МБ, уменьшаем разрешение
        while os.path.getsize(output_path) > max_size:
            width, height = img.size
            img = img.resize((width // 2, height // 2), Image.ANTIALIAS)
            img.save(output_path, format='JPEG', quality=quality)

        # Удаляем временный JPG файл, если он был создан
        if file_path.endswith('.jpg'):
            os.remove(file_path)

# Функция для загрузки изображения на сloudinary
async def upload_image_to_cloudinary(file_path: str) -> str:
    CLOUDINARY_URL = 'https://api.cloudinary.com/v1_1/dmacjjaho/image/upload'
    UPLOAD_PRESET = 'ml_default'
    timeout = ClientTimeout(total=10)  # Таймаут в 10 секунд    
    
    async with aiohttp.ClientSession() as session:
        with open(file_path, 'rb') as f:
            form = aiohttp.FormData()
            form.add_field('file', f)
            form.add_field('upload_preset', UPLOAD_PRESET)

            async with session.post(CLOUDINARY_URL, data=form) as response:
                if response.status == 200:
                    response_json = await response.json()
                    return response_json['secure_url']
                else:
                    response_text = await response.text()  # Логируем текст ошибки
                    raise Exception(f"Ошибка загрузки на Cloudinary: {response.status}, ответ: {response_text}")


# Функция для загрузки изображения на imgbb
async def upload_image_to_imgbb(file_path: str) -> str:
    timeout = ClientTimeout(total=4)  # Таймаут в 10 секунд
    async with aiohttp.ClientSession() as session:
        with open(file_path, 'rb') as f:
            form = aiohttp.FormData()
            form.add_field('key', IMGBB_API_KEY)
            form.add_field('image', f)

            async with session.post('https://api.imgbb.com/1/upload', data=form) as response:
                if response.status == 200:
                    response_json = await response.json()
                    return response_json['data']['url']
                else:
                    raise Exception(f"Ошибка загрузки на imgbb: {response.status}")

# Функция для загрузки изображения на Imgur
async def upload_image_to_imgur(file_path: str) -> str:
    IMGUR_CLIENT_ID = '5932e0bc7fdb523'  # Укажите свой ID клиента Imgur
    headers = {'Authorization': f'Client-ID {IMGUR_CLIENT_ID}'}
    async with aiohttp.ClientSession() as session:
        with open(file_path, 'rb') as f:
            form = aiohttp.FormData()
            form.add_field('image', f)

            async with session.post('https://api.imgur.com/3/image', headers=headers, data=form) as response:
                if response.status == 200:
                    response_json = await response.json()
                    return response_json['data']['link']
                else:
                    raise Exception(f"Ошибка загрузки на Imgur: {response.status}")

# Функция для загрузки изображения на Catbox
async def upload_image_to_catbox(file_path: str) -> str:
    async with aiohttp.ClientSession() as session:
        with open(file_path, 'rb') as f:
            form = aiohttp.FormData()
            form.add_field('reqtype', 'fileupload')
            form.add_field('fileToUpload', f)
            
            # Добавляем ваш userhash
            form.add_field('userhash', '1f68d2a125c66f6ab79a4f89c')

            async with session.post('https://catbox.moe/user/api.php', data=form) as response:
                if response.status == 200:
                    return await response.text()  # возвращает URL загруженного файла
                else:
                    raise Exception(f"Ошибка загрузки на Catbox: {response.status}")

async def upload_image_to_freeimage(file_path: str) -> str:
    async with aiohttp.ClientSession() as session:
        with open(file_path, 'rb') as f:
            form = aiohttp.FormData()
            form.add_field('key', '6d207e02198a847aa98d0a2a901485a5')  # Ваш API ключ для freeimage.host
            form.add_field('action', 'upload')
            form.add_field('source', f)  # Используем файл для загрузки

            async with session.post('https://freeimage.host/api/1/upload', data=form) as response:
                if response.status == 200:
                    response_json = await response.json()
                    return response_json['image']['url']  # Проверьте правильность пути к URL в ответе
                elif response.status == 400:
                    response_text = await response.text()
                    raise Exception(f"Ошибка загрузки на Free Image Hosting: {response_text}")
                else:
                    raise Exception(f"Ошибка загрузки на Free Image Hosting: {response.status}")

# Основная функция загрузки изображения с проверкой доступности сервисов
async def upload_image(file_path: str) -> str:
    try:
        # Попытка загрузки на imgbb
        return await upload_image_to_imgbb(file_path)
    except Exception as e:
        logging.error(f"Ошибка загрузки на imgbb: {e}")
        try:
            # Попытка загрузки на Cloudinary
            return await upload_image_to_cloudinary(file_path)
        except Exception as e:
            logging.error(f"Ошибка загрузки на Cloudinary: {e}")
            try:
                # Попытка загрузки на Free Image Hosting
                return await upload_image_to_freeimage(file_path)
            except Exception as e:
                logging.error(f"Ошибка загрузки на Free Image Hosting: {e}")
                try:
                    # Попытка загрузки на Catbox
                    return await upload_image_to_catbox(file_path)
                except Exception as e:
                    logging.error(f"Ошибка загрузки на Catbox: {e}")
                    try:
                        # Попытка загрузки на Imgur
                        return await upload_image_to_imgur(file_path)
                    except Exception as e:
                        logging.error(f"Ошибка загрузки на Imgur: {e}")
                        raise Exception("Не удалось загрузить изображение на все сервисы.")

import re

# Определяем разметку тегов
markup_tags = {
    '*': 'strong',  # Жирный текст
    '_': 'em',      # Курсив
}

import re

def apply_markup(text: str) -> dict:
    """Применяет разметку к тексту на основе команд и возвращает узел контента в формате Telegra.ph."""
    
    text = text.strip()  # Убираем пробелы в начале и в конце текста
    text_lower = text.lower()

    # Обработка команд
    if text_lower.startswith("подзаголовок: "):
        content = text[len("Подзаголовок: "):].strip()
        content = apply_markup_to_content(content)
        return {"tag": "h4", "children": content}
    elif text_lower.startswith("цитата:"):
        content = text[len("Цитата:"):].strip()
        content = apply_markup_to_content(content)
        return {"tag": "blockquote", "children": content}
    elif text_lower.startswith("заголовок: "):
        content = text[len("Заголовок: "):].strip()
        content = apply_markup_to_content(content)
        return {"tag": "h3", "children": content}
    elif text_lower.startswith("цитата по центру:"):
        content = text[len("Цитата по центру:"):].strip()
        content = apply_markup_to_content(content)
        return {"tag": "aside", "children": content}
    elif text_lower.startswith("***"):
        return {"tag": "hr"}
    elif text_lower.startswith("видео: "):
        video_url = text[len("Видео: "):].strip()
        # Кодируем URL, чтобы он подходил для использования в src
        encoded_url = re.sub(r'https://', 'https%3A%2F%2F', video_url)
        
        # Проверяем, это YouTube или Vimeo
        if "youtube.com" in video_url or "youtu.be" in video_url:
            return {
                "tag": "figure",
                "children": [
                    {
                        "tag": "iframe",
                        "attrs": {
                            "src": f"/embed/youtube?url={encoded_url}",
                            "width": 640,
                            "height": 360,
                            "frameborder": 0,
                            "allowtransparency": "true",
                            "allowfullscreen": "true",
                            "scrolling": "no"
                        }
                    }
                ]
            }
        elif "vimeo.com" in video_url:
            return {
                "tag": "figure",
                "children": [
                    {
                        "tag": "iframe",
                        "attrs": {
                            "src": f"/embed/vimeo?url={encoded_url}",
                            "width": 640,
                            "height": 360,
                            "frameborder": 0,
                            "allowtransparency": "true",
                            "allowfullscreen": "true",
                            "scrolling": "no"
                        }
                    }
                ]
            }

    # Если команда не распознана, обрабатываем текст с разметкой
    content = apply_markup_to_content(text)
    return {"tag": "div", "children": content}

def apply_markup_to_content(content: str) -> list:
    """Обрабатывает разметку в тексте и возвращает список узлов для Telegra.ph."""
    nodes = []

    # Регулярные выражения для разметки
    regex_markup = re.compile(r'(\*|_)(.*?)\1', re.DOTALL)
    link_regex = re.compile(r'\[(.*?)\]\((.*?)\)', re.DOTALL)

    # Сначала обрабатываем гиперссылки
    pos = 0
    temp_nodes = []
    for match in link_regex.finditer(content):
        # Добавляем текст до текущего совпадения
        if pos < match.start():
            temp_nodes.append(content[pos:match.start()])

        # Добавляем узел ссылки
        link_text, url = match.groups()
        temp_nodes.append({"tag": "a", "attrs": {"href": url}, "children": [{"tag": "text", "children": [link_text]}]})

        # Обновляем позицию
        pos = match.end()

    # Добавляем оставшийся текст после обработки гиперссылок
    if pos < len(content):
        temp_nodes.append(content[pos:])

    # Теперь обрабатываем остальную разметку
    for node in temp_nodes:
        if isinstance(node, str):
            # Обрабатываем текст с разметкой
            while True:
                match = regex_markup.search(node)
                if not match:
                    # Если больше нет совпадений, добавляем оставшийся текст
                    nodes.append({"tag": "text", "children": [node]})
                    break
                # Добавляем текст до текущего совпадения
                if match.start() > 0:
                    nodes.append({"tag": "text", "children": [node[:match.start()]]})

                # Определяем тег и добавляем узел
                tag = markup_tags.get(match.group(1))
                if tag:
                    nodes.append({"tag": tag, "children": [match.group(2)]})

                # Обновляем строку: обрезаем её до конца текущего совпадения
                node = node[match.end():]
        else:
            nodes.append(node)

    return nodes

async def edit_article(update: Update, context: CallbackContext) -> None:
    # Проверяем, является ли обновление запросом обратного вызова (нажатие кнопки)
    if update.callback_query:
        query = update.callback_query
        user_id = query.from_user.id
    else:
        user_id = update.message.from_user.id  # Если это сообщение, получаем ID пользователя

    media = user_data[user_id].get('media', [])
    
    if not media:
        await update.message.reply_text("🚫 Ошибка: нет фрагментов для редактирования.")
        return

    # Удаляем предыдущее сообщение с кнопками содержания статьи
    if 'last_content_message_id' in user_data[user_id]:
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,  # Используем effective_chat
                message_id=user_data[user_id]['last_content_message_id']
            )
        except Exception as e:
            print(f"Ошибка при удалении сообщения с содержанием: {e}")

    # Настройки пагинации
    items_per_page = 30  # Количество кнопок на странице
    total_pages = (len(media) + items_per_page - 1) // items_per_page  # Общее количество страниц
    current_page = user_data[user_id].get('current_page', 0)  # Текущая страница

    # Ограничиваем текущую страницу
    current_page = max(0, min(current_page, total_pages - 1))
    
    # Создаем новый список кнопок для текущей страницы
    keyboard = []
    image_counter = 1  # Счётчик для изображений
    start_idx = current_page * items_per_page
    end_idx = min(start_idx + items_per_page, len(media))

    for idx in range(start_idx, end_idx):
        item = media[idx]
        if item['type'] == 'text':
            text = item['content']
            if isinstance(text, dict) and 'children' in text:
                text = ''.join(child['children'][0] for child in text['children'] if isinstance(child, dict) and 'children' in child)
            preview_text = (text[:12] + '...') if len(text) > 12 else text
        else:
            preview_text = f"{image_counter} изображение"
            image_counter += 1
        
        keyboard.append([
            InlineKeyboardButton(text=str(preview_text), callback_data=f"preview_{idx}"),
            InlineKeyboardButton(text="Редактировать", callback_data=f"edit_{idx}"),
            InlineKeyboardButton(text="Удалить", callback_data=f"delete_{idx}"),
        ])

    # Добавляем кнопки навигации, если это не первая страница
    if current_page > 0:
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data='page_down')])
    
    # Добавляем кнопки навигации, если это не последняя страница
    if current_page < total_pages - 1:
        keyboard.append([InlineKeyboardButton("Вперёд ➡️", callback_data='page_up')])
    
    keyboard.append([InlineKeyboardButton("🌌 Предпросмотр 🌌", callback_data='preview_article')])
    keyboard.append([InlineKeyboardButton("Помощь и разметка", callback_data='help_command')])
    keyboard.append([InlineKeyboardButton("Найти автора, аниме или проверить на ИИ", callback_data='start_search')])
    keyboard.append([InlineKeyboardButton("🌠 К Завершению Публикации 🌠", callback_data='create_article')])
    # Отправляем новое сообщение и сохраняем его ID
    sent_message = await (query.message if update.callback_query else update.message).reply_text(
        "Выберите фрагмент для редактирования или удаления:", 
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    # Сохраняем ID нового сообщения с кнопками
    user_data[user_id]['last_content_message_id'] = sent_message.message_id
    user_data[user_id]['current_page'] = current_page  # Сохраняем текущую страницу



async def handle_edit_delete(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    action, index = query.data.split('_')
    index = int(index)

    media = user_data[user_id].get('media', [])

    # Проверяем, существует ли фрагмент с таким индексом
    if index >= len(media):
        await query.message.reply_text("🚫 Ошибка: указанный индекс недействителен.")
        return

    if action == 'edit':
        # Если тип контента — изображение, предлагаем отправить новое изображение
        if media[index]['type'] == 'image':
            context.user_data['editing_index'] = index
            await query.message.reply_text("Пожалуйста, отправьте новое изображение или текст:")
            return ASKING_FOR_IMAGE  # Переход к ожиданию нового изображения
        # Если тип контента — текст, предлагаем ввести новый текст
        elif media[index]['type'] == 'text':
            context.user_data['editing_index'] = index
            await query.message.reply_text("Пожалуйста, отправьте новое изображение или текст:")
            return EDITING_FRAGMENT  # Переходим в состояние редактирования текста

    elif action == 'delete':
        if index < len(media):
            media.pop(index)
            user_data[user_id]['media'] = media  # Сохраняем изменения

            # Обновляем кнопки
# Количество кнопок на одной странице
            PAGE_SIZE = 30

            # Получаем текущую страницу из user_data (по умолчанию 1)
            if 'page' not in user_data[user_id]:
                user_data[user_id]['page'] = 1
            current_page = user_data[user_id]['page']

            # Обновляем кнопки
            keyboard = []
            image_counter = 1  # Счётчик для изображений

            # Подсчёт общего количества элементов
            total_items = len(media)
            total_pages = (total_items + PAGE_SIZE - 1) // PAGE_SIZE  # Рассчитываем количество страниц

            # Показ элементов только для текущей страницы
            start_idx = (current_page - 1) * PAGE_SIZE
            end_idx = start_idx + PAGE_SIZE

            for idx, item in enumerate(media[start_idx:end_idx], start=start_idx):
                if item['type'] == 'text':
                    text = item['content']
                    
                    # Извлечение текста, если нужно
                    if isinstance(text, dict) and 'children' in text:
                        text = ''.join(child['children'][0] for child in text['children'] if isinstance(child, dict) and 'children' in child)
                    
                    preview_text = (text[:12] + '...') if len(text) > 12 else text
                else:  # Если элемент — это изображение
                    preview_text = f"{image_counter} изображение"  # Нумерация только для изображений
                    image_counter += 1  # Увеличиваем счётчик только для изображений
                
                # Добавляем кнопки для текущей страницы
                keyboard.append([
                    InlineKeyboardButton(text=str(preview_text), callback_data=f"preview_{idx}"),
                    InlineKeyboardButton(text="Редактировать", callback_data=f"edit_{idx}"),
                    InlineKeyboardButton(text="Удалить", callback_data=f"delete_{idx}"),
                ])

            # Добавляем кнопки для переключения страниц
            navigation_buttons = []
            if current_page > 1:
                navigation_buttons.append(InlineKeyboardButton("⬆️ Предыдущая страница", callback_data=f"prev_page_{current_page - 1}"))
            if current_page < total_pages:
                navigation_buttons.append(InlineKeyboardButton("⬇️ Следующая страница", callback_data=f"next_page_{current_page + 1}"))

            if navigation_buttons:
                keyboard.append(navigation_buttons)

            # Добавляем кнопку предпросмотра
            keyboard.append([InlineKeyboardButton("🌌 Предпросмотр 🌌", callback_data='preview_article')])
            keyboard.append([InlineKeyboardButton("Помощь и разметка", callback_data='help_command')])
            keyboard.append([InlineKeyboardButton("Найти автора, аниме или проверить на ИИ", callback_data='start_search')])
            keyboard.append([InlineKeyboardButton("🌠 К Завершению Публикации 🌠", callback_data='create_article')])

            # Отправляем новое сообщение с обновлённым списком кнопок
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_reply_markup(reply_markup=reply_markup)  # Обновляем клавиатуру

            await query.message.reply_text("✅ Фрагмент удалён.")
        return





async def handle_new_text(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    index = context.user_data['editing_index']
    media = user_data[user_id].get('media', [])

    # Убедимся, что индекс действителен
    if index >= 0 and index < len(media):
        # Если редактируемый элемент — это текст
        if media[index]['type'] == 'text':
            # Обновляем текст
            formatted_text = apply_markup(update.message.text)
            media[index] = {  # Обновляем существующий текст
                'type': 'text',
                'content': formatted_text
            }
            user_data[user_id]['media'] = media  # Сохраняем изменения

            # Удаляем предыдущее сообщение с кнопками содержания статьи
            if 'last_content_message_id' in user_data[user_id]:
                try:
                    await context.bot.delete_message(
                        chat_id=update.message.chat_id, 
                        message_id=user_data[user_id]['last_content_message_id']
                    )
                except Exception as e:
                    print(f"Ошибка при удалении сообщения с содержанием: {e}")

            # Настройки пагинации
            items_per_page = 30  # Количество кнопок на странице
            total_pages = (len(media) + items_per_page - 1) // items_per_page  # Общее количество страниц
            current_page = user_data[user_id].get('current_page', 0)  # Текущая страница

            # Ограничиваем текущую страницу
            current_page = max(0, min(current_page, total_pages - 1))


            # Создаём новый список кнопок для содержания статьи
    # Создаем новый список кнопок для текущей страницы
            keyboard = []
            image_counter = 1  # Счётчик для изображений
            start_idx = current_page * items_per_page
            end_idx = min(start_idx + items_per_page, len(media))

            for idx, item in enumerate(media):
                item = media[idx]
                if item['type'] == 'text':
                    text = item['content']
                    
                    # Извлечение текста, если нужно
                    if isinstance(text, dict) and 'children' in text:
                        text = ''.join(child['children'][0] for child in text['children'] if isinstance(child, dict) and 'children' in child)
                    
                    preview_text = (text[:12] + '...') if len(text) > 12 else text
                else:  # Если элемент — это изображение
                    preview_text = f"{image_counter} изображение"  # Нумерация только для изображений
                    image_counter += 1  # Увеличиваем счётчик только для изображений
                
                # Добавляем кнопки для предпросмотра, редактирования и удаления
                keyboard.append([
                    InlineKeyboardButton(text=str(preview_text), callback_data=f"preview_{idx}"),
                    InlineKeyboardButton(text="Редактировать", callback_data=f"edit_{idx}"),
                    InlineKeyboardButton(text="Удалить", callback_data=f"delete_{idx}"),
                ])

            if current_page > 0:
                keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data='page_down')])
            
            # Добавляем кнопки навигации, если это не последняя страница
            if current_page < total_pages - 1:
                keyboard.append([InlineKeyboardButton("Вперёд ➡️", callback_data='page_up')])
            

            keyboard.append([
                InlineKeyboardButton("🌌 Предпросмотр 🌌 ", callback_data='preview_article')
            ])    

            # Отправляем новое сообщение с обновлённым списком кнопок
            reply_markup = InlineKeyboardMarkup(keyboard)
            sent_message = await context.bot.send_message(
                chat_id=update.message.chat_id,
                text='📝 Текущее содержание статьи2:',
                reply_markup=reply_markup
            )

            # Сохраняем ID нового сообщения с кнопками
            user_data[user_id]['last_content_message_id'] = sent_message.message_id
            user_data[user_id]['current_page'] = current_page  
            # Сообщаем пользователю об успешном обновлении текста
            await context.bot.send_message(
                chat_id=update.message.chat_id,
                text='✅ Текст обновлён.',
                reply_to_message_id=update.message.message_id
            )

            # Удаляем индекс редактирования после завершения
            del context.user_data['editing_index']

            return ASKING_FOR_IMAGE
        else:
            # Ошибка, если тип редактируемого элемента не текст
            await context.bot.send_message(
                chat_id=update.message.chat_id,
                text='🚫 Ошибка: указанный элемент не является текстом.',
                reply_to_message_id=update.message.message_id
            )
            del context.user_data['editing_index']  # Удаляем индекс, если он недействителен
            return ConversationHandler.END
    else:
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text='🚫 Ошибка: указанный индекс недействителен.',
            reply_to_message_id=update.message.message_id
        )
        del context.user_data['editing_index']  # Удаляем индекс, если он недействителен
        return ConversationHandler.END


async def handle_new_image(update: Update, context: CallbackContext, index: int, media: list) -> int:
    user_id = update.message.from_user.id
    message_id = update.message.message_id

    if update.message.photo or update.message.document:
        if update.message.photo:
            await context.bot.send_message(
                chat_id=update.message.chat_id,
                text='🚫 Ошибка: пожалуйста, отправьте изображение как файл (формат JPG, PNG или .RAR для .GIF), без сжатия. Для подробностей введите /help',
                reply_to_message_id=message_id
            )
            return ASKING_FOR_IMAGE 

        elif update.message.document:
            file_name = update.message.document.file_name
            file_ext = file_name.lower().split('.')[-1]
            file = await context.bot.get_file(update.message.document.file_id)

        # Создаем временный файл для сохранения изображения
        with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{file_ext}') as tmp_file:
            file_path = tmp_file.name
            await file.download_to_drive(file_path)

        if file_ext == 'rar':
            new_file_path = f'{os.path.splitext(file_path)[0]}.gif'
            shutil.move(file_path, new_file_path)
            file_path = new_file_path
            file_name = os.path.basename(file_path)
            file_ext = 'gif'

        if file_ext in ('jpg', 'jpeg', 'png', 'gif'):
            if file_ext == 'gif':
                try:
                    image_url = await upload_image(file_path)
                    media[index] = {  # Обновляем существующее изображение
                        'type': 'image',
                        'url': image_url,
                        'caption': update.message.caption if update.message.caption else ""
                    }
                    user_data[user_id]['media'] = media  # Сохраняем изменения

                    # Удаляем предыдущее сообщение, если оно есть
                    if 'last_image_message_id' in user_data[user_id]:
                        try:
                            await context.bot.delete_message(chat_id=update.message.chat_id, message_id=user_data[user_id]['last_image_message_id'])
                        except Exception as e:
                            print(f"Ошибка при удалении сообщения: {e}")

                    # Отправляем новое сообщение
                    sent_message = await context.bot.send_message(
                        chat_id=update.message.chat_id,
                        text='✅ Изображение очень обновлено.',
                        reply_to_message_id=message_id
                    )

                    # Сохраняем ID нового сообщения
                    user_data[user_id]['last_image_message_id'] = sent_message.message_id

                    # Удаляем индекс редактирования после завершения
                    del context.user_data['editing_index']

                    return ASKING_FOR_IMAGE
                except Exception as e:
                    await context.bot.send_message(
                        chat_id=update.message.chat_id,
                        text=f'🚫 Ошибка при загрузке изображения: {str(e)}. Попробуйте снова.',
                        reply_to_message_id=message_id
                    )
                    return ConversationHandler.END

            else:
                if os.path.getsize(file_path) > 5 * 1024 * 1024:
                    compressed_path = f'{os.path.splitext(file_path)[0]}_compressed.jpg'
                    compress_image(file_path, compressed_path)
                    file_path = compressed_path

                try:
                    image_url = await upload_image(file_path)
                    media[index] = {  # Обновляем существующее изображение
                        'type': 'image',
                        'url': image_url,
                        'caption': update.message.caption if update.message.caption else ""
                    }
                    user_data[user_id]['media'] = media  # Сохраняем изменения
                    os.remove(file_path)

                    # Удаляем предыдущее сообщение, если оно есть
                    if 'last_image_message_id' in user_data[user_id]:
                        try:
                            await context.bot.delete_message(chat_id=update.message.chat_id, message_id=user_data[user_id]['last_image_message_id'])
                        except Exception as e:
                            print(f"Ошибка при удалении сообщения: {e}")

                    # Отправляем новое сообщение
                    sent_message = await context.bot.send_message(
                        chat_id=update.message.chat_id,
                        text='✅ Изображение добавлено.',
                        reply_to_message_id=message_id
                    )

                    # Удаляем предыдущее сообщение с кнопками содержания статьи, если оно существует
                    if 'last_content_message_id' in user_data[user_id]:
                        try:
                            await context.bot.delete_message(
                                chat_id=update.message.chat_id, 
                                message_id=user_data[user_id]['last_content_message_id']
                            )
                        except Exception as e:
                            print(f"Ошибка при удалении сообщения с содержанием: {e}")


                    # Настройки пагинации
                    items_per_page = 30  # Количество кнопок на странице
                    total_pages = (len(media) + items_per_page - 1) // items_per_page  # Общее количество страниц
                    current_page = user_data[user_id].get('current_page', 0)  # Текущая страница

                    # Ограничиваем текущую страницу
                    current_page = max(0, min(current_page, total_pages - 1))

                    # Создаём новый список кнопок для содержания статьи
                    keyboard = []
                    image_counter = 1  # Счётчик для изображений
                    start_idx = current_page * items_per_page
                    end_idx = min(start_idx + items_per_page, len(media))
                    for idx in range(start_idx, end_idx):
                        item = media[idx]
                        if item['type'] == 'text':
                            text = item['content']
                            
                            # Извлечение текста, если нужно
                            if isinstance(text, dict) and 'children' in text:
                                text = ''.join(child['children'][0] for child in text['children'] if isinstance(child, dict) and 'children' in child)
                            
                            preview_text = (text[:12] + '...') if len(text) > 12 else text
                        else:  # Если элемент — это изображение
                            preview_text = f"Обн изобр-ие"  # Нумерация только для изображений
                            image_counter += 1  # Увеличиваем счётчик только для изображений
                        
                        # Добавляем кнопки для предпросмотра, редактирования и удаления
                        keyboard.append([
                            InlineKeyboardButton(text=str(preview_text), callback_data=f"preview_{idx}"),
                            InlineKeyboardButton(text="Редактировать", callback_data=f"edit_{idx}"),
                            InlineKeyboardButton(text="Удалить", callback_data=f"delete_{idx}"),
                        ])

                    if current_page > 0:
                        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data='page_down')])
                    
                    # Добавляем кнопки навигации, если это не последняя страница
                    if current_page < total_pages - 1:
                        keyboard.append([InlineKeyboardButton("Вперёд ➡️", callback_data='page_up')])
                    
                    keyboard.append([
                        InlineKeyboardButton("🌌 Предпросмотр 🌌 ", callback_data='preview_article')
                    ])    

                    # Отправляем новое сообщение с обновлённым списком кнопок
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    sent_message = await context.bot.send_message(
                        chat_id=update.message.chat_id,
                        text='📝 Текущее содержание статьи1:',
                        reply_markup=reply_markup
                    )

                    # Сохраняем ID нового сообщения с кнопками
                    user_data[user_id]['last_content_message_id'] = sent_message.message_id
                    user_data[user_id]['current_page'] = current_page  

                    # Удаляем индекс редактирования после завершения
                    del context.user_data['editing_index']

                    return ASKING_FOR_IMAGE
                except Exception as e:
                    await context.bot.send_message(
                        chat_id=update.message.chat_id,
                        text=f'🚫 Ошибка при загрузке изображения: {str(e)}. Попробуйте снова.',
                        reply_to_message_id=message_id
                    )
                    return ConversationHandler.END

        else:
            await context.bot.send_message(
                chat_id=update.message.chat_id,
                text='Пожалуйста, отправьте изображение в формате JPG, PNG или .RAR для .GIF.',
                reply_to_message_id=message_id
            )
            return ASKING_FOR_IMAGE
    else:
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text='🚫 Ошибка: ожидается изображение или файл.',
            reply_to_message_id=message_id
        )
        return ConversationHandler.END




async def handle_image(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    caption = update.message.caption
    message_id = update.message.message_id

    # Проверяем, редактирует ли пользователь что-либо
    if 'editing_index' in context.user_data:
        index = context.user_data['editing_index']
        media = user_data[user_id].get('media', [])

        # Проверяем, если индекс действителен
        if 0 <= index < len(media):
            # Проверяем, если редактируем текст, и если получен текст
            if media[index]['type'] == 'text':
                # Если пользователь прислал текст, обрабатываем его как текст
                if update.message.text:
                    return await handle_new_text_from_image(update, context, index, media)

                # Если вместо текста пришло изображение
                if update.message.photo or update.message.document:
                    return await handle_new_image(update, context, index, media)

            # Проверяем, если редактируем изображение
            if media[index]['type'] == 'image':
                # Проверяем, если пользователь отправил текст вместо изображения
                if update.message.text:
                    return await handle_new_text_from_image(update, context, index, media)

                # Проверка фото
                if update.message.photo:
                    await context.bot.send_message(
                        chat_id=update.message.chat_id,
                        text='Пожалуйста, отправьте изображение как файл (формат JPG, PNG или .RAR для .GIF), без сжатия. Для подробностей введите /help',
                        reply_to_message_id=message_id
                    )
                    return ASKING_FOR_IMAGE

                elif update.message.document:
                    file_name = update.message.document.file_name
                    if file_name:  # Проверка, что файл имеет имя
                        file_ext = file_name.lower().split('.')[-1]

                        # Если не удается определить расширение, выходим
                        if not file_ext:
                            await context.bot.send_message(
                                chat_id=update.message.chat_id,
                                text='🚫 Ошибка: не удалось определить расширение файла. Пожалуйста, отправьте файл с правильным расширением.',
                                reply_to_message_id=message_id
                            )
                            return ConversationHandler.END

                        file = await context.bot.get_file(update.message.document.file_id)
                        # Скачивание и создание временного файла
                        with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{file_ext}') as tmp_file:
                            file_path = tmp_file.name
                            await file.download_to_drive(file_path)                    

                # Обработка документа

                        if file_ext == 'rar':
                            new_file_path = f'{os.path.splitext(file_path)[0]}.gif'
                            shutil.move(file_path, new_file_path)
                            file_path = new_file_path
                            file_name = os.path.basename(file_path)
                            file_ext = 'gif'

                        if file_ext in ('jpg', 'jpeg', 'png', 'gif'):
                            if file_ext == 'gif':
                                try:
                                    image_url = await upload_image(file_path)
                                    media[index] = {  # Обновляем существующее изображение
                                        'type': 'image',
                                        'url': image_url,
                                        'caption': caption if caption else ""
                                    }
                                    user_data[user_id]['media'] = media  # Сохраняем изменения

                                    # Удаляем предыдущее сообщение, если оно есть
                                    if 'last_image_message_id' in user_data[user_id]:
                                        try:
                                            await context.bot.delete_message(chat_id=update.message.chat_id, message_id=user_data[user_id]['last_image_message_id'])
                                        except Exception as e:
                                            print(f"Ошибка при удалении сообщения: {e}")

                                    # Отправляем новое сообщение
                                    sent_message = await context.bot.send_message(
                                        chat_id=update.message.chat_id,
                                        text='✅ Изображение замечательно обновлено.',
                                        reply_to_message_id=message_id
                                    )

                                    # Сохраняем ID нового сообщения
                                    user_data[user_id]['last_image_message_id'] = sent_message.message_id

                                    # Удаляем индекс редактирования после завершения
                                    del context.user_data['editing_index']

                                    return ASKING_FOR_IMAGE
                                except Exception as e:
                                    await context.bot.send_message(
                                        chat_id=update.message.chat_id,
                                        text=f'🚫 Ошибка при загрузке изображения: {str(e)}. Попробуйте снова.',
                                        reply_to_message_id=message_id
                                    )
                                    return ConversationHandler.END
                            else:
                                if os.path.getsize(file_path) > 5 * 1024 * 1024:
                                    compressed_path = f'{os.path.splitext(file_path)[0]}_compressed.jpg'
                                    compress_image(file_path, compressed_path)
                                    file_path = compressed_path

                                try:




                                    image_url = await upload_image(file_path)
                                    media[index] = {  # Обновляем существующее изображение
                                        'type': 'image',
                                        'url': image_url,
                                        'caption': caption if caption else ""
                                    }
                                    user_data[user_id]['media'] = media # Сохраняем изменения
                                    os.remove(file_path)

                                    # Удаляем предыдущее сообщение, если оно есть
                                    if 'last_image_message_id' in user_data[user_id]:
                                        try:
                                            await context.bot.delete_message(chat_id=update.message.chat_id, message_id=user_data[user_id]['last_image_message_id'])
                                        except Exception as e:
                                            print(f"Ошибка при удалении сообщения: {e}")

                                    # Отправляем новое сообщение
                                    keyboard = []
                                    image_counter = 1  # Счётчик для изображений

                                    # Настройки пагинации
                                    items_per_page = 30  # Количество кнопок на странице
                                    total_pages = (len(media) + items_per_page - 1) // items_per_page  # Общее количество страниц
                                    current_page = user_data[user_id].get('current_page', 0)  # Текущая страница

                                    # Ограничиваем текущую страницу
                                    current_page = max(0, min(current_page, total_pages - 1))

                                    # Создаём новый список кнопок для содержания статьи
                                    start_idx = current_page * items_per_page
                                    end_idx = min(start_idx + items_per_page, len(media))
                                    for idx in range(start_idx, end_idx):
                                        item = media[idx]
                                        if item['type'] == 'text':
                                            text = item['content']
                                            
                                            # Извлечение текста, если нужно
                                            if isinstance(text, dict) and 'children' in text:
                                                text = ''.join(child['children'][0] for child in text['children'] if isinstance(child, dict) and 'children' in child)
                                            
                                            preview_text = (text[:12] + '...') if len(text) > 12 else text
                                        else:  # Если элемент — это изображение
                                            preview_text = f"{image_counter} изображение"  # Нумерация только для изображений
                                            image_counter += 1  # Увеличиваем счётчик только для изображений
                                        
                                        # Добавляем кнопки для предпросмотра, редактирования и удаления
                                        keyboard.append([
                                            InlineKeyboardButton(text=str(preview_text), callback_data=f"preview_{idx}"),
                                            InlineKeyboardButton(text="Редактировать", callback_data=f"edit_{idx}"),
                                            InlineKeyboardButton(text="Удалить", callback_data=f"delete_{idx}"),
                                        ])

                                    # Добавляем кнопки навигации, если это не первая страница
                                    if current_page > 0:
                                        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data='page_down')])

                                    # Добавляем кнопки навигации, если это не последняя страница
                                    if current_page < total_pages - 1:
                                        keyboard.append([InlineKeyboardButton("Вперёд ➡️", callback_data='page_up')])

                                    keyboard.append([InlineKeyboardButton("🌌 Предпросмотр 🌌", callback_data='preview_article')])
                                    keyboard.append([InlineKeyboardButton("Помощь и разметка", callback_data='help_command')])
                                    keyboard.append([InlineKeyboardButton("Найти автора, аниме или проверить на ИИ", callback_data='start_search')])
                                    keyboard.append([InlineKeyboardButton("🌠 К Завершению Публикации 🌠", callback_data='create_article')])


                                    # Отправляем новое сообщение с обновлённым списком кнопок
                                    reply_markup = InlineKeyboardMarkup(keyboard)
                                    sent_message_with_buttons = await context.bot.send_message(
                                        chat_id=update.message.chat_id,
                                        text='✅ Изображение Заменено. \n📝 Текущее содержание статьи:',
                                        reply_markup=reply_markup
                                    )

                                    # Сохраняем ID нового сообщения с кнопками
                                    user_data[user_id]['last_image_message_id'] = sent_message_with_buttons.message_id
                                    user_data[user_id]['current_page'] = current_page

                                    # Удаляем индекс редактирования после завершения
                                    del context.user_data['editing_index']

                                    return ASKING_FOR_IMAGE
                                except Exception as e:
                                    await context.bot.send_message(
                                        chat_id=update.message.chat_id,
                                        text=f'🚫 Ошибка при загрузке изображения: {str(e)}. Попробуйте снова.',
                                        reply_to_message_id=message_id
                                    )
                                    return ConversationHandler.END

                        else:
                            await context.bot.send_message(
                                chat_id=update.message.chat_id,
                                text='Пожалуйста, отправьте изображение в формате JPG, PNG или .RAR для .GIF.',
                                reply_to_message_id=message_id
                            )
                            return ASKING_FOR_IMAGE

                    elif media[index]['type'] == 'text':
                        # Если редактируем текст, вызываем обработчик текста
                        return await handle_new_text(update, context)
                    else:
                        await context.bot.send_message(
                            chat_id=update.message.chat_id,
                            text='🚫 Ошибка: указанный элемент имеет недопустимый тип.',
                            reply_to_message_id=message_id
                        )
                        del context.user_data['editing_index']
                        return ConversationHandler.END
                else:
                    await context.bot.send_message(
                        chat_id=update.message.chat_id,
                        text='🚫 Ошибка: указанный индекс изображения недействителен.',
                        reply_to_message_id=message_id
                    )
                    del context.user_data['editing_index']  # Удаляем индекс, если он недействителен
                    return ConversationHandler.END

    # Если не в состоянии редактирования, продолжаем обычную обработку изображений
    if user_id in user_data and user_data[user_id]['status'] == 'awaiting_image':
        if update.message.photo:
            await context.bot.send_message(
                chat_id=update.message.chat_id,
                text='Пожалуйста, отправьте изображение как файл (формат JPG, PNG или .RAR для .GIF), без сжатия. Для подробностей введите /help',
                reply_to_message_id=message_id
            )
            return ASKING_FOR_IMAGE

        elif update.message.document:
            file_name = update.message.document.file_name
            file_ext = file_name.lower().split('.')[-1]
            file = await context.bot.get_file(update.message.document.file_id)

            with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{file_ext}') as tmp_file:
                file_path = tmp_file.name
                await file.download_to_drive(file_path)

            if file_ext == 'rar':
                new_file_path = f'{os.path.splitext(file_path)[0]}.gif'
                shutil.move(file_path, new_file_path)
                file_path = new_file_path
                file_name = os.path.basename(file_path)
                file_ext = 'gif'

            if file_ext in ('jpg', 'jpeg', 'png', 'gif'):
                if file_ext == 'gif':
                    try:
                        image_url = await upload_image(file_path)
                        if 'media' not in user_data[user_id]:
                            user_data[user_id]['media'] = []
                        user_data[user_id]['media'].append({
                            'type': 'image',
                            'url': image_url,
                            'caption': caption if caption else ""
                        })

                        # Удаляем предыдущее сообщение, если оно есть
                        if 'last_image_message_id' in user_data[user_id]:
                            try:
                                await context.bot.delete_message(chat_id=update.message.chat_id, message_id=user_data[user_id]['last_image_message_id'])
                            except Exception as e:
                                print(f"Ошибка при удалении сообщения: {e}")

                        keyboard = [
                            [InlineKeyboardButton("‼️Сброс Публикации и Возврат к Началу‼️", callback_data='restart')],
                            [InlineKeyboardButton("📝 Проверить последний текст на ошибки 📝", callback_data='check_text')],  # Новая кнопка                           
                            [InlineKeyboardButton("Удалить последний элемент", callback_data='delete_last')],
                            [InlineKeyboardButton("Предпросмотр", callback_data='preview_article')],
                            [InlineKeyboardButton("Редактировать", callback_data='edit_article')],
                            [InlineKeyboardButton("Помощь и разметка", callback_data='help_command')],
                            [InlineKeyboardButton("🌠 К Завершению Публикации 🌠", callback_data='create_article')]
                        ]

                        reply_markup = InlineKeyboardMarkup(keyboard)                                

                        if 'image_counter' not in user_data[user_id]:
                            user_data[user_id]['image_counter'] = 0

                        # Когда бот получает изображение, увеличиваем счётчик
                        user_data[user_id]['image_counter'] += 1
                        image_counter = user_data[user_id]['image_counter']

                        # Используем счётчик в сообщении
                        image_text = "изображение" if image_counter == 1 else "изображения"
                        sent_message = await context.bot.send_message(
                            chat_id=update.message.chat_id,
                            text=f'✅ {image_counter} {image_text} добавлено.\n\n Дождитесь загрузки остальных изображений, если их больше чем одно. Затем вы можете продолжить присылать изображения или текст.\n\n Так же вы можете использовать следующие команды:',
                            reply_to_message_id=message_id,
                            reply_markup=reply_markup
                        )

                        # Сохраняем ID нового сообщения
                        user_data[user_id]['last_image_message_id'] = sent_message.message_id

                        return ASKING_FOR_IMAGE
                    except Exception as e:
                        await context.bot.send_message(
                            chat_id=update.message.chat_id,
                            text=f'🚫Ошибка при загрузке изображения: {str(e)}. Можете попробовать прислать файл ещё раз через некоторое время или нажать /restart',
                            reply_to_message_id=message_id
                        )
                        return ConversationHandler.END
                else:
                    if os.path.getsize(file_path) > 5 * 1024 * 1024:
                        compressed_path = f'{os.path.splitext(file_path)[0]}_compressed.jpg'
                        compress_image(file_path, compressed_path)
                        file_path = compressed_path

                    try:
                        image_url = await upload_image(file_path)
                        if 'media' not in user_data[user_id]:
                            user_data[user_id]['media'] = []
                        user_data[user_id]['media'].append({
                            'type': 'image',
                            'url': image_url,
                            'caption': caption if caption else ""
                        })
                        os.remove(file_path)

                        # Удаляем предыдущее сообщение, если оно есть
                        if 'last_image_message_id' in user_data[user_id]:
                            try:
                                await context.bot.delete_message(chat_id=update.message.chat_id, message_id=user_data[user_id]['last_image_message_id'])
                            except Exception as e:
                                print(f"Ошибка при удалении сообщения: {e}")

                        keyboard = [
                            [InlineKeyboardButton("‼️Сброс Публикации и Возврат к Началу‼️", callback_data='restart')],
                            [InlineKeyboardButton("📝 Проверить последний текст на ошибки 📝", callback_data='check_text')],  # Новая кнопка                           
                            [InlineKeyboardButton("Удалить последний элемент", callback_data='delete_last')],
                            [InlineKeyboardButton("Предпросмотр", callback_data='preview_article')],
                            [InlineKeyboardButton("Редактировать", callback_data='edit_article')],
                            [InlineKeyboardButton("Помощь и разметка", callback_data='help_command')],
                            [InlineKeyboardButton("🌠 К Завершению Публикации 🌠", callback_data='create_article')]
                        ]

                        reply_markup = InlineKeyboardMarkup(keyboard) 


                        if 'image_counter' not in user_data[user_id]:
                            user_data[user_id]['image_counter'] = 0

                        # Когда бот получает изображение, увеличиваем счётчик
                        user_data[user_id]['image_counter'] += 1
                        image_counter = user_data[user_id]['image_counter']

                        # Используем счётчик в сообщении
                        image_text = "изображение" if image_counter == 1 else "изображения"
                        sent_message = await context.bot.send_message(
                            chat_id=update.message.chat_id,
                            text=f'✅ {image_counter} {image_text} добавлено.\n\n Дождитесь загрузки остальных изображений, если их больше чем одно. Затем вы можете продолжить присылать изображения или текст.\n\n Так же вы можете использовать следующие команды:',
                            reply_to_message_id=message_id,
                            reply_markup=reply_markup
                        )

                        # Сохраняем ID нового сообщения
                        user_data[user_id]['last_image_message_id'] = sent_message.message_id

                        return ASKING_FOR_IMAGE
                    except Exception as e:
                        await context.bot.send_message(
                            chat_id=update.message.chat_id,
                            text=f'🚫Ошибка при загрузке изображения: {str(e)}. Можете попробовать прислать файл ещё раз через некоторое время или нажать /restart',
                            reply_to_message_id=message_id
                        )
                        return ConversationHandler.END

            else:
                await context.bot.send_message(
                    chat_id=update.message.chat_id,
                    text='Пожалуйста, отправьте изображение в формате JPG, PNG или .RAR для .GIF.',
                    reply_to_message_id=message_id
                )
                return ASKING_FOR_IMAGE

        elif update.message.text:
            return await handle_text(update, context)

        else:
            await context.bot.send_message(
                chat_id=update.message.chat_id,
                text='Пожалуйста, отправьте изображение как файл (формат JPG, PNG или .RAR для .GIF), без сжатия, или текст.',
                reply_to_message_id=message_id
            )
            return ASKING_FOR_IMAGE

    else:
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text='🚫Ошибка: данные не найдены. Попробуйте отправить снова. Или нажмите /restart',
            reply_to_message_id=message_id
        )
        return ConversationHandler.END


        
# Функция для обработки текстовых сообщений
async def handle_text(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    message_text = update.message.text

    # Если не в режиме редактирования, продолжаем обычную обработку текстовых сообщений
    user_data_entry = user_data.get(user_id, {})

    # Проверяем статус пользователя
    if user_data_entry.get('status') == 'awaiting_image':
        # Обработка текстовых сообщений с разметкой
        formatted_text = apply_markup(message_text)

        # Проверка наличия раздела 'media' и добавление текста
        if 'media' not in user_data_entry:
            user_data_entry['media'] = []

        user_data_entry['media'].append({'type': 'text', 'content': formatted_text})

        # Сохраняем обновлённые данные
        user_data[user_id] = user_data_entry

        # Удаление предыдущего сообщения, если оно существует
        if 'last_message_id' in user_data_entry:
            try:
                await context.bot.delete_message(
                    chat_id=update.message.chat_id, 
                    message_id=user_data_entry['last_message_id']
                )
            except Exception as e:
                print(f"Ошибка при удалении сообщения: {e}")

        # Отправляем новое сообщение


        keyboard = [
            [InlineKeyboardButton("‼️Сброс Публикации и Возврат к Началу‼️", callback_data='restart')],
            [InlineKeyboardButton("📝 Проверить последний текст на ошибки 📝", callback_data='check_text')],  # Новая кнопка
            [InlineKeyboardButton("Удалить последний элемент", callback_data='delete_last')],
            [InlineKeyboardButton("Предпросмотр", callback_data='preview_article')],
            [InlineKeyboardButton("Редактировать", callback_data='edit_article')],
            [InlineKeyboardButton("Помощь и разметка", callback_data='help_command')],
            [InlineKeyboardButton("🌠 К Завершению Публикации 🌠", callback_data='create_article')],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard) 

        if 'text_counter' not in user_data[user_id]:
            user_data[user_id]['text_counter'] = 0

        # Когда бот получает текст, увеличиваем счётчик
        user_data[user_id]['text_counter'] += 1
        text_counter = user_data[user_id]['text_counter']

        # Используем счётчик текста в сообщении
        text_message = "текст" if text_counter == 1 else "текста"
        sent_message = await update.message.reply_text(
            f'✅ {text_counter} {text_message} успешно добавлено. Вы можете отправить ещё текст или изображения.\n\n'
            'Либо воспользоваться одной из команд ниже:\n',
            reply_to_message_id=update.message.message_id,
            reply_markup=reply_markup  # Добавляем клавиатуру с кнопкой
        )
        # Сохраняем ID нового сообщения
        user_data_entry['last_message_id'] = sent_message.message_id
        user_data[user_id] = user_data_entry

        return ASKING_FOR_IMAGE
    else:
        await update.message.reply_text('🚫 Ошибка: данные не найдены. Попробуйте отправить снова. Или нажмите /restart')
        return ConversationHandler.END

def extract_text_from_json(data):
    if isinstance(data, dict):
        # Если текущий элемент - это словарь, рекурсивно обрабатываем его ключ 'children'
        return ''.join(extract_text_from_json(child) for child in data.get('children', []))
    elif isinstance(data, list):
        # Если текущий элемент - это список, обрабатываем каждый элемент списка
        return ''.join(extract_text_from_json(item) for item in data)
    elif isinstance(data, str):
        # Если текущий элемент - это строка, возвращаем её
        return data
    return ''

async def handle_check_text(update, context):
    user_id = update.effective_user.id
    user_data_entry = user_data.get(user_id, {})

    # Проверяем, есть ли текстовые сообщения в данных пользователя
    if 'media' in user_data_entry and user_data_entry['media']:
        # Ищем последний введенный текст
        last_text_entry = next((entry['content'] for entry in reversed(user_data_entry['media']) if entry['type'] == 'text'), None)

        # Проверяем, извлечен ли последний текст корректно
        if last_text_entry:
            # Извлекаем текстовое содержание из JSON-объекта
            plain_text = extract_text_from_json(last_text_entry)

            # Логируем содержание plain_text
            logging.info(f"Extracted text for user {user_id}: {plain_text}")

            # Формируем запрос для Gemini с текстом для проверки
            query = (
                f"Проверь данный текст в первую очередь на орфографические и пунктуационные ошибки. "
                f"Сначала перечисли самые грубые и очевидные ошибки, такие как пропущенные буквы или очевидные опечатки "
                f"(например, 'даска' вместо 'доска'), перечисли их, либо напиши что явных ошибок в тексте не найдено "
                f"Затем представь полностью исправленный вариант текста. "
                f"В конце добавь любые менее значительные рекомендации по улучшению текста, если они есть. "
                f"Если ошибок не найдено и замечаний нет, укажи, что текст полностью корректен.\n\n{plain_text}"
)            
            # Логируем сформированный запрос
            logging.info(f"Generated query for Gemini: {query}")

            # Отправка запроса в модель Gemini для проверки
            response = generate_gemini_response(user_id, query=query, use_context=False)

            # Проверяем, что модель вернула ответ, и отправляем его пользователю
            await update.callback_query.message.reply_text(response or "Не удалось выполнить проверку текста.")
        else:
            # Ответ пользователю, если текст не найден
            await update.callback_query.answer("Последний текст не найден.")
    else:
        # Ответ пользователю, если нет текстовых сообщений
        await update.callback_query.answer("Тексты для проверки отсутствуют.")


async def handle_new_text_from_image(update: Update, context: CallbackContext, index, media) -> int:
    user_id = update.message.from_user.id
    message_text = update.message.text

    # Проверка наличия данных пользователя и медиа
    if user_id not in user_data or 'media' not in user_data[user_id]:
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text='🚫 Ошибка: данные пользователя не найдены. Попробуйте снова.',
            reply_to_message_id=update.message.message_id
        )
        return ConversationHandler.END

    # Проверка корректности индекса
    if not (0 <= index < len(media)):
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text='🚫 Ошибка: недопустимый индекс редактируемого элемента.',
            reply_to_message_id=update.message.message_id
        )
        return ConversationHandler.END

    # Применение разметки к тексту
    formatted_text = apply_markup(message_text)

    # Замена изображения на текст в media
    media[index] = {
        'type': 'text',
        'content': formatted_text
    }
    user_data[user_id]['media'] = media  # Обновляем данные пользователя

    # Уведомление пользователя
    await context.bot.send_message(
        chat_id=update.message.chat_id,
        text='✅ Содержание изменено.',
        reply_to_message_id=update.message.message_id
    )

    # Удаляем индекс редактирования только после успешной замены
    del context.user_data['editing_index']

    # Удаляем предыдущее сообщение с кнопками содержания статьи, если оно существует
    if 'last_content_message_id' in user_data[user_id]:
        try:
            await context.bot.delete_message(
                chat_id=update.message.chat_id, 
                message_id=user_data[user_id]['last_content_message_id']
            )
        except Exception as e:
            print(f"Ошибка при удалении сообщения с содержанием: {e}")

        # Настройки пагинации
    items_per_page = 30  # Количество кнопок на странице
    total_pages = (len(media) + items_per_page - 1) // items_per_page  # Общее количество страниц
    current_page = user_data[user_id].get('current_page', 0)  # Текущая страница

    # Ограничиваем текущую страницу
    current_page = max(0, min(current_page, total_pages - 1))        

    # Создаём новый список кнопок для содержания статьи
    keyboard = []
    image_counter = 1  # Счётчик для изображений
    start_idx = current_page * items_per_page
    end_idx = min(start_idx + items_per_page, len(media))
    for idx in range(start_idx, end_idx):
        item = media[idx]
        if item['type'] == 'text':
            text = item['content']
            
            # Извлечение текста, если нужно
            if isinstance(text, dict) and 'children' in text:
                text = ''.join(child['children'][0] for child in text['children'] if isinstance(child, dict) and 'children' in child)
            
            preview_text = (text[:12] + '...') if len(text) > 12 else text
        else:  # Если элемент — это изображение
            preview_text = f"{image_counter} изображение"  # Нумерация только для изображений
            image_counter += 1  # Увеличиваем счётчик только для изображений
        
        # Добавляем кнопки для предпросмотра, редактирования и удаления
        keyboard.append([
            InlineKeyboardButton(text=str(preview_text), callback_data=f"preview_{idx}"),
            InlineKeyboardButton(text="Редактировать", callback_data=f"edit_{idx}"),
            InlineKeyboardButton(text="Удалить", callback_data=f"delete_{idx}"),
        ])
    # Добавляем кнопки навигации, если это не первая страница
    if current_page > 0:
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data='page_down')])
    
    # Добавляем кнопки навигации, если это не последняя страница
    if current_page < total_pages - 1:
        keyboard.append([InlineKeyboardButton("Вперёд ➡️", callback_data='page_up')])
    
    keyboard.append([InlineKeyboardButton("🌌 Предпросмотр 🌌", callback_data='preview_article')])
    keyboard.append([InlineKeyboardButton("Помощь и разметка", callback_data='help_command')])
    keyboard.append([InlineKeyboardButton("Найти автора, аниме или проверить на ИИ", callback_data='start_search')])
    keyboard.append([InlineKeyboardButton("🌠 К Завершению Публикации 🌠", callback_data='create_article')])
    # Отправляем новое сообщение с обновлённым списком кнопок
    reply_markup = InlineKeyboardMarkup(keyboard)
    sent_message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text='📝 Текущее содержание статьи3:',
        reply_markup=reply_markup
    )

    # Сохраняем ID нового сообщения с кнопками
    user_data[user_id]['last_content_message_id'] = sent_message.message_id
    user_data[user_id]['current_page'] = current_page 

    del context.user_data['editing_index']

    return ASKING_FOR_IMAGE
        


@retry(wait=wait_fixed(2), stop=stop_after_attempt(3))
def make_request(url, data):
    response = requests.post(url, json=data, timeout=30)
    response.raise_for_status()
    return response.json()

# Функция для отправки медиа-сообщений с повторными попытками
@retry(wait=wait_fixed(2), stop=stop_after_attempt(3))
async def send_media_with_retries(update, media_group, caption):
    try:
        await update.message.reply_text(caption, parse_mode='HTML')
        await update.message.reply_media_group(media=media_group)
    except Exception as e:
        logger.error(f"Failed to send media group: {e}")
        raise  # Перекидываем исключение для повторных попыток

async def send_media_group(update, media_group, caption):
    if not media_group:
        logger.error("Media group is empty")
        return
    try:
        await update.message.reply_text(caption, parse_mode='HTML')
        await update.message.reply_media_group(media=media_group)
    except Exception as e:
        logger.error(f"Failed to send media group: {e}")
        raise

async def send_media_group_with_retries(update, media_group, max_retries=3, delay=2):
    retries = 0
    # Определяем, является ли событие сообщением или callback-запросом
    if update.message:
        message_to_reply = update.message
    elif update.callback_query:
        message_to_reply = update.callback_query.message
    else:
        return False  # Не удалось определить источник

    while retries < max_retries:
        try:
            await message_to_reply.reply_media_group(media_group)
            return True  # Успешная отправка
        except Exception as e:
            logger.error(f"Failed to send media group: {e}")
            retries += 1
            if retries < max_retries:
                logger.info(f"Retrying in {delay} seconds... (Attempt {retries}/{max_retries})")
                await asyncio.sleep(delay)
    return False  # Если все попытки не удались


# Метод для отправки одного изображения с повторными попытками и задержкой
async def send_photo_with_retries(update, photo_url, caption, parse_mode, reply_markup=None, max_retries=3, delay=2):
    retries = 0
    # Определяем, является ли событие сообщением или callback-запросом
    if update.message:
        message_to_reply = update.message
    elif update.callback_query:
        message_to_reply = update.callback_query.message
    else:
        return False  # Не удалось определить источник

    while retries < max_retries:
        try:
            await message_to_reply.reply_photo(
                photo=photo_url,
                caption=caption,
                parse_mode=parse_mode,
                reply_markup=reply_markup  # Добавляем возможность передать клавиатуру с кнопками
            )
            return True  # Успешная отправка
        except Exception as e:
            logger.error(f"Failed to send photo: {e}")
            retries += 1
            if retries < max_retries:
                logger.info(f"Retrying in {delay} seconds... (Attempt {retries}/{max_retries})")
                await asyncio.sleep(delay)
    return False  # Если все попытки не удались



async def delete_last(update: Update, context: CallbackContext) -> None:
    # Определяем, откуда пришёл запрос - через команду или через кнопку
    if update.message:  # Если это сообщение
        user_id = update.message.from_user.id
        chat_id = update.message.chat_id
        message_id = update.message.message_id
    elif update.callback_query:  # Если это callback через кнопку
        user_id = update.callback_query.from_user.id
        chat_id = update.callback_query.message.chat_id
        message_id = update.callback_query.message.message_id
    else:
        return  # Если это что-то другое, то ничего не делаем

    if user_id in user_data and 'media' in user_data[user_id]:
        if user_data[user_id]['media']:
            last_item = user_data[user_id]['media'].pop()  # Удаляем последний элемент
            item_type = last_item['type']
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"Удалён последний элемент типа: {item_type}\n\nДля предпросмотра введите команду /preview",
                reply_to_message_id=message_id
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Ваша статья пуста. Нет элементов для удаления.",
                reply_to_message_id=message_id
            )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text="У вас нет активной статьи для редактирования. Используйте /start для начала.",
            reply_to_message_id=message_id
        )



from telegram import InlineKeyboardButton, InlineKeyboardMarkup

async def preview_article(update: Update, context: CallbackContext) -> None:
    # Проверяем, вызвано ли через сообщение или инлайн-кнопку
    if update.message:
        user_id = update.message.from_user.id
    elif update.callback_query:
        user_id = update.callback_query.from_user.id
    else:
        return

    if user_id in user_data:
        try:
            author_name = "Anemone"
            author_link = "https://t.me/anemonn"
            artist_link = user_data[user_id].get('artist_link', '')
            media = user_data[user_id].get('media', [])
            title = user_data[user_id].get('title', 'Предпросмотр статьи')

            # Создаём контент для страницы
            content = [{'tag': 'p', 'children': [{'tag': 'a', 'attrs': {'href': artist_link}, 'children': [artist_link]}]}]

            # Добавление изображений с разделителями
            for index, item in enumerate(media):
                if item['type'] == 'text':
                    content.append({'tag': 'p', 'children': [item['content']]})
                elif item['type'] == 'image':
                    # Создаем фигуру с изображением и подписью
                    figure_content = [{'tag': 'img', 'attrs': {'src': item['url']}}]
                    if item.get('caption'):
                        figure_content.append({'tag': 'figcaption', 'children': [item['caption']]})

                    content.append({'tag': 'figure', 'children': figure_content})

                    # Добавление разделителя после изображения, если это не последнее изображение
                    if index < len(media) - 1:
                        content.append({'tag': 'hr'})

            # Создание статьи в Telegra.ph
            response = requests.post('https://api.telegra.ph/createPage', json={
                'access_token': TELEGRAPH_TOKEN,
                'title': title,
                'author_name': author_name,
                'author_url': author_link,
                'content': content
            })
            response.raise_for_status()
            response_json = response.json()

            if response_json.get('ok'):
                preview_url = f"https://telegra.ph/{response_json['result']['path']}"

                # Создание кнопки
                keyboard = [[InlineKeyboardButton("🌠 К Завершению Публикации 🌠", callback_data='create_article')]]
                reply_markup = InlineKeyboardMarkup(keyboard)

                # Отправляем предпросмотр пользователю
                if update.message:
                    await update.message.reply_text(f'Предпросмотр статьи: {preview_url}', reply_markup=reply_markup)
                elif update.callback_query:
                    await update.callback_query.message.reply_text(f'Предпросмотр статьи: {preview_url}', reply_markup=reply_markup)
            else:
                if update.message:
                    await update.message.reply_text('Ошибка при создании предпросмотра статьи.')
                elif update.callback_query:
                    await update.callback_query.message.reply_text('Ошибка при создании предпросмотра статьи.')

        except requests.RequestException as e:
            if update.message:
                await update.message.reply_text(f'Ошибка при создании предпросмотра: {e}')
            elif update.callback_query:
                await update.callback_query.message.reply_text(f'Ошибка при создании предпросмотра: {e}')
    else:
        if update.message:
            await update.message.reply_text('Нет данных для предпросмотра. Начните с отправки текста или изображений.')
        elif update.callback_query:
            await update.callback_query.message.reply_text('Нет данных для предпросмотра. Начните с отправки текста или изображений.')





async def handle_preview_button(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()  # Подтверждаем нажатие

    if query.data == 'preview_article':
        await preview_article(update, context)

async def handle_delete_button(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()  # Подтверждаем нажатие

    if query.data == 'delete_last':
        await delete_last(update, context)


async def handle_help_text_button(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()  # Подтверждаем нажатие

    if query.data == 'help_command':
        await help_command(update, context)


async def handle_create_article_button(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()  # Ответ на нажатие

    # Вызываем функцию publish, которая создаёт статью
    await publish(update, context)


async def handle_restart_button(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()  # Подтверждаем нажатие

    if query.data == 'restart':
        await restart(update, context)

async def handle_edit_button(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()  # Подтверждаем нажатие

    if query.data == 'edit_article':
        await edit_article(update, context)   

# Добавьте обработчик для переключения страниц
async def handle_page_change(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    
    if query.data == 'page_down':
        user_data[user_id]['current_page'] -= 1
    elif query.data == 'page_up':
        user_data[user_id]['current_page'] += 1

    await edit_article(update, context)  # Повторно вызываем функцию редактирования


# Функция для рекурсивного поиска изображений
def count_images_in_content(content):
    image_count = 0
    for item in content:
        if isinstance(item, dict):
            if item.get('tag') == 'img':
                image_count += 1
            elif item.get('tag') == 'figure' and 'children' in item:
                # Если есть тег figure, проверяем его содержимое
                image_count += count_images_in_content(item['children'])
    return image_count

# Основная функция публикации
async def publish(update: Update, context: CallbackContext) -> None:
    # Проверяем, пришло ли событие от сообщения или от callback_query
    if update.message:
        user_id = update.message.from_user.id
        message_to_reply = update.message
    elif update.callback_query:
        user_id = update.callback_query.from_user.id
        message_to_reply = update.callback_query.message
    else:
        return  # Если ни того, ни другого нет, просто выйдем

    if user_id in user_data:
        try:
            author_name = "Anemone"
            author_link = "https://t.me/anemonn"
            artist_link = user_data[user_id]['artist_link']
            media = user_data[user_id].get('media', [])
            title = user_data[user_id].get('title', 'test')

            # Извлекаем фразу перед "Автор", если она есть
            extra_phrase = user_data[user_id].get('extra_phrase', "")
            author_name_final = user_data[user_id].get('author_name', '')

            # Формируем строку с фразой перед "Автор", если она есть
            if extra_phrase:
                author_line = f"{extra_phrase}\nАвтор: {author_name_final}"
            else:
                author_line = f"Автор: {author_name_final}"

            # Проверяем, есть ли авторское имя
            if not author_name_final:
                author_line = title  # Если это заголовок из "^...^", то используем только заголовок
            else:
                # Формируем строку с фразой перед "Автор", если она есть
                if extra_phrase:
                    author_line = f"{extra_phrase}\nАвтор: {author_name_final}"
                else:
                    author_line = f"Автор: {author_name_final}"


            # Создание статьи в Telegra.ph
            content = [
                {
                    'tag': 'p',
                    'children': [
                        {
                            'tag': 'a',
                            'attrs': {'href': artist_link},
                            'children': [artist_link]
                        }
                    ]
                }
            ]

            # Добавление изображений с разделителями
            for index, item in enumerate(media):
                if item['type'] == 'text':
                    content.append({'tag': 'p', 'children': [item['content']]})
                elif item['type'] == 'image':
                    # Создаем фигуру с изображением и подписью
                    figure_content = [
                        {'tag': 'img', 'attrs': {'src': item['url']}},
                    ]
                    if item.get('caption'):
                        figure_content.append({'tag': 'figcaption', 'children': [item['caption']]})

                    content.append({'tag': 'figure', 'children': figure_content})

                    if index < len(media) - 1:
                        content.append({'tag': 'hr'})

            content.append({'tag': 'hr'})
            content.append({
                'tag': 'i',
                'children': [f'Оригиналы доступны в браузере через меню (⋮)']
            })

            response = requests.post('https://api.telegra.ph/createPage', json={
                'access_token': TELEGRAPH_TOKEN,
                'title': title,
                'author_name': author_name,
                'author_url': author_link,
                'content': content
            })
            response.raise_for_status()
            response_json = response.json()

            if response_json.get('ok'):
                article_url = f"https://telegra.ph/{response_json['result']['path']}"

                article_response = requests.get(f'https://api.telegra.ph/getPage?access_token={TELEGRAPH_TOKEN}&path={response_json["result"]["path"]}&return_content=true')
                article_response.raise_for_status()
                article_data = article_response.json()

                image_count = count_images_in_content(content)
                logger.info(f"Number of images detected: {image_count}")

                if image_count > 1:
                    # Фильтруем только изображения, чтобы избежать смешивания с текстом
                    image_media = [item for item in media if item['type'] == 'image']
                    
                    # Разделение только изображений на группы по 10
                    media_groups = [image_media[i:i + 10] for i in range(0, len(image_media), 10)]
                    media_group_data = []
                    
                    # Для хранения информации о том, был ли добавлен текст
                    text_added = False

                    for group in media_groups:
                        media_group = []

                        for idx, item in enumerate(group):
                            caption = None
                            
                            # Если текст ещё не добавлен, добавляем подпись к первому изображению
                            if not text_added:
                                caption = f'{author_line}\n<a href="{article_url}">Оригинал</a>'
                                text_added = True

                            # Добавляем только изображения в медиа-группу
                            media_group.append(InputMediaPhoto(media=item['url'], caption=caption, parse_mode='HTML' if caption else None))
                            
                            # Запоминаем данные для последующего использования
                            media_group_data.append({
                                "file_id": item['url'],
                                "caption": caption,
                                "parse_mode": 'HTML' if caption else None
                            })

                        # Используем функцию для повторных попыток отправки медиа-группы
                        success = await send_media_group_with_retries(update, media_group)
                        if not success:
                            await message_to_reply.reply_text(f'🚫Ошибка при отправке медиа-группы.')
                            return

                        if caption:
                            await message_to_reply.reply_text(
                                f"✅ Медиагруппа отправлена с подписью.",
                                disable_web_page_preview=True
                            )

                    media_group_storage[user_id] = media_group_data



                if image_count == 1:
                    single_image = next((item for item in media if item['type'] == 'image'), None)
                    if single_image:
                        caption = f'{author_line}\n<a href="{article_url}">Оригинал</a>'
                        
                        media_group_storage[user_id] = [{
                            "file_id": single_image['url'],
                            "caption": caption,
                            "parse_mode": 'HTML'
                        }]
                        
                        # Проверяем, откуда пришел вызов - из команды или инлайн-кнопки
                        success = await send_photo_with_retries(
                            update=update,
                            photo_url=single_image['url'],
                            caption=caption,
                            parse_mode='HTML'
                        )
                        if not success:
                            await message_to_reply.reply_text('🚫Ошибка при отправке изображения. /restart')
                            return

                elif image_count == 0:
                    message_with_link = f'{author_line}\n<a href="{article_url}">Оригинал</a>'
                    await message_to_reply.reply_text(message_with_link, parse_mode='HTML')

                image_text = (
                    "изображение" if image_count % 10 == 1 and image_count % 100 != 11
                    else "изображения" if 2 <= image_count % 10 <= 4 and (image_count % 100 < 10 or image_count % 100 >= 20)
                    else "изображений"
                )

                await message_to_reply.reply_text(
                    f'====--- В статье {image_count} {image_text} ---===='
                )

                publish_data[user_id] = {
                    'title': title,
                    'article_url': article_url,
                    'image_count': image_count,
                    'author_line': author_line
                }

                del user_data[user_id]
                await message_to_reply.reply_text(
                    '✅Все данные для публикации успешно созданы.\n'
                    'Но сейчас они видны только вам, чтобы поделиться ими с администрацией просто нажмите /share '
                    '(эта кнопка будет работать только до вашего следующего нажатия команды publish).\n\n'
                    'Либо создайте другую публикацию, если что-то пошло не так.\n\n'
                    '<i>Вы так же можете ввести команду /send, чтобы перейти в режим прямой связи с администрацией. '
                    'Просто нажмите на эту команду, и после этого любые ваши сообщения, отправленные боту, будут сразу дублироваться администрации. '
                    'Таким образом, вы можете задать вопросы, отправить дополнительные файлы, изображения и пояснения касательно вашей публикации, '
                    'сообщить об обнаруженных багах или что-то ещё.</i>\n\n'
                    '✅*Бот перезапущен успешно.*\n\n'
                    '(=^・ェ・^=)',
                    parse_mode='HTML',  # Добавляем parse_mode
                    reply_markup=ReplyKeyboardRemove()
                )
                logger.info(f"User {user_id}'s data cleared and process completed.")
                await message_to_reply.reply_text('********************************************************')
                # Вызов команды restart
                await restart(update, context)

                return ConversationHandler.END
            else:
                await message_to_reply.reply_text('🚫Ошибка при создании статьи. /restart')
        except requests.RequestException as e:
            logger.error(f"Request error: {e}")
            await message_to_reply.reply_text('🚫Ошибка при создании статьи. /restart')
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            await message_to_reply.reply_text('🚫Произошла неожиданная ошибка. /restart')


import ast



async def unknown_message(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    if user_id not in user_data:
        await update.message.reply_text('🚫Неизвестное сообщение. Пожалуйста, отправьте ссылку на автора, имя автора или изображение. В случае если это сообщение повторяется нажмите /restart')
    else:
        # Обработка сообщений в процессе
        if user_data[user_id]['status'] == 'awaiting_artist_link':
            await handle_artist_link(update, context)
        elif user_data[user_id]['status'] == 'awaiting_author_name':
            await handle_author_name(update, context)
        elif user_data[user_id]['status'] == 'awaiting_image':
            await handle_image(update, context)
            
# Функция для разбиения списка изображений на группы по 10
def chunk_images(images, chunk_size=10):
    for i in range(0, len(images), chunk_size):
        yield images[i:i + chunk_size]

TELEGRAM_API_TIMEOUT = 20  # Увеличьте время ожидания        

async def share(update: Update, context: CallbackContext) -> None:
    global publish_data
    user_id = update.message.from_user.id
    if user_id in publish_data:
        data = publish_data[user_id]
        title = data['title']
        article_url = data['article_url']
        author_line = data['author_line']

        try:
            # Увеличиваем таймаут для запроса к Telegra.ph
            article_response = requests.get(f'https://api.telegra.ph/getPage?path={article_url.split("/")[-1]}&return_content=true', timeout=10)
            article_response.raise_for_status()
            article_data = article_response.json()

            # Ищем изображения в контенте, включая теги figure
            images = []
            for node in article_data['result']['content']:
                if node.get('tag') == 'img' and 'attrs' in node and 'src' in node['attrs']:
                    images.append(node['attrs']['src'])
                elif node.get('tag') == 'figure' and 'children' in node:
                    images_in_figure = count_images_in_content(node['children'])
                    images.extend([img['attrs']['src'] for img in node['children'] if img.get('tag') == 'img' and 'attrs' in img and 'src' in img['attrs']])

            # Отправляем сообщение с текстом
            message_with_link = f'Пользователь {update.message.from_user.username} предложил:\n {author_line}\n<a href="{article_url}">Оригинал</a>'
            await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=message_with_link, parse_mode='HTML', disable_web_page_preview=True)

            # Отправляем изображения группами по 10
            if images:
                for image_group in chunk_images(images):
                    media_group = [InputMediaPhoto(image) for image in image_group]
                    await context.bot.send_media_group(chat_id=GROUP_CHAT_ID, media=media_group)
                    await asyncio.sleep(1)  # Задержка в 1 секунду между отправками медиа-групп
            else:
                await context.bot.send_message(chat_id=GROUP_CHAT_ID, text='Изображений в статье нет.')

            # Сообщение об успешной отправке
            await update.message.reply_text('✅Ваше предложение отправлено администрации. Спасибо.')

        except Timeout:
            logger.warning("Request to Telegram timed out, but message sent successfully.")
            await update.message.reply_text('✅Ваше предложение отправлено, но обработка статьи заняла больше времени. Вероятно это произошло из-за большого объёма статьи, на всякий случай сообщите об этом через команду /send и прикрепите там ссылку на вашу статью /restart для перезапуска')
        except Exception as e:
            logger.error(f"Failed to process article: {e}")
            await update.message.reply_text('✅Ваше предложение отправлено, но обработка статьи заняла больше времени. Вероятно это произошло из-за большого объёма статьи, на всякий случай сообщите об этом через команду /send и прикрепите там ссылку на вашу статью /restart для перезапуска')
    else:
        await update.message.reply_text('🚫Нет данных для предложения.')

async def send_mode(update: Update, context: CallbackContext) -> None:
    """Включение режима дублирования сообщений."""
    user_id = update.message.from_user.id
    users_in_send_mode.add(user_id)
    await update.message.reply_text('🔄 Режим прямой связи включен. Все последующие сообщения будут дублироваться администрации. Для завершения режима введите /fin')
    
async def fin_mode(update: Update, context: CallbackContext) -> None:
    """Выключение режима дублирования сообщений и возврат к изначальной логике."""
    user_id = update.message.from_user.id
    if user_id in users_in_send_mode:
        users_in_send_mode.remove(user_id)
        await update.message.reply_text('✅ Режим пересылки сообщений администрации отключен. Бот вернулся к своему основному режиму работы.')
    else:
        await update.message.reply_text('❗ Вы не активировали режим дублирования.')

from telegram import InputMediaPhoto, InputMediaVideo, InputMediaDocument

async def duplicate_message(update: Update, context: CallbackContext) -> None:
    """Дублирование сообщений пользователя в группу, включая медиа-группы, одиночные сообщения и документы."""
    user = update.message.from_user
    user_name = user.username if user.username else user.full_name
    message_prefix = f"{user_name} отправил сообщение:"

    if user.id in users_in_send_mode:
        # Если сообщение является частью медиа-группы
        if update.message.media_group_id:
            media_group = []
            messages = await context.bot.get_updates(offset=update.update_id - 10)  # Получаем несколько предыдущих сообщений для сборки медиа-группы

            # Фильтрация сообщений с тем же media_group_id
            for message in messages:
                if message.message.media_group_id == update.message.media_group_id:
                    if message.message.photo:
                        media_group.append(InputMediaPhoto(message.message.photo[-1].file_id, caption=message.message.caption if message.message.caption else ""))
                    elif message.message.video:
                        media_group.append(InputMediaVideo(message.message.video.file_id, caption=message.message.caption if message.message.caption else ""))
                    elif message.message.document:
                        media_group.append(InputMediaDocument(message.message.document.file_id, caption=message.message.caption if message.message.caption else ""))

            # Отправляем медиа-группу, если она есть
            if media_group:
                await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=message_prefix)
                await context.bot.send_media_group(chat_id=GROUP_CHAT_ID, media=media_group)
                await update.message.reply_text("Сообщение успешно отправлено администрации. Для завершения режима дублирования введите /fin")

        # Обработка одиночных текстовых сообщений
        elif update.message.text:
            await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=f"{message_prefix}\n{update.message.text}")
            await update.message.reply_text("Сообщение успешно отправлено администрации. Для завершения режима дублирования введите /fin")

        # Обработка одиночных фото
        elif update.message.photo:
            photo = update.message.photo[-1].file_id  # Получаем последнюю фотографию с наибольшим разрешением
            await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=message_prefix)
            await context.bot.send_photo(chat_id=GROUP_CHAT_ID, photo=photo, caption=update.message.caption)
            await update.message.reply_text("Сообщение успешно отправлено администрации. Для завершения режима дублирования введите /fin")

        # Обработка одиночных документов (включая изображения, отправленные как файл)
        elif update.message.document:
            doc = update.message.document.file_id
            await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=message_prefix)
            await context.bot.send_document(chat_id=GROUP_CHAT_ID, document=doc, caption=update.message.caption)
            await update.message.reply_text("Сообщение успешно отправлено администрации. Для завершения режима дублирования введите /fin")

        # Обработка одиночных видео
        elif update.message.video:
            video = update.message.video.file_id
            await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=message_prefix)
            await context.bot.send_video(chat_id=GROUP_CHAT_ID, video=video, caption=update.message.caption)
            await update.message.reply_text("Сообщение успешно отправлено администрации. Для завершения режима дублирования введите /fin")

        # Обработка стикеров
        elif update.message.sticker:
            await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=message_prefix)
            await context.bot.send_sticker(chat_id=GROUP_CHAT_ID, sticker=update.message.sticker.file_id)
            await update.message.reply_text("Сообщение успешно отправлено администрации. Для завершения режима дублирования введите /fin")

        # Обработка аудио
        elif update.message.audio:
            await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=message_prefix)
            await context.bot.send_audio(chat_id=GROUP_CHAT_ID, audio=update.message.audio.file_id, caption=update.message.caption)
            await update.message.reply_text("Сообщение успешно отправлено администрации. Для завершения режима дублирования введите /fin")

        # Добавьте обработку других типов сообщений по мере необходимости
    else:
        # Если пользователь не в режиме дублирования, продолжаем с основной логикой
        await start(update, context)




def main() -> None:
    load_context_from_firebase()  # Загружаем историю чатов в user_contexts
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Настройка ConversationHandler для основной логики
    conversation_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CommandHandler('edit', edit_article),            
            MessageHandler(filters.TEXT & ~filters.COMMAND, main_logic)  # Основная логика
        ],
        states={
            ASKING_FOR_ARTIST_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_artist_link)],
            ASKING_FOR_AUTHOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_author_name)],
            EDITING_FRAGMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_text)],
            ASKING_FOR_IMAGE: [
                MessageHandler(filters.PHOTO | filters.Document.ALL, handle_new_image),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
            ],
        },
        fallbacks=[MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message)],
        per_user=True
    )

    search_handler = ConversationHandler(
        entry_points=[CommandHandler('search', start_search)],
        states={
            ASKING_FOR_FILE: [
                MessageHandler(filters.PHOTO | filters.Document.ALL, handle_file),
                MessageHandler(filters.ALL & ~filters.COMMAND, unknown_search_message),
            ],
        },
        fallbacks=[
            CommandHandler('fin_search', finish_search),
            CommandHandler('restart', restart),  # Добавлен обработчик для /restart
        ],
        per_user=True,
        allow_reentry=True
    )

    ocr_handler = ConversationHandler(
        entry_points=[CommandHandler('ocr', start_ocr), CallbackQueryHandler(text_rec_with_gpt, pattern='^text_rec$')],
        states={
            ASKING_FOR_FILE: [
                MessageHandler(filters.PHOTO | filters.Document.ALL, handle_file),
                MessageHandler(filters.ALL & ~filters.COMMAND, unknown_ocr_message),
            ],
            ASKING_FOR_FOLLOWUP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_followup_question),            ],        
        },
        fallbacks=[
            CommandHandler('fin_ocr', finish_ocr),
            CommandHandler('restart', restart),  # Добавлен обработчик для /restart
        ],
        per_user=True,
        allow_reentry=True
    )

    gpt_handler = ConversationHandler(
        entry_points=[CommandHandler('gpt', run_gpt), CommandHandler('set_role', handle_set_role_button), CommandHandler('help_gpt', handle_gpt_help), CommandHandler('short_help_gpt', handle_short_gpt_help)],
        states={
            ASKING_FOR_ROLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_role_input),
            ],
            ASKING_FOR_FILE: [
                MessageHandler(filters.PHOTO | filters.Document.ALL, handle_file),
                MessageHandler(filters.ALL & ~filters.COMMAND, unknown_ocr_message),
            ],
        },
        fallbacks=[
            CommandHandler('fin_gpt', stop_gpt),
            CommandHandler('restart', restart),  # Добавлен обработчик для /restart
        ],
        per_user=True,
        allow_reentry=True
    )

    # Добавляем обработчики команд
    application.add_handler(CallbackQueryHandler(handle_edit_button, pattern='edit_article'))
    application.add_handler(CallbackQueryHandler(handle_delete_button, pattern='delete_last'))
    application.add_handler(CallbackQueryHandler(handle_edit_delete, pattern='^edit_|^delete_'))
    application.add_handler(CallbackQueryHandler(handle_preview_button, pattern='preview_article'))
    application.add_handler(CallbackQueryHandler(handle_create_article_button, pattern='create_article'))
    application.add_handler(CallbackQueryHandler(handle_help_text_button, pattern='help_command'))
    application.add_handler(CallbackQueryHandler(handle_restart_button, pattern='restart'))
    application.add_handler(CallbackQueryHandler(handle_page_change, pattern='^page_')) 
    application.add_handler(CallbackQueryHandler(ai_or_not, pattern='ai_or_not'))
    application.add_handler(CallbackQueryHandler(finish_search, pattern='finish_search')) 
    application.add_handler(CallbackQueryHandler(finish_ocr, pattern='finish_ocr'))
    application.add_handler(CallbackQueryHandler(stop_gpt, pattern='stop_gpt'))      
    application.add_handler(CallbackQueryHandler(start_search, pattern='start_search'))
    application.add_handler(CallbackQueryHandler(start_ocr, pattern='start_ocr'))
    application.add_handler(CallbackQueryHandler(button_ocr, pattern='recognize_text'))
    application.add_handler(CallbackQueryHandler(button_ocr, pattern='recognize_plant'))
    application.add_handler(CallbackQueryHandler(button_more_plants_handler, pattern='plant_\\d+'))
    application.add_handler(CallbackQueryHandler(gpt_plants_help_handler, pattern='^gpt_plants_help$'))
    application.add_handler(CallbackQueryHandler(gpt_plants_more_handler, pattern='^gpt_plants_more$'))
    application.add_handler(CallbackQueryHandler(text_rec_with_gpt, pattern='text_rec_with_gpt$'))
    application.add_handler(CallbackQueryHandler(text_plant_help_with_gpt, pattern='text_plant_help_with_gpt$'))    
    application.add_handler(CallbackQueryHandler(handle_check_text, pattern='^check_text$'))
    application.add_handler(CallbackQueryHandler(run_gpt, pattern='run_gpt')) 
    application.add_handler(CallbackQueryHandler(reset_dialog, pattern='^reset_dialog$')) 
    application.add_handler(CallbackQueryHandler(handle_set_role_button, pattern='^set_role_button$'))  
    application.add_handler(CallbackQueryHandler(handle_followup_question, pattern='^ask_followup'))    
    application.add_handler(CallbackQueryHandler(handle_gpt_help, pattern='^help_gpt$'))
    application.add_handler(CallbackQueryHandler(handle_short_gpt_help, pattern='^short_help_gpt$'))    
    application.add_handler(CallbackQueryHandler(handle_choose_preset, pattern="choose_preset"))
    application.add_handler(CallbackQueryHandler(handle_preset_selection, pattern="set_preset:.*"))
    application.add_handler(CallbackQueryHandler(handle_choose_model, pattern="^choose_model$"))
    application.add_handler(CallbackQueryHandler(handle_model_selection, pattern="^set_model:"))
    
    
    application.add_handler(CommandHandler('set_role', set_role ))          
    application.add_handler(CommandHandler('send', send_mode))
    application.add_handler(CommandHandler('fin', fin_mode))
    application.add_handler(CommandHandler('restart', restart))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('publish', publish))
    application.add_handler(CommandHandler('preview', preview_article))  # Добавляем обработчик для /preview
    application.add_handler(CommandHandler('delete', delete_last))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, duplicate_message))  # Обработчик дублирования сообщений
    application.add_handler(CommandHandler('share', share))  # Добавляем обработчик для /share

    # Добавляем обработчики для команд /search и /fin_search
    application.add_handler(search_handler)
    application.add_handler(CommandHandler('fin_search', finish_search))  # Обработчик команды /fin_search

    # Добавляем обработчики для команд /ocr и /fin_ocr
    application.add_handler(ocr_handler)
    application.add_handler(CommandHandler('fin_ocr', finish_ocr)) 

    # Добавляем обработчики для команд /gpt и /fin_gpt
    application.add_handler(gpt_handler)
    application.add_handler(CommandHandler('fin_gpt', stop_gpt))     

    # Добавляем основной conversation_handler
    application.add_handler(conversation_handler)

    logger.info("Bot started and polling...")  
    keep_alive()#запускаем flask-сервер в отдельном потоке. Подробнее ниже...
    application.run_polling() #запуск бота    

if __name__ == '__main__':
    main()
