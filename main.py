import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
from datetime import datetime, timedelta
import re
import asyncio
import traceback

# Настройки бота
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # ВАЖНО: нужно для работы с ролями и участниками
bot = commands.Bot(command_prefix='!', intents=intents)

# Файлы для хранения данных
DATA_FILE = 'events.json'
SETTINGS_FILE = 'settings.json'

# Настройки
DELETE_AFTER_HOURS = 18
MAX_EVENTS_PER_GUILD = 100
EVENTS_PER_PAGE = 10

# Название роли для упоминания в напоминаниях
MENTION_ROLE_NAME = "Участник ST-9"

# Название роли, у которой есть доступ к командам
ACCESS_ROLE_NAME = "Ком состав"

# Интервалы напоминаний (в минутах до события)
REMINDER_TIMES = [
    (3 * 24 * 60+180, "3 дня"),
    (24 * 60+180, "24 часа"),
    (12 * 60+180, "12 часов"),
    (3 * 60+180, "3 часа"),
    (60+180, "1 час"),
    (30+180, "30 минут"),
    (10+180, "10 минут"),
    (0+180, "время начала")
]

# ==================== ФУНКЦИИ РАБОТЫ С ФАЙЛАМИ ====================

def load_events():
    """Загружает события из файла"""
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    data = json.loads(content)
                    if isinstance(data, dict):
                        return data
                return {}
        return {}
    except json.JSONDecodeError as e:
        print(f"Ошибка чтения JSON: {e}")
        if os.path.exists(DATA_FILE):
            backup_file = f"{DATA_FILE}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            try:
                os.rename(DATA_FILE, backup_file)
                print(f"Поврежденный файл сохранен как {backup_file}")
            except:
                pass
        return {}
    except Exception as e:
        print(f"Ошибка загрузки: {e}")
        return {}

def save_events(events):
    """Сохраняет события в файл"""
    try:
        if not isinstance(events, dict):
            events = {}
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(events, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"Ошибка сохранения: {e}")
        return False

def load_settings():
    """Загружает настройки серверов"""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    data = json.loads(content)
                    if isinstance(data, dict):
                        return data
                return {}
        return {}
    except Exception as e:
        print(f"Ошибка загрузки настроек: {e}")
        return {}

def save_settings(settings):
    """Сохраняет настройки серверов"""
    try:
        if not isinstance(settings, dict):
            settings = {}
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"Ошибка сохранения настроек: {e}")
        return False

# ==================== ПРОВЕРКА ПРАВ ====================

def has_access_role(member):
    """Проверяет, есть ли у участника роль доступа"""
    if not isinstance(member, discord.Member):
        return False
    
    # Администраторы всегда имеют доступ
    if member.guild_permissions.administrator:
        return True
    
    # Проверяем наличие роли по названию
    for role in member.roles:
        if role.name.lower() == ACCESS_ROLE_NAME.lower():
            return True
        # Частичное совпадение
        if ACCESS_ROLE_NAME.lower() in role.name.lower():
            return True
    
    return False

def access_check():
    """Декоратор для проверки прав доступа"""
    async def predicate(interaction: discord.Interaction):
        if not has_access_role(interaction.user):
            raise app_commands.CheckFailure(
                f"❌ У вас нет роли **{ACCESS_ROLE_NAME}** для использования этой команды"
            )
        return True
    return app_commands.check(predicate)

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def get_next_event_number(events, guild_id):
    """Получает следующий номер события"""
    try:
        guild_id_str = str(guild_id)
        if guild_id_str not in events:
            return 1
        guild_events = events[guild_id_str]
        if not guild_events:
            return 1
        numbers = []
        for key in guild_events.keys():
            try:
                numbers.append(int(key))
            except:
                pass
        return max(numbers) + 1 if numbers else 1
    except:
        return 1

def validate_date(date_str):
    """Проверяет корректность даты"""
    if not date_str:
        return False, "Дата не может быть пустой"
    pattern = r'^(\d{2})\.(\d{2})$'
    match = re.match(pattern, date_str)
    if not match:
        return False, "Неверный формат даты. Используйте ДД.ММ"
    day, month = int(match.group(1)), int(match.group(2))
    if month < 1 or month > 12:
        return False, "Неверный месяц"
    days_in_month = {1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30,
                     7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}
    if day < 1 or day > days_in_month[month]:
        return False, f"Неверный день для месяца {month}"
    return True, ""

