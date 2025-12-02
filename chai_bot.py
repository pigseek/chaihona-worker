import logging
import re
import sqlite3
import telebot
from telebot import types
import threading
import time
from datetime import datetime

# Настройки
TOKEN = "7790643850:AAGUGZ4Nsrw_NHZSt_xM7YxrePLY9oBqH5Y"
ADMIN_USERNAME = "@@Imperator_M"
DB_NAME = "bot_database.db"

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN)

# Инициализация базы данных с проверкой и добавлением отсутствующих столбцов
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Создаем таблицу пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            name TEXT,
            late_minutes INTEGER DEFAULT 0,
            contribution INTEGER DEFAULT 0,
            role TEXT DEFAULT 'worker',
            chat_id INTEGER
        )
    ''')
    
    # Создаем таблицу настроек
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE,
            value TEXT
        )
    ''')
    
    # Создаем таблицу для очереди опозданий
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS late_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_name TEXT,
            amount INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Создаем таблицу для предложений работы
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS work_proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_username TEXT,
            worker_name TEXT,
            work_description TEXT,
            status TEXT DEFAULT 'pending',
            admin_chat_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Создаем таблицу для запросов помощи
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS help_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            name TEXT,
            message TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Проверяем существующие столбцы
    cursor.execute("PRAGMA table_info(users)")
    columns = [column[1] for column in cursor.fetchall()]
    
    # Добавляем отсутствующие столбцы
    if 'contribution' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN contribution INTEGER DEFAULT 0")
        print("Добавлен столбец contribution")
    
    if 'chat_id' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN chat_id INTEGER")
        print("Добавлен столбец chat_id")
    
    # Добавляем администратора если его нет
    cursor.execute(
        "INSERT OR IGNORE INTO users (username, role) VALUES (?, 'admin')", 
        (ADMIN_USERNAME,)
    )
    
    conn.commit()
    conn.close()
    print("База данных инициализирована")

# Обновление взносов для всех пользователей
def update_contributions():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET contribution = late_minutes * 10")
    conn.commit()
    conn.close()

# Проверка прав доступа
def check_access(username):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM users WHERE username = ?", (username,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

# Получение роли пользователя
def get_user_role(username):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE username = ?", (username,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

# Получение chat_id админа
def get_admin_chat_id():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id FROM users WHERE role = 'admin'")
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

# Получение списка работников (только имена)
def get_workers_names():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM users WHERE role = 'worker'")
    result = cursor.fetchall()
    conn.close()
    return [worker[0] for worker in result] if result else []

# Получение работников с ненулевыми опозданиями
def get_workers_with_late():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT username, name, late_minutes, contribution, chat_id FROM users WHERE role = 'worker' AND late_minutes > 0")
    result = cursor.fetchall()
    conn.close()
    return result

# Получение даты уведомления
def get_notification_date():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'notification_date'")
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

# Сохранение дату уведомления
def set_notification_date(date):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        ('notification_date', date)
    )
    conn.commit()
    conn.close()

# Получение времени уведомления
def get_notification_time():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'notification_time'")
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

# Сохранение времени уведомления
def set_notification_time(time_str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        ('notification_time', time_str)
    )
    conn.commit()
    conn.close()

# Добавление опоздания в очередь
def add_to_late_queue(worker_name, amount):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO late_queue (worker_name, amount) VALUES (?, ?)",
        (worker_name, amount)
    )
    conn.commit()
    conn.close()

# Получение следующего опоздания из очереди
def get_next_late_from_queue():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, worker_name, amount FROM late_queue WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1")
    result = cursor.fetchone()
    conn.close()
    return result

# Обновление статуса опоздания в очереди
def update_late_status(queue_id, status):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE late_queue SET status = ? WHERE id = ?",
        (status, queue_id)
    )
    conn.commit()
    conn.close()

# Сохранение предложения работы
def save_work_proposal(worker_username, worker_name, work_description, admin_chat_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO work_proposals (worker_username, worker_name, work_description, admin_chat_id) VALUES (?, ?, ?, ?)",
        (worker_username, worker_name, work_description, admin_chat_id)
    )
    proposal_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return proposal_id

# Обновление статуса предложения работы
def update_work_proposal_status(proposal_id, status):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE work_proposals SET status = ? WHERE id = ?",
        (status, proposal_id)
    )
    conn.commit()
    conn.close()

# Получение информации о предложении работы
def get_work_proposal(proposal_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM work_proposals WHERE id = ?", (proposal_id,))
    result = cursor.fetchone()
    conn.close()
    return result

# Сохранение запроса помощи
def save_help_request(user_id, username, name, message):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO help_requests (user_id, username, name, message) VALUES (?, ?, ?, ?)",
        (user_id, username, name, message)
    )
    conn.commit()
    conn.close()

# Создание основной клавиатуры в зависимости от роли
def get_main_keyboard(role):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if role == 'admin':
        keyboard.add(
            types.KeyboardButton("Инфо"), 
            types.KeyboardButton("Списки"),
            types.KeyboardButton("Дата уведомления"),
            types.KeyboardButton("Время уведомления"),
            types.KeyboardButton("🚨Помощь")
        )
    else:
        keyboard.add(
            types.KeyboardButton("Инфо"), 
            types.KeyboardButton("Погасить взнос"),
            types.KeyboardButton("🚨Помощь")
        )
    return keyboard

# Создание клавиатуры для меню списков
def get_lists_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("Добавить работника"), types.KeyboardButton("Удалить работника"))
    keyboard.add(types.KeyboardButton("Назад"))
    return keyboard

# Создание клавиатуры для подтверждения сброса
def get_reset_confirmation_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("Да, сбросить"), types.KeyboardButton("Нет, отменить"))
    keyboard.add(types.KeyboardButton("Назад"))
    return keyboard

# Создание временной клавиатуры с кнопкой Назад
def get_back_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("Назад"))
    return keyboard

# Создание клавиатуры для помощи
def get_help_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("Назад"))
    return keyboard

# Создание inline-клавиатуры для погашения взноса
def get_repayment_keyboard(worker_username):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("Внести баллы", callback_data=f"pay_{worker_username}"),
        types.InlineKeyboardButton("Предложить работу", callback_data=f"suggest_work_{worker_username}"),
        types.InlineKeyboardButton("Отказаться", callback_data=f"decline_{worker_username}")
    )
    return keyboard