def validate_time(time_str):
    """Проверяет корректность времени"""
    if not time_str:
        return False, "Время не может быть пустым"
    pattern = r'^(\d{1,2})[:：\-](\d{2})$'
    match = re.match(pattern, time_str)
    if not match:
        return False, "Неверный формат времени. Используйте ЧЧ:ММ или ЧЧ-ММ"
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour < 0 or hour > 23:
        return False, "Неверный час"
    if minute < 0 or minute > 59:
        return False, "Неверные минуты"
    return True, ""

def format_date_display(date_str):
    """Форматирует дату для отображения"""
    months = {1: "января", 2: "февраля", 3: "марта", 4: "апреля",
              5: "мая", 6: "июня", 7: "июля", 8: "августа",
              9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"}
    try:
        day, month = date_str.split('.')
        return f"{int(day)} {months[int(month)]}"
    except:
        return date_str

def format_time_display(time_str):
    """Форматирует время для отображения"""
    try:
        time_str = time_str.replace('-', ':').replace('：', ':')
        hour, minute = time_str.split(':')
        return f"{int(hour):02d}:{minute}"
    except:
        return time_str

def get_event_datetime(event_data, year=None):
    """Получает объект datetime для события"""
    try:
        day, month = map(int, event_data['date'].split('.'))
        hour, minute = map(int, event_data['time'].split(':'))
        if year is None:
            year = datetime.now().year
        return datetime(year, month, day, hour, minute)
    except:
        return None

def sort_events_by_date(events_dict):
    """Сортирует события по дате и времени"""
    def get_sort_key(item):
        try:
            event_data = item[1]
            date_parts = event_data['date'].split('.')
            time_parts = event_data['time'].split(':')
            return (int(date_parts[1]), int(date_parts[0]),
                    int(time_parts[0]), int(time_parts[1]))
        except:
            return (99, 99, 99, 99)
    return sorted(events_dict.items(), key=get_sort_key)

def get_reminder_color(reminder_label):
    """Возвращает цвет для напоминания"""
    colors = {
        "3 дня": discord.Color.blue(),
        "24 часа": discord.Color.teal(),
        "12 часов": discord.Color.green(),
        "3 часа": discord.Color.gold(),
        "1 час": discord.Color.orange(),
        "30 минут": discord.Color.red(),
        "10 минут": discord.Color.dark_red(),
        "время начала": discord.Color.purple()
    }
    return colors.get(reminder_label, discord.Color.blue())

def get_reminder_channel(guild, settings, guild_id):
    """Получает канал для отправки напоминаний"""
    guild_id_str = str(guild_id)
    
    if guild_id_str in settings and 'reminder_channel_id' in settings[guild_id_str]:
        channel_id = settings[guild_id_str]['reminder_channel_id']
        channel = guild.get_channel(channel_id)
        if channel and channel.permissions_for(guild.me).send_messages:
            return channel
        else:
            print(f"⚠️ Настроенный канал {channel_id} недоступен")
    
    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).send_messages:
            return channel
    
    return None

def find_role_by_name(guild, role_name):
    """Находит роль по названию"""
    # Точное совпадение
    for role in guild.roles:
        if role.name.lower() == role_name.lower():
            return role
    # Частичное совпадение
    for role in guild.roles:
        if role_name.lower() in role.name.lower():
            return role
    return None

def find_mention_role(guild):
    """Находит роль для упоминания"""
    return find_role_by_name(guild, MENTION_ROLE_NAME)

async def send_reminder(channel, guild, event_number, event_data, reminder_label):
    """Отправляет напоминание о событии с упоминанием роли"""
    try:
        embed = discord.Embed(
            title="⏰ НАПОМИНАНИЕ О СОБЫТИИ",
            color=get_reminder_color(reminder_label)
        )
        
        embed.add_field(name="📅 Дата", value=f"**{event_data.get('date_formatted', event_data['date'])}**", inline=True)
        embed.add_field(name="⏰ Время", value=f"**{event_data['time']}**", inline=True)
        embed.add_field(name="📝 Описание", value=f"**{event_data['description']}**", inline=False)
        embed.add_field(name="👤 Автор", value=f"**{event_data['author']}**", inline=True)
        embed.add_field(name="⏳ До события", value=f"**{reminder_label}**", inline=True)
        
        mentions = []
        
        role = find_mention_role(guild)
        if role:
            if role.mentionable:
                mentions.append(role.mention)
            else:
                mentions.append(f"**@{role.name}**")
        else:
            print(f"⚠️ Роль '{MENTION_ROLE_NAME}' не найдена на сервере {guild.name}")
        
        author_id = event_data.get('author_id')
        if author_id:
            mentions.append(f"<@{author_id}>")
        
        mention_text = " ".join(mentions) if mentions else ""
        content = f"{mention_text}\n🔔 **Напоминание о событии #{event_number}**"
        
        await channel.send(content=content, embed=embed)
        print(f"✅ Отправлено напоминание за {reminder_label} для события #{event_number}")
        
    except Exception as e:
        print(f"Ошибка отправки напоминания: {e}")
        traceback.print_exc()

# ==================== СОБЫТИЯ БОТА ====================

@bot.event
async def on_ready():
    print(f'✅ {bot.user} подключился к Discord!')
    print(f'ID бота: {bot.user.id}')
    
    if not reminder_task.is_running():
        reminder_task.start()
        print("✅ Задача напоминаний запущена")
    
    if not cleanup_task.is_running():
        cleanup_task.start()
        print("✅ Задача очистки запущена")
    
    # Проверяем наличие ролей на всех серверах
    for guild in bot.guilds:
        access_role = find_role_by_name(guild, ACCESS_ROLE_NAME)
        mention_role = find_role_by_name(guild, MENTION_ROLE_NAME)
        
        print(f"\n📋 Сервер: {guild.name}")
        if access_role:
            print(f"  ✅ Роль доступа '{access_role.name}' найдена")
        else:
            print(f"  ⚠️ Роль доступа '{ACCESS_ROLE_NAME}' НЕ найдена (только админы)")
        
        if mention_role:
            print(f"  ✅ Роль упоминания '{mention_role.name}' найдена")
        else:
            print(f"  ⚠️ Роль упоминания '{MENTION_ROLE_NAME}' НЕ найдена")
    
    try:
        synced = await bot.tree.sync()
        print(f"\n✅ Синхронизировано {len(synced)} слэш-команд")
    except Exception as e:
        print(f"❌ Ошибка синхронизации: {e}")
    
    print('------')

# ==================== ФОНОВЫЕ ЗАДАЧИ ====================

@tasks.loop(minutes=1)
async def reminder_task():
    """Проверяет и отправляет напоминания"""
    try:
        events = load_events()
        settings = load_settings()
        
        if not events:
            return
        
        current_time = datetime.now()
        changed = False
        
        for guild_id, guild_events in events.items():
            if not guild_events:
                continue
            
            guild = bot.get_guild(int(guild_id))
            if not guild:
                continue
            
            channel = get_reminder_channel(guild, settings, guild_id)
            if not channel:
                continue
            
            for event_number, event_data in guild_events.items():
                if 'reminders_sent' not in event_data:
                    event_data['reminders_sent'] = []
                    changed = True
                
                event_time = get_event_datetime(event_data, current_time.year)
                if event_time is None:
                    continue
                
                if event_time < current_time and current_time.month > 10 and event_time.month < 3:
                    event_time = get_event_datetime(event_data, current_time.year + 1)
                
                time_diff = event_time - current_time
                minutes_until_event = time_diff.total_seconds() / 60
                
                for reminder_minutes, reminder_label in REMINDER_TIMES:
                    if (reminder_minutes - 1 < minutes_until_event <= reminder_minutes and 
                        reminder_label not in event_data['reminders_sent']):
                        
                        await send_reminder(channel, guild, event_number, event_data, reminder_label)
                        event_data['reminders_sent'].append(reminder_label)
                        changed = True
        
        if changed:
            save_events(events)
        
    except Exception as e:
        print(f"Ошибка в reminder_task: {e}")
        traceback.print_exc()