# Создание inline-клавиатуры для администратора при получении предложения работы
def get_admin_work_proposal_keyboard(proposal_id):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("Одобрить работу", callback_data=f"approve_work_{proposal_id}"),
        types.InlineKeyboardButton("Отказать", callback_data=f"reject_work_{proposal_id}")
    )
    return keyboard

# Создание inline-клавиатуры для подтверждения одобрения работы
def get_confirm_approve_work_keyboard(proposal_id):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("Да, одобрить", callback_data=f"confirm_approve_{proposal_id}"),
        types.InlineKeyboardButton("Нет, отменить", callback_data=f"cancel_approve_{proposal_id}")
    )
    return keyboard

# Создание inline-клавиатуры для подтверждения отказа работы
def get_confirm_reject_work_keyboard(proposal_id):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("Да, отказать", callback_data=f"confirm_reject_{proposal_id}"),
        types.InlineKeyboardButton("Нет, отменить", callback_data=f"cancel_reject_{proposal_id}")
    )
    return keyboard

# Обработчик команды /start
@bot.message_handler(commands=['start'])
def start(message):
    user = message.from_user
    username = user.username
    chat_id = user.id
    
    if not username or not check_access(f"@{username}"):
        bot.reply_to(message, "❌Вас нет в белом листе!")
        return
    
    # Сохраняем chat_id пользователя
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET chat_id = ? WHERE username = ?",
        (chat_id, f"@{username}")
    )
    conn.commit()
    conn.close()
    
    role = get_user_role(f"@{username}")
    
    if role == 'admin':
        bot.reply_to(message, "Добро пожаловать, Админ!", reply_markup=get_main_keyboard(role))
    else:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM users WHERE username = ?", (f"@{username}",))
        result = cursor.fetchone()
        conn.close()
        
        if not result or not result[0]:
            msg = bot.reply_to(message, "Введите ваше имя:", reply_markup=get_back_keyboard())
            bot.register_next_step_handler(msg, process_name_step)
        else:
            bot.reply_to(message, "Главное меню:", reply_markup=get_main_keyboard(role))

def process_name_step(message):
    if message.text == 'Назад':
        username = message.from_user.username
        role = get_user_role(f"@{username}")
        bot.reply_to(message, "Возврат в главное меню.", reply_markup=get_main_keyboard(role))
        return
        
    try:
        name = message.text
        username = f"@{message.from_user.username}"
        role = get_user_role(username)
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET name = ? WHERE username = ?", 
            (name, username)
        )
        conn.commit()
        conn.close()
        
        bot.reply_to(message, "Имя сохранено!", reply_markup=get_main_keyboard(role))
    except Exception as e:
        bot.reply_to(message, 'Ошибка при сохранении имени.')

# Обработчик кнопки "Инфо"
@bot.message_handler(func=lambda message: message.text == 'Инфо')
def worker_info(message):
    username = message.from_user.username
    role = get_user_role(f"@{username}")
    
    if role == 'admin':
        msg = bot.reply_to(message, "Введите имя сотрудника:", reply_markup=get_back_keyboard())
        bot.register_next_step_handler(msg, get_worker_info_admin)
    else:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, late_minutes FROM users WHERE username = ?", 
            (f"@{username}",)
        )
        result = cursor.fetchone()
        conn.close()
        
        if result:
            bot.reply_to(message, f"Имя: {result[0]}\nМинуты опозданий: {result[1]}", reply_markup=get_main_keyboard(role))

def get_worker_info_admin(message):
    if message.text == 'Назад':
        username = message.from_user.username
        role = get_user_role(f"@{username}")
        bot.reply_to(message, "Возврат в главное меню.", reply_markup=get_main_keyboard(role))
        return
        
    try:
        name = message.text
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, username, late_minutes, contribution FROM users WHERE name = ?", 
            (name,)
        )
        result = cursor.fetchone()
        conn.close()
        
        if result:
            worker_name, worker_username, late_minutes, contribution = result
            
            # Сохраняем информацию о выбранном работнике для последующего сброса
            if not hasattr(bot, 'reset_workers'):
                bot.reset_workers = {}
            bot.reset_workers[message.chat.id] = worker_username
            
            # Создаем клавиатуру с кнопкой сброса
            keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
            keyboard.add(types.KeyboardButton("Сбросить взнос и минуты"))
            keyboard.add(types.KeyboardButton("Назад"))
            
            bot.reply_to(message, 
                f"Имя: {worker_name}\n"
                f"Username: {worker_username}\n"
                f"Минуты опозданий: {late_minutes}\n"
                f"Взнос: {contribution} баллов\n\n"
                f"Вы можете сбросить минуты опозданий и взнос для этого сотрудника:",
                reply_markup=keyboard)
        else:
            # Если сотрудник не найден, предлагаем ввести имя снова
            msg = bot.reply_to(message, "Сотрудник не найден. Введите имя сотрудника снова:", reply_markup=get_back_keyboard())
            bot.register_next_step_handler(msg, get_worker_info_admin)
    except Exception as e:
        bot.reply_to(message, 'Ошибка при поиске сотрудника.')

# Обработчик кнопки "Погасить взнос" для работника
@bot.message_handler(func=lambda message: message.text == 'Погасить взнос')
def repay_contribution(message):
    username = f"@{message.from_user.username}"
    
    # Получаем информацию о работнике
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name, late_minutes, contribution FROM users WHERE username = ?", 
        (username,)
    )
    result = cursor.fetchone()
    conn.close()
    
    if result:
        name, late_minutes, contribution = result
        if contribution > 0:
            # Отправляем сообщение с inline-кнопками
            bot.send_message(
                message.chat.id,
                f"Привет, {name}!\n"
                f"В этом месяце твоё суммарное количество минут опоздания составило {late_minutes}.\n"
                f"Ты можешь внести {contribution} баллов в общий фонд, чтобы сбросить накопившиеся минуты.\n"
                f"Или предложи работу для погашения взноса.",
                reply_markup=get_repayment_keyboard(username)
            )
        else:
            bot.reply_to(message, "У вас нет накопленных минут опоздания.")
    else:
        bot.reply_to(message, "Ошибка: пользователь не найден.")