@tasks.loop(hours=1)
async def cleanup_task():
    """Автоматически удаляет старые события"""
    try:
        events = load_events()
        if not events:
            return
        
        current_time = datetime.now()
        changed = False
        
        for guild_id, guild_events in events.items():
            if not guild_events:
                continue
            
            events_to_delete = []
            for event_number, event_data in guild_events.items():
                event_time = get_event_datetime(event_data, current_time.year)
                if event_time and event_time < current_time:
                    time_diff = current_time - event_time
                    if time_diff > timedelta(hours=DELETE_AFTER_HOURS):
                        events_to_delete.append(event_number)
            
            for event_number in events_to_delete:
                del guild_events[event_number]
                changed = True
                print(f"🗑️ Удалено событие #{event_number} с сервера {guild_id}")
        
        if changed:
            save_events(events)
            
    except Exception as e:
        print(f"Ошибка в cleanup_task: {e}")

@reminder_task.before_loop
async def before_reminder_task():
    await bot.wait_until_ready()

@cleanup_task.before_loop
async def before_cleanup_task():
    await bot.wait_until_ready()

# ==================== ГРУППА КОМАНД: СОБЫТИЯ ====================

class EventCommands(app_commands.Group):
    def __init__(self):
        super().__init__(name="event", description="Управление событиями")

    @app_commands.command(name="add", description="Добавить новое событие (только Ком Состав)")
    @app_commands.describe(
        description="Описание события",
        date="Дата в формате ДД.ММ (например, 25.12)",
        time="Время в формате ЧЧ:ММ (например, 15:30)"
    )
    @access_check()
    async def add_event(self, interaction: discord.Interaction, description: str, date: str, time: str):
        """Добавляет новое событие"""
        try:
            is_valid_date, date_error = validate_date(date)
            if not is_valid_date:
                await interaction.response.send_message(f"❌ {date_error}", ephemeral=True)
                return
            
            is_valid_time, time_error = validate_time(time)
            if not is_valid_time:
                await interaction.response.send_message(f"❌ {time_error}", ephemeral=True)
                return
            
            events = load_events()
            guild_id = str(interaction.guild.id)
            
            if guild_id not in events:
                events[guild_id] = {}
            
            if len(events[guild_id]) >= MAX_EVENTS_PER_GUILD:
                await interaction.response.send_message(
                    f"⚠️ Достигнут лимит в {MAX_EVENTS_PER_GUILD} событий", ephemeral=True
                )
                return
            
            event_number = get_next_event_number(events, guild_id)
            normalized_time = format_time_display(time)
            
            events[guild_id][str(event_number)] = {
                'description': description,
                'date': date,
                'date_formatted': format_date_display(date),
                'time': normalized_time,
                'author': str(interaction.user),
                'author_id': interaction.user.id,
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'reminders_sent': []
            }
            
            save_events(events)
            
            role = find_mention_role(interaction.guild)
            role_status = f"✅ {role.mention}" if role else f"⚠️ Роль '{MENTION_ROLE_NAME}' не найдена"
            
            embed = discord.Embed(
                title="✅ Событие добавлено",
                description=f"**Номер:** {event_number}\n"
                          f"**Дата:** {format_date_display(date)}\n"
                          f"**Время:** {normalized_time}\n"
                          f"**Описание:** {description}\n\n"
                          f"🔔 **Напоминания будут отправлены:**\n"
                          f"• За 3 дня, 24 часа, 12 часов\n"
                          f"• За 3 часа, 1 час, 30 минут\n"
                          f"• За 10 минут и в момент начала\n\n"
                          f"👥 **Роль для упоминания:** {role_status}",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            print(f"Ошибка в add_event: {e}")
            traceback.print_exc()
            await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)

    @app_commands.command(name="list", description="Показать все события (только Ком Состав)")
    @app_commands.describe(page="Номер страницы")
    @access_check()
    async def list_events(self, interaction: discord.Interaction, page: int = 1):
        """Показывает все события"""
        try:
            events = load_events()
            guild_id = str(interaction.guild.id)
            
            if guild_id not in events or not events[guild_id]:
                await interaction.response.send_message("📋 Нет сохраненных событий", ephemeral=True)
                return
            
            sorted_events = sort_events_by_date(events[guild_id])
            total_events = len(sorted_events)
            total_pages = max(1, (total_events + EVENTS_PER_PAGE - 1) // EVENTS_PER_PAGE)
            
            if page < 1:
                page = 1
            elif page > total_pages:
                page = total_pages
            
            start_idx = (page - 1) * EVENTS_PER_PAGE
            end_idx = min(start_idx + EVENTS_PER_PAGE, total_events)
            page_events = sorted_events[start_idx:end_idx]
            
            embed = discord.Embed(
                title="📋 Список событий",
                description=f"Страница **{page}/{total_pages}** | Всего: **{total_events}**",
                color=discord.Color.blue()
            )
            
            for number, event_data in page_events:
                reminders_count = len(event_data.get('reminders_sent', []))
                embed.add_field(
                    name=f"📌 Событие #{number}",
                    value=f"**Дата:** {event_data.get('date_formatted', event_data['date'])}\n"
                          f"**Время:** {event_data['time']}\n"
                          f"**Описание:** {event_data['description']}\n"
                          f"**Напоминания:** {reminders_count}/{len(REMINDER_TIMES)}",
                    inline=False
                )
            
            embed.set_footer(text=f"Страница {page} из {total_pages}")
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            print(f"Ошибка в list_events: {e}")
            await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)

    @app_commands.command(name="upcoming", description="Показать ближайшие события (только Ком Состав)")
    @access_check()
    async def upcoming_events(self, interaction: discord.Interaction):
        """Показывает ближайшие события"""
        try:
            events = load_events()
            guild_id = str(interaction.guild.id)
            
            if guild_id not in events or not events[guild_id]:
                await interaction.response.send_message("📋 Нет сохраненных событий", ephemeral=True)
                return
            
            now = datetime.now()
            sorted_events = sort_events_by_date(events[guild_id])
            
            embed = discord.Embed(
                title="📅 Ближайшие события",
                color=discord.Color.orange()
            )
            
            events_added = 0
            for number, event_data in sorted_events:
                event_time = get_event_datetime(event_data, now.year)
                if event_time and event_time >= now and events_added < 15:
                    time_diff = event_time - now
                    days = time_diff.days
                    hours = time_diff.seconds // 3600
                    minutes = (time_diff.seconds % 3600) // 60
                    
                    if days > 0:
                        time_left = f"через {days} дн. {hours} ч."
                    elif hours > 0:
                        time_left = f"через {hours} ч. {minutes} мин."
                    else:
                        time_left = f"через {minutes} мин."
                    
                    embed.add_field(
                        name=f"📌 #{number} | {event_data['date']} в {event_data['time']}",
                        value=f"**{event_data['description']}**\n⏳ {time_left}",
                        inline=False
                    )
                    events_added += 1
            
            if events_added == 0:
                embed.description = "Нет предстоящих событий"
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            print(f"Ошибка в upcoming_events: {e}")
            await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)

    @app_commands.command(name="info", description="Показать информацию о событии (только Ком Состав)")
    @app_commands.describe(number="Номер события")
    @access_check()
    async def show_info(self, interaction: discord.Interaction, number: int):
        """Показывает информацию о событии"""
        try:
            events = load_events()
            guild_id = str(interaction.guild.id)
            
            if guild_id not in events:
                await interaction.response.send_message("❌ Нет событий", ephemeral=True)
                return
            
            event_key = str(number)
            if event_key not in events[guild_id]:
                await interaction.response.send_message(f"❌ Событие {number} не найдено", ephemeral=True)
                return
            
            event_data = events[guild_id][event_key]
            
            event_time = get_event_datetime(event_data)
            now = datetime.now()
            time_diff = event_time - now if event_time else None
            
            embed = discord.Embed(
                title=f"📌 Информация о событии #{number}",
                color=discord.Color.gold()
            )
            embed.add_field(name="📅 Дата", value=f"**{event_data.get('date_formatted', event_data['date'])}**", inline=True)
            embed.add_field(name="⏰ Время", value=f"**{event_data['time']}**", inline=True)
            embed.add_field(name="📝 Описание", value=f"**{event_data['description']}**", inline=False)
            embed.add_field(name="👤 Автор", value=f"**{event_data['author']}**", inline=True)
            
            reminders_sent = event_data.get('reminders_sent', [])
            embed.add_field(
                name="🔔 Напоминания",
                value=f"**{len(reminders_sent)}/{len(REMINDER_TIMES)}**",
                inline=True
            )
            
            if time_diff and time_diff.total_seconds() > 0:
                days = time_diff.days
                hours = time_diff.seconds // 3600
                minutes = (time_diff.seconds % 3600) // 60
                embed.add_field(
                    name="⏳ До события",
                    value=f"**{days} дн. {hours} ч. {minutes} мин.**",
                    inline=False
                )
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            print(f"Ошибка в show_info: {e}")
            await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)

    @app_commands.command(name="delete", description="Удалить событие (только Ком Состав)")
    @app_commands.describe(number="Номер события")
    @access_check()
    async def delete_event(self, interaction: discord.Interaction, number: int):
        """Удаляет событие"""
        try:
            events = load_events()
            guild_id = str(interaction.guild.id)
            
            if guild_id not in events:
                await interaction.response.send_message("❌ Нет событий", ephemeral=True)
                return
            
            event_key = str(number)
            if event_key not in events[guild_id]:
                await interaction.response.send_message(f"❌ Событие {number} не найдено", ephemeral=True)
                return
            
            deleted = events[guild_id].pop(event_key)
            save_events(events)
            
            embed = discord.Embed(
                title="🗑️ Событие удалено",
                description=f"**Номер:** {number}\n"
                          f"**Дата:** {deleted.get('date_formatted', deleted['date'])}\n"
                          f"**Время:** {deleted['time']}\n"
                          f"**Описание:** {deleted['description']}",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            print(f"Ошибка в delete_event: {e}")
            await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)

    @app_commands.command(name="clear", description="Удалить все события (только Ком Состав)")
    @access_check()
    async def clear_events(self, interaction: discord.Interaction):
        """Удаляет все события"""
        try:
            events = load_events()
            guild_id = str(interaction.guild.id)
            events[guild_id] = {}
            save_events(events)
            
            await interaction.response.send_message("✅ Все события удалены")
            
        except Exception as e:
            print(f"Ошибка в clear_events: {e}")
            await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)