# Обработчик кнопки "🚨Помощь"
@bot.message_handler(func=lambda message: message.text == '🚨Помощь')
def help_request(message):
    # Запрашиваем описание проблемы
    msg = bot.reply_to(
        message,
        "Подробно опишите техническую проблему, с которой вы столкнулись, можете также прикрепить скриншоты. Разработчик постарается исправить эту ошибку как можно скорее!",
        reply_markup=get_help_keyboard()
    )
    
    # Сохраняем информацию о том, что ожидаем описание проблемы
    if not hasattr(bot, 'waiting_for_help'):
        bot.waiting_for_help = {}
    bot.waiting_for_help[message.from_user.id] = True

# Обработчик кнопки "Сбросить взнос и минуты"
@bot.message_handler(func=lambda message: message.text == 'Сбросить взнос и минуты')
def reset_contribution(message):
    if not hasattr(bot, 'reset_workers') or message.chat.id not in bot.reset_workers:
        bot.reply_to(message, "Ошибка: сотрудник не выбран.", reply_markup=get_main_keyboard('admin'))
        return
    
    worker_username = bot.reset_workers[message.chat.id]
    
    # Получаем информацию о сотруднике
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM users WHERE username = ?", 
        (worker_username,)
    )
    result = cursor.fetchone()
    conn.close()
    
    if result:
        worker_name = result[0]
        msg = bot.reply_to(message, 
            f"Вы уверены, что хотите сбросить минуты опозданий и взнос для сотрудника {worker_name}?",
            reply_markup=get_reset_confirmation_keyboard())
        
        # Сохраняем информацию для подтверждения
        if not hasattr(bot, 'pending_resets'):
            bot.pending_resets = {}
        bot.pending_resets[message.chat.id] = worker_username

# Обработчик подтверждения сброса
@bot.message_handler(func=lambda message: message.text == 'Да, сбросить')
def confirm_reset(message):
    if not hasattr(bot, 'pending_resets') or message.chat.id not in bot.pending_resets:
        bot.reply_to(message, "Ошибка: нет ожидающих операций сброса.", reply_markup=get_main_keyboard('admin'))
        return
    
    worker_username = bot.pending_resets[message.chat.id]
    
    # Получаем информацию о сотруднике перед сбросом
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM users WHERE username = ?", 
        (worker_username,)
    )
    result = cursor.fetchone()
    
    if result:
        worker_name = result[0]
        
        # Обнуляем минуты и взнос
        cursor.execute(
            "UPDATE users SET late_minutes = 0, contribution = 0 WHERE username = ?",
            (worker_username,)
        )
        conn.commit()
        conn.close()
        
        bot.reply_to(message, f"✅ Минуты опозданий и взнос для {worker_name} обнулены.", reply_markup=get_main_keyboard('admin'))
    else:
        conn.close()
        bot.reply_to(message, "Ошибка: сотрудник не найден.", reply_markup=get_main_keyboard('admin'))
    
    # Очищаем временные данные
    if hasattr(bot, 'pending_resets') and message.chat.id in bot.pending_resets:
        del bot.pending_resets[message.chat.id]
    if hasattr(bot, 'reset_workers') and message.chat.id in bot.reset_workers:
        del bot.reset_workers[message.chat.id]

# Обработчик отмены сброса
@bot.message_handler(func=lambda message: message.text == 'Нет, отменить')
def cancel_reset(message):
    if hasattr(bot, 'pending_resets') and message.chat.id in bot.pending_resets:
        del bot.pending_resets[message.chat.id]
    if hasattr(bot, 'reset_workers') and message.chat.id in bot.reset_workers:
        del bot.reset_workers[message.chat.id]
    
    bot.reply_to(message, "Сброс отменен.", reply_markup=get_main_keyboard('admin'))

# Обработчик кнопки "Списки"
@bot.message_handler(func=lambda message: message.text == 'Списки')
def lists_menu(message):
    username = message.from_user.username
    role = get_user_role(f"@{username}")
    
    if role == 'admin':
        workers = get_workers_names()
        if workers:
            workers_text = "Список работников в белом листе:\n\n" + "\n".join(workers)
        else:
            workers_text = "Нет зарегистрированных работников."
        
        bot.reply_to(message, workers_text, reply_markup=get_lists_keyboard())

# Обработчик кнопки "Добавить работника"
@bot.message_handler(func=lambda message: message.text == 'Добавить работника')
def add_worker(message):
    msg = bot.reply_to(message, "Введите username нового работника:", reply_markup=get_back_keyboard())
    bot.register_next_step_handler(msg, process_add_worker)

def process_add_worker(message):
    if message.text == 'Назад':
        username = message.from_user.username
        role = get_user_role(f"@{username}")
        bot.reply_to(message, "Возврат в главное меню.", reply_markup=get_main_keyboard(role))
        return
        
    try:
        new_username = message.text
        # Автоматически добавляем @ если его нет
        if not new_username.startswith('@'):
            new_username = f"@{new_username}"
        
        username = message.from_user.username
        role = get_user_role(f"@{username}")
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO users (username, role) VALUES (?, 'worker')", 
                (new_username,)
            )
            conn.commit()
            bot.reply_to(message, f"Пользователь {new_username} добавлен в белый список!", reply_markup=get_main_keyboard(role))
        except sqlite3.IntegrityError:
            bot.reply_to(message, f"Пользователь {new_username} уже существует", reply_markup=get_main_keyboard(role))
        conn.close()
    except Exception as e:
        bot.reply_to(message, 'Ошибка при добавлении пользователя.')

# Обработчик кнопки "Удалить работника"
@bot.message_handler(func=lambda message: message.text == 'Удалить работника')
def delete_worker(message):
    msg = bot.reply_to(message, "Введите username работника для удаления:", reply_markup=get_back_keyboard())
    bot.register_next_step_handler(msg, process_delete_worker)

def process_delete_worker(message):
    if message.text == 'Назад':
        username = message.from_user.username
        role = get_user_role(f"@{username}")
        bot.reply_to(message, "Возврат в главное меню.", reply_markup=get_main_keyboard(role))
        return
        
    try:
        username_to_delete = message.text
        if not username_to_delete.startswith('@'):
            username_to_delete = f"@{username_to_delete}"
        
        username = message.from_user.username
        role = get_user_role(f"@{username}")
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Проверяем, существует ли пользователь
        cursor.execute("SELECT username FROM users WHERE username = ? AND role = 'worker'", (username_to_delete,))
        result = cursor.fetchone()
        
        if result:
            cursor.execute("DELETE FROM users WHERE username = ?", (username_to_delete,))
            conn.commit()
            bot.reply_to(message, f"Пользователь {username_to_delete} удален из белого списка!", reply_markup=get_main_keyboard(role))
        else:
            # Если пользователь не найден, предлагаем ввести username снова
            msg = bot.reply_to(message, f"Пользователь {username_to_delete} не найден или не может быть удален. Введите username снова:", reply_markup=get_back_keyboard())
            bot.register_next_step_handler(msg, process_delete_worker)
        
        conn.close()
    except Exception as e:
        bot.reply_to(message, 'Ошибка при удалении пользователя.')

# Обработчик кнопки "Назад"
@bot.message_handler(func=lambda message: message.text == 'Назад')
def back_to_main(message):
    username = message.from_user.username
    role = get_user_role(f"@{username}")
    
    # Очищаем временные данные при возврате в главное меню
    if hasattr(bot, 'pending_resets') and message.chat.id in bot.pending_resets:
        del bot.pending_resets[message.chat.id]
    if hasattr(bot, 'reset_workers') and message.chat.id in bot.reset_workers:
        del bot.reset_workers[message.chat.id]
    
    # Очищаем состояние ожидания помощи
    if hasattr(bot, 'waiting_for_help') and message.from_user.id in bot.waiting_for_help:
        del bot.waiting_for_help[message.from_user.id]
    
    # Очищаем состояние ожидания описания работы
    if hasattr(bot, 'waiting_for_work_description') and message.from_user.id in bot.waiting_for_work_description:
        del bot.waiting_for_work_description[message.from_user.id]
    
    # Очищаем состояние ожидания скриншота
    if hasattr(bot, 'waiting_for_screenshot') and message.from_user.id in bot.waiting_for_screenshot:
        del bot.waiting_for_screenshot[message.from_user.id]
    
    bot.reply_to(message, "Главное меню:", reply_markup=get_main_keyboard(role))

# Обработчик кнопки "Дата уведомления"
@bot.message_handler(func=lambda message: message.text == 'Дата уведомления')
def notification_date(message):
    username = message.from_user.username
    role = get_user_role(f"@{username}")
    
    if role == 'admin':
        current_date = get_notification_date()
        if current_date:
            msg = bot.reply_to(message, f"Текущая дата уведомления: {current_date}\nВведите новое число месяца (1-31):", reply_markup=get_back_keyboard())
        else:
            msg = bot.reply_to(message, "Введите число месяца для уведомления (1-31):", reply_markup=get_back_keyboard())
        bot.register_next_step_handler(msg, process_notification_date)

def process_notification_date(message):
    if message.text == 'Назад':
        username = message.from_user.username
        role = get_user_role(f"@{username}")
        bot.reply_to(message, "Возврат в главное меню.", reply_markup=get_main_keyboard(role))
        return
        
    try:
        date = message.text
        if not date.isdigit() or int(date) < 1 or int(date) > 31:
            bot.reply_to(message, "Пожалуйста, введите корректное число месяца (1-31).", reply_markup=get_main_keyboard('admin'))
            return
        
        set_notification_date(date)
        bot.reply_to(message, f"Дата уведомления установлена на {date} число каждого месяца.", reply_markup=get_main_keyboard('admin'))
    except Exception as e:
        bot.reply_to(message, 'Ошибка при установке даты уведомления.')

# Обработчик кнопки "Время уведомления"
@bot.message_handler(func=lambda message: message.text == 'Время уведомления')
def notification_time(message):
    username = message.from_user.username
    role = get_user_role(f"@{username}")
    
    if role == 'admin':
        current_time = get_notification_time()
        if current_time:
            msg = bot.reply_to(message, f"Текущее время уведомления: {current_time}\nВведите новое время в формате ЧЧ:ММ (например, 09:00):", reply_markup=get_back_keyboard())
        else:
            msg = bot.reply_to(message, "Введите время уведомления в формате ЧЧ:ММ (например, 09:00):", reply_markup=get_back_keyboard())
        bot.register_next_step_handler(msg, process_notification_time)

def process_notification_time(message):
    if message.text == 'Назад':
        username = message.from_user.username
        role = get_user_role(f"@{username}")
        bot.reply_to(message, "Возврат в главное меню.", reply_markup=get_main_keyboard(role))
        return
        
    try:
        time_str = message.text
        # Проверяем формат времени
        if not re.match(r'^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$', time_str):
            bot.reply_to(message, "Неверный формат времени. Введите время в формате ЧЧ:ММ (например, 09:00).", reply_markup=get_main_keyboard('admin'))
            return
        
        set_notification_time(time_str)
        bot.reply_to(message, f"Время уведомления установлено на {time_str}.", reply_markup=get_main_keyboard('admin'))
    except Exception as e:
        bot.reply_to(message, 'Ошибка при установке времени уведомления.')

# Обработчик опозданий в группах
@bot.message_handler(commands=['opoz'])
def handle_opoz(message):
    if message.chat.type not in ['group', 'supergroup']:
        return

    # Обновляем регулярное выражение для обработки часов
    pattern = r'/opoz\s+(\S+)\s+опоздание\s+(\d+)\s+(минут|часов|часа)'
    match = re.match(pattern, message.text)
    
    if match:
        worker_name = match.group(1)
        amount = int(match.group(2))
        unit = match.group(3)
        
        # Обрабатываем часы (умножаем на 60)
        if unit in ['часов', 'часа']:
            amount *= 60
        
        # Добавляем опоздание в очередь
        add_to_late_queue(worker_name, amount)
        
        # Проверяем, есть ли ожидающие опоздания
        check_and_send_next_late()