# ==================== ГРУППА КОМАНД: НАСТРОЙКИ ====================

class SettingsCommands(app_commands.Group):
    def __init__(self):
        super().__init__(name="settings", description="Настройки бота")

    @app_commands.command(name="set_channel", description="Установить канал для напоминаний (только Ком Состав)")
    @app_commands.describe(channel="Канал для отправки напоминаний")
    @access_check()
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Устанавливает канал для напоминаний"""
        try:
            if not channel.permissions_for(interaction.guild.me).send_messages:
                await interaction.response.send_message(
                    f"❌ У бота нет прав на отправку сообщений в {channel.mention}", ephemeral=True
                )
                return
            
            settings = load_settings()
            guild_id = str(interaction.guild.id)
            
            if guild_id not in settings:
                settings[guild_id] = {}
            
            settings[guild_id]['reminder_channel_id'] = channel.id
            save_settings(settings)
            
            embed = discord.Embed(
                title="✅ Канал настроен",
                description=f"Напоминания будут отправляться в {channel.mention}",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            print(f"Ошибка в set_channel: {e}")
            await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)

    @app_commands.command(name="show", description="Показать текущие настройки (только Ком Состав)")
    @access_check()
    async def show_settings(self, interaction: discord.Interaction):
        """Показывает текущие настройки"""
        try:
            settings = load_settings()
            guild_id = str(interaction.guild.id)
            
            embed = discord.Embed(
                title="⚙️ Настройки бота",
                color=discord.Color.blue()
            )
            
            # Канал напоминаний
            if guild_id in settings and 'reminder_channel_id' in settings[guild_id]:
                channel_id = settings[guild_id]['reminder_channel_id']
                channel = interaction.guild.get_channel(channel_id)
                
                if channel:
                    embed.add_field(
                        name="📢 Канал напоминаний",
                        value=channel.mention,
                        inline=False
                    )
                else:
                    embed.add_field(
                        name="📢 Канал напоминаний",
                        value=f"⚠️ Канал не найден (ID: {channel_id})",
                        inline=False
                    )
            else:
                embed.add_field(
                    name="📢 Канал напоминаний",
                    value="⚠️ Не настроен\n*Используется первый доступный канал*\n\n"
                          "Используйте `/settings set_channel` для настройки",
                    inline=False
                )
            
            # Роль для упоминания
            mention_role = find_mention_role(interaction.guild)
            if mention_role:
                embed.add_field(
                    name="👥 Роль для упоминания",
                    value=f"{mention_role.mention} (`{mention_role.name}`)",
                    inline=False
                )
            else:
                embed.add_field(
                    name="👥 Роль для упоминания",
                    value=f"⚠️ Роль **{MENTION_ROLE_NAME}** не найдена",
                    inline=False
                )
            
            # Роль доступа
            access_role = find_role_by_name(interaction.guild, ACCESS_ROLE_NAME)
            if access_role:
                embed.add_field(
                    name="🔐 Роль доступа",
                    value=f"{access_role.mention} (`{access_role.name}`)",
                    inline=False
                )
            else:
                embed.add_field(
                    name="🔐 Роль доступа",
                    value=f"⚠️ Роль **{ACCESS_ROLE_NAME}** не найдена\n*Только администраторы могут использовать команды*",
                    inline=False
                )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)

    @app_commands.command(name="reset_channel", description="Сбросить настройку канала (только Ком Состав)")
    @access_check()
    async def reset_channel(self, interaction: discord.Interaction):
        """Сбрасывает настройку канала"""
        try:
            settings = load_settings()
            guild_id = str(interaction.guild.id)
            
            if guild_id in settings and 'reminder_channel_id' in settings[guild_id]:
                del settings[guild_id]['reminder_channel_id']
                save_settings(settings)
                
                embed = discord.Embed(
                    title="✅ Настройка сброшена",
                    description="Напоминания будут отправляться в первый доступный канал",
                    color=discord.Color.green()
                )
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message("ℹ️ Канал не был настроен", ephemeral=True)
                
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)

    @app_commands.command(name="check_role", description="Проверить роли на сервере (только Ком Состав)")
    @access_check()
    async def check_role(self, interaction: discord.Interaction):
        """Проверяет наличие ролей на сервере"""
        try:
            embed = discord.Embed(
                title="🔍 Проверка ролей",
                color=discord.Color.blue()
            )
            
            # Роль доступа
            access_role = find_role_by_name(interaction.guild, ACCESS_ROLE_NAME)
            if access_role:
                embed.add_field(
                    name=f"🔐 Роль доступа `{ACCESS_ROLE_NAME}`",
                    value=f"✅ Найдена: {access_role.mention}\n"
                          f"**ID:** {access_role.id}\n"
                          f"**Участников:** {len(access_role.members)}",
                    inline=False
                )
            else:
                embed.add_field(
                    name=f"🔐 Роль доступа `{ACCESS_ROLE_NAME}`",
                    value=f"❌ Не найдена на сервере\n"
                          f"*Только администраторы смогут использовать команды*",
                    inline=False
                )
            
            # Роль упоминания
            mention_role = find_mention_role(interaction.guild)
            if mention_role:
                embed.add_field(
                    name=f"👥 Роль упоминания `{MENTION_ROLE_NAME}`",
                    value=f"✅ Найдена: {mention_role.mention}\n"
                          f"**ID:** {mention_role.id}\n"
                          f"**Упоминаемая:** {'✅ Да' if mention_role.mentionable else '❌ Нет'}\n"
                          f"**Участников:** {len(mention_role.members)}",
                    inline=False
                )
                
                if not mention_role.mentionable:
                    embed.add_field(
                        name="⚠️ Важно",
                        value="Роль не является упоминаемой. Включите **'Упоминать эту роль'** "
                              "в настройках роли, чтобы упоминания работали корректно.",
                        inline=False
                    )
            else:
                embed.add_field(
                    name=f"👥 Роль упоминания `{MENTION_ROLE_NAME}`",
                    value=f"❌ Не найдена на сервере\n"
                          f"*В напоминаниях не будет упоминаний*",
                    inline=False
                )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)

# ==================== КОМАНДА ПОМОЩИ ====================

@bot.tree.command(name="ev_help", description="Показать список всех команд бота")
async def ev_help_command(interaction: discord.Interaction):
    """Показывает список всех команд"""
    embed = discord.Embed(
        title="📚 Список команд бота",
        description="**Все доступные команды:**",
        color=discord.Color.purple()
    )
    
    # Проверяем, есть ли у пользователя роль доступа
    has_access = has_access_role(interaction.user)
    access_status = "✅ У вас есть доступ" if has_access else f"❌ Требуется роль **{ACCESS_ROLE_NAME}**"
    
    embed.add_field(
        name="🔐 Ваш доступ",
        value=access_status,
        inline=False
    )
    
    embed.add_field(
        name="📅 Управление событиями",
        value="**/event add** — Добавить событие\n"
              "`описание` `дата` `время`\n\n"
              "**/event list** — Показать все события\n"
              "`страница` (опционально)\n\n"
              "**/event upcoming** — Ближайшие события\n\n"
              "**/event info** — Информация о событии\n"
              "`номер`\n\n"
              "**/event delete** — Удалить событие\n"
              "`номер`\n\n"
              "**/event clear** — Удалить все события",
        inline=False
    )
    
    embed.add_field(
        name="⚙️ Настройки",
        value="**/settings set_channel** — Установить канал напоминаний\n"
              "`канал`\n\n"
              "**/settings show** — Показать текущие настройки\n\n"
              "**/settings reset_channel** — Сбросить настройку канала\n\n"
              "**/settings check_role** — Проверить роли на сервере",
        inline=False
    )
    
    embed.add_field(
        name="📝 Форматы",
        value="**Дата:** `ДД.ММ` (например, `25.12`)\n"
              "**Время:** `ЧЧ:ММ` или `ЧЧ-ММ` (например, `15:30`)",
        inline=False
    )
    
    embed.add_field(
        name="🔔 Напоминания",
        value="За **3 дня**, **24ч**, **12ч**, **3ч**, **1ч**, **30мин**, **10мин** и в **момент начала**",
        inline=False
    )
    
    embed.add_field(
        name="🔐 Доступ к командам",
        value=f"Команды доступны только роли **{ACCESS_ROLE_NAME}** и администраторам",
        inline=False
    )
    
    embed.add_field(
        name="👥 Упоминание в напоминаниях",
        value=f"Роль **{MENTION_ROLE_NAME}**",
        inline=False
    )
    
    embed.add_field(
        name="🗑️ Автоудаление",
        value=f"События удаляются через **{DELETE_AFTER_HOURS} часов** после прохождения",
        inline=False
    )
    
    embed.set_footer(text="Бот для управления событиями")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ==================== РЕГИСТРАЦИЯ КОМАНД ====================

bot.tree.add_command(EventCommands())
bot.tree.add_command(SettingsCommands())

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    """Обработка ошибок команд"""
    try:
        if isinstance(error, app_commands.CheckFailure):
            # Ошибка проверки прав
            embed = discord.Embed(
                title="🔐 Доступ запрещён",
                description=f"{error}",
                color=discord.Color.red()
            )
            embed.add_field(
                name="💡 Что делать?",
                value=f"Обратитесь к администрации сервера для получения роли **{ACCESS_ROLE_NAME}**",
                inline=False
            )
            
            try:
                await interaction.response.send_message(embed=embed, ephemeral=True)
            except:
                await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            print(f"Ошибка команды: {error}")
            traceback.print_exc()
            try:
                await interaction.response.send_message(f"❌ Ошибка: {error}", ephemeral=True)
            except:
                await interaction.followup.send(f"❌ Ошибка: {error}", ephemeral=True)
    except Exception as e:
        print(f"Критическая ошибка обработки: {e}")
        traceback.print_exc()

# ==================== ЗАПУСК БОТА ====================

if __name__ == "__main__":
    if not os.path.exists(DATA_FILE):
        save_events({})
        print(f"✅ Создан файл {DATA_FILE}")
    
    if not os.path.exists(SETTINGS_FILE):
        save_settings({})
        print(f"✅ Создан файл {SETTINGS_FILE}")
    
    TOKEN = "ВАШ_ТОКЕН_БОТА"
    bot.run(TOKEN)