# Функция для проверки и отправки следующего опоздания из очереди
def check_and_send_next_late():
    next_late = get_next_late_from_queue()
    if next_late:
        queue_id, worker_name, amount = next_late
        
        # Получаем chat_id админа
        admin_chat_id = get_admin_chat_id()
        if not admin_chat_id:
            return

        # Создаем inline-клавиатуру
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("Да", callback_data=f"late_confirm_{queue_id}"),
            types.InlineKeyboardButton("Нет", callback_data=f"late_reject_{queue_id}")
        )
        
        # Отправляем сообщение админу
        bot.send_message(
            admin_chat_id,
            text=f"Подтвердить опоздание для {worker_name} на {amount} минут?",
            reply_markup=keyboard
        )

# Функция для отправки уведомлений о взносах
def send_contribution_notifications():
    notification_date = get_notification_date()
    notification_time = get_notification_time()
    
    if not notification_date or not notification_time:
        print(f"Дата или время уведомления не установлены. Дата: {notification_date}, Время: {notification_time}")
        return
    
    current_day = datetime.now().day
    current_time = datetime.now().strftime("%H:%M")
    
    print(f"Проверка уведомлений: Текущие - день {current_day}, время {current_time}; Установленные - день {notification_date}, время {notification_time}")
    
    if str(current_day) == notification_date and current_time == notification_time:
        print("Условия совпали, отправляем уведомления...")
        workers = get_workers_with_late()
        print(f"Найдено работников с опозданиями: {len(workers)}")
        
        for worker in workers:
            username, name, late_minutes, contribution, chat_id = worker
            
            if contribution > 0 and chat_id:
                # Отправляем сообщение работнику с inline-кнопками
                bot.send_message(
                    chat_id,
                    f"Привет, {name}!\n"
                    f"В этом месяце твоё суммарное количество минут опоздания составило {late_minutes}.\n"
                    f"Ты можешь внести {contribution} баллов в общий фонд, чтобы сбросить накопившиеся минуты.\n"
                    f"Или предложи работу для погашения взноса.",
                    reply_markup=get_repayment_keyboard(username)
                )
                print(f"Уведомление отправлено пользователю {name}")

# Безопасное редактирование сообщения
def safe_edit_or_send_message(chat_id, message_id, text, reply_markup=None):
    try:
        # Пытаемся отредактировать сообщение
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup
        )
    except Exception as e:
        # Если редактирование не удалось, отправляем новое сообщение
        print(f"Не удалось отредактировать сообщение, отправляем новое: {e}")
        bot.send_message(
            chat_id,
            text,
            reply_markup=reply_markup
        )

# Обработчик inline-кнопок для опозданий
@bot.callback_query_handler(func=lambda call: call.data.startswith(('late_confirm_', 'late_reject_')))
def handle_late_callback(call):
    try:
        if call.data.startswith('late_confirm_'):
            queue_id = int(call.data[13:])
            
            # Получаем данные опоздания
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT worker_name, amount FROM late_queue WHERE id = ?", (queue_id,))
            result = cursor.fetchone()
            
            if result:
                worker_name, amount = result
                
                # Обновляем минуты опоздания
                cursor.execute(
                    "UPDATE users SET late_minutes = late_minutes + ? WHERE name = ?",
                    (amount, worker_name)
                )
                # Обновляем взносы
                cursor.execute("UPDATE users SET contribution = late_minutes * 10")
                
                # Обновляем статус в очереди
                cursor.execute("UPDATE late_queue SET status = 'confirmed' WHERE id = ?", (queue_id,))
                
                conn.commit()
                conn.close()
                
                # Отправляем новое сообщение вместо редактирования
                bot.send_message(
                    call.message.chat.id,
                    f"✅ Опоздание для {worker_name} на {amount} минут подтверждено."
                )
            else:
                conn.close()
        
        elif call.data.startswith('late_reject_'):
            queue_id = int(call.data[12:])
            
            # Обновляем статус в очереди
            update_late_status(queue_id, 'rejected')
            
            # Отправляем новое сообщение вместо редактирования
            bot.send_message(
                call.message.chat.id,
                f"❌ Опоздание отклонено."
            )
        
        # Проверяем следующее опоздание в очереди
        check_and_send_next_late()
    
    except Exception as e:
        print(f"Ошибка при обработке опоздания: {e}")

# Обработчик inline-кнопок для платежей и работы
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    try:
        print(f"DEBUG: Получен callback: {call.data}")
        
        # Обработка платежей
        if call.data.startswith("pay_"):
            worker_username = call.data[4:]
            print(f"DEBUG: Обработка pay для {worker_username}")
            
            # Получаем информацию о работнике
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name, contribution FROM users WHERE username = ?", 
                (worker_username,)
            )
            result = cursor.fetchone()
            conn.close()
            
            if result:
                worker_name, contribution = result
                
                # Сохраняем информацию о том, что пользователь ожидает отправки скриншота
                if not hasattr(bot, 'waiting_for_screenshot'):
                    bot.waiting_for_screenshot = {}
                bot.waiting_for_screenshot[call.from_user.id] = worker_username
                
                # Отправляем сообщение работнику с просьбой прислать скриншот
                safe_edit_or_send_message(
                    call.message.chat.id,
                    call.message.message_id,
                    "Пришлите скриншот, подтверждающий взнос:"
                )
        
        elif call.data.startswith("suggest_work_"):
            worker_username = call.data[13:]
            print(f"DEBUG: Обработка suggest_work для {worker_username}")
            
            # Сохраняем информацию о том, что пользователь хочет предложить работу
            if not hasattr(bot, 'waiting_for_work_description'):
                bot.waiting_for_work_description = {}
            bot.waiting_for_work_description[call.from_user.id] = worker_username
            
            # Отправляем сообщение работнику с просьбой описать работу
            safe_edit_or_send_message(
                call.message.chat.id,
                call.message.message_id,
                "Опишите работу, которую вы готовы выполнить для погашения взноса:"
            )
        
        elif call.data.startswith("decline_"):
            worker_username = call.data[8:]
            print(f"DEBUG: Обработка decline для {worker_username}")
            
            # Получаем информацию о работнике
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM users WHERE username = ?", 
                (worker_username,)
            )
            result = cursor.fetchone()
            conn.close()
            
            if result:
                worker_name = result[0]
                
                # Обновляем сообщение у работника
                safe_edit_or_send_message(
                    call.message.chat.id,
                    call.message.message_id,
                    f"Хорошо, {worker_name}. Вы можете внести взнос в следующий раз."
                )
        
        elif call.data.startswith("confirm_payment_"):
            worker_username = call.data[16:]
            print(f"DEBUG: Обработка confirm_payment для {worker_username}")
            
            # Создаем клавиатуру для подтверждения
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton("Да", callback_data=f"confirm_final_{worker_username}"),
                types.InlineKeyboardButton("Нет", callback_data=f"back_to_payment_{worker_username}")
            )
            
            safe_edit_or_send_message(
                call.message.chat.id,
                call.message.message_id,
                f"Вы уверены, что хотите подтвердить взнос для {worker_username}?",
                keyboard
            )
        
        elif call.data.startswith("reject_payment_"):
            worker_username = call.data[15:]
            print(f"DEBUG: Обработка reject_payment для {worker_username}")
            
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton("Да", callback_data=f"reject_final_{worker_username}"),
                types.InlineKeyboardButton("Нет", callback_data=f"back_to_payment_{worker_username}")
            )
            
            safe_edit_or_send_message(
                call.message.chat.id,
                call.message.message_id,
                f"Вы уверены, что хотите отклонить взнос для {worker_username}?",
                keyboard
            )
        
        elif call.data.startswith("confirm_final_"):
            worker_username = call.data[14:]
            print(f"DEBUG: Обработка confirm_final для {worker_username}")
            
            # Обнуляем минуты и взнос
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET late_minutes = 0, contribution = 0 WHERE username = ?",
                (worker_username,)
            )
            conn.commit()
            
            # Получаем имя работника
            cursor.execute("SELECT name FROM users WHERE username = ?", (worker_username,))
            result = cursor.fetchone()
            conn.close()
            
            worker_name = result[0] if result else worker_username
            
            # Отправляем сообщение админу
            safe_edit_or_send_message(
                call.message.chat.id,
                call.message.message_id,
                f"Взнос на {worker_name} согласован! Минуты опоздания и взнос обнулены."
            )
            
            # Отправляем сообщение работнику
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT chat_id FROM users WHERE username = ?", (worker_username,))
            result = cursor.fetchone()
            conn.close()
            
            if result and result[0]:
                bot.send_message(
                    result[0],
                    f"Взнос на {worker_name} согласован! Минуты опоздания и взнос обнулены.",
                    reply_markup=get_main_keyboard('worker')
                )
        
        elif call.data.startswith("reject_final_"):
            worker_username = call.data[13:]
            print(f"DEBUG: Обработка reject_final для {worker_username}")
            
            # Получаем имя работника
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM users WHERE username = ?", (worker_username,))
            result = cursor.fetchone()
            conn.close()
            
            worker_name = result[0] if result else worker_username
            
            # Отправляем сообщение админу
            safe_edit_or_send_message(
                call.message.chat.id,
                call.message.message_id,
                f"Вы отклонили взнос для {worker_name}."
            )
            
            # Отправляем сообщение работнику
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT chat_id FROM users WHERE username = ?", (worker_username,))
            result = cursor.fetchone()
            conn.close()
            
            if result and result[0]:
                bot.send_message(
                    result[0],
                    "Взнос отклонён, свяжитесь с менеджером.",
                    reply_markup=get_main_keyboard('worker')
                )
        
        elif call.data.startswith("back_to_payment_"):
            worker_username = call.data[16:]
            print(f"DEBUG: Обработка back_to_payment для {worker_username}")
            
            # Возвращаем к выбору подтверждения или отклонения
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton("Подтвердить взнос", callback_data=f"confirm_payment_{worker_username}"),
                types.InlineKeyboardButton("Отклонить", callback_data=f"reject_payment_{worker_username}")
            )
            
            safe_edit_or_send_message(
                call.message.chat.id,
                call.message.message_id,
                f"Работник {worker_username} внёс баллы. Подтвердите или отклоните:",
                keyboard
            )
        
        # Обработка предложений работы
        elif call.data.startswith("approve_work_"):
            proposal_id = int(call.data[13:])
            print(f"DEBUG: Обработка approve_work для proposal_id: {proposal_id}")
            
            # Получаем информацию о предложении
            proposal = get_work_proposal(proposal_id)
            if proposal:
                worker_username = proposal[1]
                worker_name = proposal[2]
                print(f"DEBUG: Найден proposal для {worker_name}")
                
                # Отправляем сообщение с подтверждением
                safe_edit_or_send_message(
                    call.message.chat.id,
                    call.message.message_id,
                    f"Вы уверены, что хотите одобрить работу для {worker_name}?",
                    get_confirm_approve_work_keyboard(proposal_id)
                )
            else:
                print(f"DEBUG: Proposal {proposal_id} не найден")
        
        elif call.data.startswith("reject_work_"):
            proposal_id = int(call.data[12:])
            print(f"DEBUG: Обработка reject_work для proposal_id: {proposal_id}")
            
            # Получаем информацию о предложении
            proposal = get_work_proposal(proposal_id)
            if proposal:
                worker_username = proposal[1]
                worker_name = proposal[2]
                print(f"DEBUG: Найден proposal для {worker_name}")
                
                # Отправляем сообщение с подтверждением
                safe_edit_or_send_message(
                    call.message.chat.id,
                    call.message.message_id,
                    f"Вы уверены, что хотите отказать в работе для {worker_name}?",
                    get_confirm_reject_work_keyboard(proposal_id)
                )
            else:
                print(f"DEBUG: Proposal {proposal_id} не найден")
        
        elif call.data.startswith("confirm_approve_"):
            proposal_id = int(call.data[16:])
            print(f"DEBUG: Обработка confirm_approve для proposal_id: {proposal_id}")
            
            # Получаем информацию о предложении
            proposal = get_work_proposal(proposal_id)
            if proposal:
                worker_username = proposal[1]
                worker_name = proposal[2]
                print(f"DEBUG: Подтверждение одобрения для {worker_name}")
                
                # Обнуляем минуты и взнос
                conn = sqlite3.connect(DB_NAME)
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE users SET late_minutes = 0, contribution = 0 WHERE username = ?",
                    (worker_username,)
                )
                
                # Обновляем статус предложения
                cursor.execute(
                    "UPDATE work_proposals SET status = 'approved' WHERE id = ?",
                    (proposal_id,)
                )
                
                conn.commit()
                conn.close()
                
                # Отправляем сообщение админу
                safe_edit_or_send_message(
                    call.message.chat.id,
                    call.message.message_id,
                    f"Работа для {worker_name} одобрена! Минуты опоздания и взнос обнулены."
                )
                
                # Отправляем сообщение работнику
                conn = sqlite3.connect(DB_NAME)
                cursor = conn.cursor()
                cursor.execute("SELECT chat_id FROM users WHERE username = ?", (worker_username,))
                result = cursor.fetchone()
                conn.close()
                
                if result and result[0]:
                    bot.send_message(
                        result[0],
                        f"Взнос на {worker_name} согласован! Минуты опоздания и взнос обнулены.",
                        reply_markup=get_main_keyboard('worker')
                    )
            else:
                print(f"DEBUG: Proposal {proposal_id} не найден при confirm_approve")
        
        elif call.data.startswith("confirm_reject_"):
            proposal_id = int(call.data[15:])
            print(f"DEBUG: Обработка confirm_reject для proposal_id: {proposal_id}")
            
            # Получаем информацию о предложении
            proposal = get_work_proposal(proposal_id)
            if proposal:
                worker_username = proposal[1]
                worker_name = proposal[2]
                print(f"DEBUG: Подтверждение отказа для {worker_name}")
                
                # Обновляем статус предложения
                update_work_proposal_status(proposal_id, 'rejected')
                
                # Отправляем сообщение админу
                safe_edit_or_send_message(
                    call.message.chat.id,
                    call.message.message_id,
                    f"Вы отклонили предложение работы для {worker_name}."
                )
                
                # Отправляем сообщение работнику
                conn = sqlite3.connect(DB_NAME)
                cursor = conn.cursor()
                cursor.execute("SELECT chat_id FROM users WHERE username = ?", (worker_username,))
                result = cursor.fetchone()
                conn.close()
                
                if result and result[0]:
                    bot.send_message(
                        result[0],
                        "Вам отказано в погашении взноса. Попробуйте предложить другую работу или обратитесь к менеджеру",
                        reply_markup=get_main_keyboard('worker')
                    )
            else:
                print(f"DEBUG: Proposal {proposal_id} не найден при confirm_reject")
        
        elif call.data.startswith("cancel_approve_"):
            proposal_id = int(call.data[15:])
            print(f"DEBUG: Обработка cancel_approve для proposal_id: {proposal_id}")
            
            # Получаем информацию о предложении
            proposal = get_work_proposal(proposal_id)
            if proposal:
                worker_name = proposal[2]
                
                # Возвращаем к исходному сообщению
                safe_edit_or_send_message(
                    call.message.chat.id,
                    call.message.message_id,
                    f"Предложение работы от {worker_name}:\n\n{proposal[3]}",
                    get_admin_work_proposal_keyboard(proposal_id)
                )
        
        elif call.data.startswith("cancel_reject_"):
            proposal_id = int(call.data[14:])
            print(f"DEBUG: Обработка cancel_reject для proposal_id: {proposal_id}")
            
            # Получаем информацию о предложении
            proposal = get_work_proposal(proposal_id)
            if proposal:
                worker_name = proposal[2]
                
                # Возвращаем к исходному сообщению
                safe_edit_or_send_message(
                    call.message.chat.id,
                    call.message.message_id,
                    f"Предложение работы от {worker_name}:\n\n{proposal[3]}",
                    get_admin_work_proposal_keyboard(proposal_id)
                )
    
    except Exception as e:
        print(f"Ошибка при обработке callback: {e}")

# Обработчик фотографий (скриншотов) - для помощи и платежей
@bot.message_handler(content_types=['photo'])
def handle_screenshot(message):
    user_id = message.from_user.id
    
    # Проверяем, ожидаем ли мы скриншот от этого пользователя (для платежей)
    if hasattr(bot, 'waiting_for_screenshot') and user_id in bot.waiting_for_screenshot:
        worker_username = bot.waiting_for_screenshot[user_id]
        
        # Получаем информацию о работнике
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, contribution FROM users WHERE username = ?", 
            (worker_username,)
        )
        result = cursor.fetchone()
        conn.close()
        
        if result:
            worker_name, contribution = result
            
            # Отправляем сообщение админу
            admin_chat_id = get_admin_chat_id()
            if admin_chat_id:
                # Создаем inline-клавиатуру
                keyboard = types.InlineKeyboardMarkup()
                keyboard.add(
                    types.InlineKeyboardButton("Подтвердить взнос", callback_data=f"confirm_payment_{worker_username}"),
                    types.InlineKeyboardButton("Отклонить", callback_data=f"reject_payment_{worker_username}")
                )
                
                # Отправляем фото и сообщение админу
                bot.send_photo(
                    admin_chat_id,
                    message.photo[-1].file_id,
                    caption=f"Работник {worker_name} ({contribution} баллов) внёс баллы",
                    reply_markup=keyboard
                )
            
            # Отправляем сообщение работнику
            bot.send_message(
                message.chat.id,
                "Скриншот отправлен на проверку. Ожидайте подтверждения.",
                reply_markup=get_main_keyboard('worker')
            )
            
            # Удаляем информацию об ожидании скриншота
            del bot.waiting_for_screenshot[user_id]
    
    # Проверяем, ожидаем ли мы описание проблемы (для помощи)
    elif hasattr(bot, 'waiting_for_help') and user_id in bot.waiting_for_help:
        # Получаем информацию о пользователе
        username = f"@{message.from_user.username}" if message.from_user.username else None
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM users WHERE username = ?", 
            (username,)
        )
        result = cursor.fetchone()
        name = result[0] if result else "Неизвестный"
        conn.close()
        
        # Сохраняем запрос помощи в базу данных
        help_text = message.caption if message.caption else "Пользователь отправил скриншот без описания"
        save_help_request(user_id, username, name, help_text)
        
        # Получаем chat_id админа
        admin_chat_id = get_admin_chat_id()
        
        if admin_chat_id:
            try:
                # Отправляем фото админу
                bot.send_photo(
                    admin_chat_id,
                    message.photo[-1].file_id,
                    caption=f"🚨 ЗАПРОС ПОМОЩИ\n\nОт: {name}\nUsername: {username}\nID: {user_id}\n\nОписание: {help_text}"
                )
                
                # Отправляем сообщение пользователю
                role = get_user_role(username) if username else 'worker'
                bot.send_message(
                    message.chat.id,
                    "Ваш запрос помощи отправлен разработчику. Спасибо за обращение!",
                    reply_markup=get_main_keyboard(role)
                )
                
            except Exception as e:
                print(f"Ошибка при отправке фото админу: {e}")
                # Если не удалось отправить админу, сообщаем пользователю
                bot.send_message(
                    message.chat.id,
                    "Не удалось отправить запрос помощи. Попробуйте позже.",
                    reply_markup=get_main_keyboard(get_user_role(username) if username else 'worker')
                )
        else:
            # Если chat_id админа не найден, сообщаем пользователю
            bot.send_message(
                message.chat.id,
                "Администратор не найден в системе. Обратитесь к менеджеру напрямую.",
                reply_markup=get_main_keyboard(get_user_role(username) if username else 'worker')
            )
        
        # Удаляем информацию об ожидании помощи
        if user_id in bot.waiting_for_help:
            del bot.waiting_for_help[user_id]

# Обработчик текстовых сообщений для описания работы
@bot.message_handler(func=lambda message: hasattr(bot, 'waiting_for_work_description') and message.from_user.id in bot.waiting_for_work_description)
def handle_work_description(message):
    user_id = message.from_user.id
    
    if user_id in bot.waiting_for_work_description:
        worker_username = bot.waiting_for_work_description[user_id]
        
        # Получаем информацию о работнике
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM users WHERE username = ?", 
            (worker_username,)
        )
        result = cursor.fetchone()
        conn.close()
        
        if result:
            worker_name = result[0]
            work_description = message.text
            
            # Получаем chat_id админа
            admin_chat_id = get_admin_chat_id()
            
            if admin_chat_id:
                # Сохраняем предложение работы в базу данных
                proposal_id = save_work_proposal(worker_username, worker_name, work_description, admin_chat_id)
                print(f"DEBUG: Сохранено предложение работы с ID: {proposal_id}")
                
                # Отправляем предложение админу
                bot.send_message(
                    admin_chat_id,
                    f"Работник {worker_name} предложил работу для погашения взноса:\n\n{work_description}",
                    reply_markup=get_admin_work_proposal_keyboard(proposal_id)
                )
            
            # Отправляем сообщение работнику
            bot.send_message(
                message.chat.id,
                "Ваше предложение отправлено администратору. Ожидайте решения.",
                reply_markup=get_main_keyboard('worker')
            )
            
            # Удаляем информацию об ожидании описания работы
            del bot.waiting_for_work_description[user_id]

# Обработчик текстовых сообщений для запросов помощи
@bot.message_handler(func=lambda message: hasattr(bot, 'waiting_for_help') and message.from_user.id in bot.waiting_for_help)
def handle_help_text(message):
    user_id = message.from_user.id
    
    if user_id in bot.waiting_for_help:
        # Получаем информацию о пользователе
        username = f"@{message.from_user.username}" if message.from_user.username else None
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM users WHERE username = ?", 
            (username,)
        )
        result = cursor.fetchone()
        name = result[0] if result else "Неизвестный"
        conn.close()
        
        # Сохраняем запрос помощи в базу данных
        save_help_request(user_id, username, name, message.text)
        
        # Получаем chat_id админа
        admin_chat_id = get_admin_chat_id()
        
        if admin_chat_id:
            try:
                bot.send_message(
                    admin_chat_id,
                    f"🚨 ЗАПРОС ПОМОЩИ\n\nОт: {name}\nUsername: {username}\nID: {user_id}\n\nОписание проблемы:\n{message.text}"
                )
                
                # Отправляем сообщение пользователю
                role = get_user_role(username) if username else 'worker'
                bot.send_message(
                    message.chat.id,
                    "Ваш запрос помощи отправлен разработчику. Спасибо за обращение!",
                    reply_markup=get_main_keyboard(role)
                )
                
            except Exception as e:
                print(f"Ошибка при отправке сообщения админу: {e}")
                # Если не удалось отправить админу, сообщаем пользователю
                bot.send_message(
                    message.chat.id,
                    "Не удалось отправить запрос помощи. Попробуйте позже.",
                    reply_markup=get_main_keyboard(get_user_role(username) if username else 'worker')
                )
        else:
            # Если chat_id админа не найден, сообщаем пользователю
            bot.send_message(
                message.chat.id,
                "Администратор не найден в системе. Обратитесь к менеджеру напрямую.",
                reply_markup=get_main_keyboard(get_user_role(username) if username else 'worker')
            )
        
        # Удаляем информацию об ожидании помощи
        if user_id in bot.waiting_for_help:
            del bot.waiting_for_help[user_id]

# Функция для периодической проверки даты и времени уведомления
def notification_checker():
    while True:
        try:
            send_contribution_notifications()
        except Exception as e:
            print(f"Ошибка при отправке уведомлений: {e}")
        
        # Проверяем раз в минуту
        time.sleep(60)

# Обработчик неизвестных команд
@bot.message_handler(func=lambda message: True)
def unknown(message):
    username = message.from_user.username
    role = get_user_role(f"@{username}") if username else None
    
    if role:
        bot.reply_to(message, "Неизвестная команда", reply_markup=get_main_keyboard(role))
    else:
        bot.reply_to(message, "Неизвестная команда")

if __name__ == '__main__':
    print("Инициализация базы данных...")
    init_db()
    update_contributions()  # Обновляем взносы при запуске
    
    # Запускаем поток для проверки уведомлений
    notification_thread = threading.Thread(target=notification_checker)
    notification_thread.daemon = True
    notification_thread.start()
    
    print("Бот запускается...")
    bot.infinity_polling()
