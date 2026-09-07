import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
from datetime import datetime, timedelta
import re
import asyncio
from typing import Optional

# Настройки бота
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Файл для хранения данных
DATA_FILE = 'events.json'

# Время хранения после прохождения события (в часах)
DELETE_AFTER_HOURS = 18

# Максимальное количество событий на сервер
MAX_EVENTS_PER_GUILD = 100

# Количество событий на страницу
EVENTS_PER_PAGE = 10


def load_events():
    """Загружает события из файла"""
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    data = json.loads(content)
                    # Убеждаемся, что data - словарь
                    if isinstance(data, dict):
                        return data
                    else:
                        print("Данные в файле не являются словарем, создаем новый")
                        return {}
                else:
                    return {}
        return {}
    except json.JSONDecodeError as e:
        print(f"Ошибка чтения JSON: {e}")
        if os.path.exists(DATA_FILE):
            backup_file = f"{DATA_FILE}.backup"
            try:
                os.rename(DATA_FILE, backup_file)
                print(f"Поврежденный файл сохранен как {backup_file}")
            except:
                pass
        return {}
    except Exception as e:
        print(f"Неожиданная ошибка при загрузке: {e}")
        return {}


def save_events(events):
    """Сохраняет события в файл"""
    try:
        # Проверяем, что events - словарь
        if not isinstance(events, dict):
            print("Ошибка: events не является словарем")
            events = {}

        temp_file = f"{DATA_FILE}.tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(events, f, ensure_ascii=False, indent=4)

        if os.path.exists(DATA_FILE):
            os.remove(DATA_FILE)
        os.rename(temp_file, DATA_FILE)
        print(f"События сохранены: {len(events)} серверов")

    except Exception as e:
        print(f"Ошибка при сохранении: {e}")
        try:
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(events, f, ensure_ascii=False, indent=4)
        except Exception as e2:
            print(f"Критическая ошибка сохранения: {e2}")


def get_next_event_number(events, guild_id):
    """Получает следующий номер события для сервера"""
    try:
        guild_id_str = str(guild_id)

        # Если сервера нет в events, создаем пустой словарь
        if guild_id_str not in events:
            events[guild_id_str] = {}
            return 1

        guild_events = events[guild_id_str]

        # Если словарь пустой, начинаем с 1
        if not guild_events:
            return 1

        # Находим максимальный номер
        numbers = []
        for key in guild_events.keys():
            try:
                numbers.append(int(key))
            except (ValueError, TypeError):
                continue

        return max(numbers) + 1 if numbers else 1

    except Exception as e:
        print(f"Ошибка получения номера: {e}")
        return 1


def validate_date(date_str):
    """Проверяет корректность даты в формате ДД.ММ"""
    if not date_str:
        return False, "Дата не может быть пустой"

    pattern = r'^(\d{2})\.(\d{2})$'
    match = re.match(pattern, date_str)

    if not match:
        return False, "Неверный формат даты. Используйте формат ДД.ММ (например, 25.12)"

    day, month = int(match.group(1)), int(match.group(2))

    if month < 1 or month > 12:
        return False, "Неверный месяц. Месяц должен быть от 01 до 12"

    days_in_month = {
        1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30,
        7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31
    }

    if day < 1 or day > days_in_month[month]:
        return False, f"Неверный день. В месяце {month:02d} может быть от 01 до {days_in_month[month]} дней"

    return True, ""


def validate_time(time_str):
    """Проверяет корректность времени в формате ЧЧ:ММ или ЧЧ-ММ"""
    if not time_str:
        return False, "Время не может быть пустым"

    pattern = r'^(\d{1,2})[:：\-](\d{2})$'
    match = re.match(pattern, time_str)

    if not match:
        return False, "Неверный формат времени. Используйте формат ЧЧ:ММ или ЧЧ-ММ (например, 15:30 или 15-30)"

    hour, minute = int(match.group(1)), int(match.group(2))

    if hour < 0 or hour > 23:
        return False, "Неверный час. Час должен быть от 00 до 23"

    if minute < 0 or minute > 59:
        return False, "Неверные минуты. Минуты должны быть от 00 до 59"

    return True, ""


def format_date_display(date_str):
    """Форматирует дату для красивого отображения"""
    months = {
        1: "января", 2: "февраля", 3: "марта", 4: "апреля",
        5: "мая", 6: "июня", 7: "июля", 8: "августа",
        9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"
    }

    try:
        day, month = date_str.split('.')
        return f"{int(day)} {months[int(month)]}"
    except:
        return date_str


def format_time_display(time_str):
    """Форматирует время для красивого отображения"""
    try:
        time_str = time_str.replace('-', ':').replace('：', ':')
        hour, minute = time_str.split(':')
        return f"{int(hour):02d}:{minute}"
    except:
        return time_str


def sort_events_by_date(events_dict):
    """Сортирует события по дате и времени"""

    def get_sort_key(item):
        try:
            event_data = item[1]
            date_parts = event_data['date'].split('.')
            time_parts = event_data['time'].split(':')

            return (
                int(date_parts[1]),  # месяц
                int(date_parts[0]),  # день
                int(time_parts[0]),  # час
                int(time_parts[1])  # минуты
            )
        except:
            return (99, 99, 99, 99)

    return sorted(events_dict.items(), key=get_sort_key)


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


def is_event_passed(event_data, current_time=None):
    """Проверяет, прошло ли событие"""
    if current_time is None:
        current_time = datetime.now()

    event_time = get_event_datetime(event_data, current_time.year)

    if event_time is None:
        return False

    if event_time < current_time:
        return True

    if current_time.month > 10 and event_time.month < 3:
        event_time_last_year = get_event_datetime(event_data, current_time.year - 1)
        if event_time_last_year and event_time_last_year < current_time:
            return True

    return False


def should_delete_event(event_data, current_time=None):
    """Проверяет, нужно ли удалить событие (прошло более 18 часов)"""
    if current_time is None:
        current_time = datetime.now()

    if not is_event_passed(event_data, current_time):
        return False

    event_time = get_event_datetime(event_data, current_time.year)

    if event_time and event_time > current_time and current_time.month > 10 and event_time.month < 3:
        event_time = get_event_datetime(event_data, current_time.year - 1)

    if event_time is None:
        return False

    time_difference = current_time - event_time
    return time_difference > timedelta(hours=DELETE_AFTER_HOURS)


def clean_old_events(events, current_time=None):
    """Удаляет старые события, которые прошли более 18 часов назад"""
    if current_time is None:
        current_time = datetime.now()

    if not isinstance(events, dict):
        return {}

    cleaned_events = {}
    deleted_count = 0

    for guild_id, guild_events in events.items():
        if not isinstance(guild_events, dict):
            continue

        cleaned_guild_events = {}

        for event_number, event_data in guild_events.items():
            if should_delete_event(event_data, current_time):
                deleted_count += 1
                print(f"Удалено событие #{event_number} с сервера {guild_id}")
            else:
                cleaned_guild_events[event_number] = event_data

        # Сохраняем даже пустые словари для серверов
        cleaned_events[guild_id] = cleaned_guild_events

    if deleted_count > 0:
        print(f"Всего удалено {deleted_count} старых событий")

    return cleaned_events


@bot.event
async def on_ready():
    print(f'{bot.user} подключился к Discord!')
    print(f'ID бота: {bot.user.id}')

    if not cleanup_task.is_running():
        cleanup_task.start()
        print("Задача автоматической очистки запущена")

    try:
        synced = await bot.tree.sync()
        print(f"Синхронизировано {len(synced)} слэш-команд")
    except Exception as e:
        print(f"Ошибка синхронизации: {e}")
    print('------')


@tasks.loop(hours=1)
async def cleanup_task():
    """Автоматически удаляет старые события"""
    try:
        print("Запущена проверка старых событий...")
        events = load_events()

        if events:
            cleaned_events = clean_old_events(events)

            if cleaned_events != events:
                save_events(cleaned_events)
                print("Очистка завершена, старые события удалены")
            else:
                print("Нет событий для удаления")
        else:
            print("Нет сохраненных событий")

    except Exception as e:
        print(f"Ошибка при очистке событий: {e}")


@cleanup_task.before_loop
async def before_cleanup_task():
    await bot.wait_until_ready()


# Группа команд для событий
class EventCommands(app_commands.Group):
    def __init__(self):
        super().__init__(name="event", description="Управление событиями")

    @app_commands.command(name="add", description="Добавить новое событие")
    @app_commands.describe(
        description="Описание события",
        date="Дата события в формате ДД.ММ (например, 25.12)",
        time="Время события в формате ЧЧ:ММ или ЧЧ-ММ (например, 15:30)"
    )
    async def add_event(self, interaction: discord.Interaction, description: str, date: str, time: str):
        """Добавляет новое событие"""
        try:
            # Проверяем дату
            is_valid_date, date_error = validate_date(date)
            if not is_valid_date:
                embed = discord.Embed(
                    title="❌ Ошибка в дате",
                    description=f"**{date_error}**\n\n"
                                f"Правильный формат: **ДД.ММ** (например, 25.12)",
                    color=discord.Color.red()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Проверяем время
            is_valid_time, time_error = validate_time(time)
            if not is_valid_time:
                embed = discord.Embed(
                    title="❌ Ошибка во времени",
                    description=f"**{time_error}**\n\n"
                                f"Правильный формат: **ЧЧ:ММ** или **ЧЧ-ММ** (например, 15:30 или 15-30)",
                    color=discord.Color.red()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            events = load_events()
            guild_id = str(interaction.guild.id)

            # ВАЖНО: Всегда создаем словарь для сервера, если его нет
            if guild_id not in events:
                events[guild_id] = {}

            # Проверяем лимит событий
            if len(events[guild_id]) >= MAX_EVENTS_PER_GUILD:
                embed = discord.Embed(
                    title="⚠️ Достигнут лимит событий",
                    description=f"На сервере уже хранится **{MAX_EVENTS_PER_GUILD}** событий.\n"
                                f"Удалите старые события или дождитесь автоочистки.",
                    color=discord.Color.orange()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
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
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

            save_events(events)

            embed = discord.Embed(
                title="✅ Событие добавлено",
                description=f"**Номер события:** {event_number}\n"
                            f"**Дата:** {format_date_display(date)}\n"
                            f"**Время:** {normalized_time}\n"
                            f"**Описание:** {description}\n\n"
                            f"*Событие будет автоматически удалено через {DELETE_AFTER_HOURS} часов после его прохождения*",
                color=discord.Color.green()
            )
            embed.set_footer(
                text=f"Добавлено: {interaction.user} | Событий на сервере: {len(events[guild_id])}/{MAX_EVENTS_PER_GUILD}")
            await interaction.response.send_message(embed=embed)

        except Exception as e:
            print(f"Ошибка в add_event: {e}")
            import traceback
            traceback.print_exc()
            await interaction.response.send_message(
                f"❌ Произошла ошибка при добавлении события: {e}",
                ephemeral=True
            )

    @app_commands.command(name="list", description="Показать все события (отсортированные по дате)")
    @app_commands.describe(page="Номер страницы (по умолчанию 1)")
    async def list_events(self, interaction: discord.Interaction, page: int = 1):
        """Показывает все события с пагинацией"""
        try:
            events = load_events()
            guild_id = str(interaction.guild.id)

            # Проверяем, есть ли события для этого сервера
            if guild_id not in events or not events[guild_id]:
                embed = discord.Embed(
                    title="📋 Список событий",
                    description="Нет сохраненных событий",
                    color=discord.Color.blue()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Очищаем старые события
            cleaned_events = clean_old_events(events)
            if cleaned_events != events:
                save_events(cleaned_events)
                events = cleaned_events

            if guild_id not in events or not events[guild_id]:
                embed = discord.Embed(
                    title="📋 Список событий",
                    description="Нет актуальных событий",
                    color=discord.Color.blue()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Сортируем события
            sorted_events = sort_events_by_date(events[guild_id])
            total_events = len(sorted_events)
            total_pages = max(1, (total_events + EVENTS_PER_PAGE - 1) // EVENTS_PER_PAGE)

            # Проверяем страницу
            if page < 1:
                page = 1
            elif page > total_pages:
                page = total_pages

            # Вычисляем диапазон для текущей страницы
            start_idx = (page - 1) * EVENTS_PER_PAGE
            end_idx = min(start_idx + EVENTS_PER_PAGE, total_events)
            page_events = sorted_events[start_idx:end_idx]

            embed = discord.Embed(
                title="📋 Список событий",
                description=f"Страница **{page}/{total_pages}** | Всего событий: **{total_events}**",
                color=discord.Color.blue()
            )

            for number, event_data in page_events:
                try:
                    day, month = map(int, event_data['date'].split('.'))

                    event_text = (
                        f"**📌 Событие #{number}**\n"
                        f"**Дата:** {event_data.get('date_formatted', event_data['date'])}\n"
                        f"**Время:** {event_data['time']}\n"
                        f"**Описание:** {event_data['description']}\n"
                        f"**Автор:** {event_data['author']}"
                    )

                    embed.add_field(
                        name=f"**{day:02d}.{month:02d}** - {event_data['time']}",
                        value=event_text,
                        inline=False
                    )

                except Exception as e:
                    print(f"Ошибка при форматировании события {number}: {e}")
                    continue

            embed.set_footer(text=f"Для навигации используйте /event list page:номер_страницы")
            await interaction.response.send_message(embed=embed)

        except Exception as e:
            print(f"Ошибка в list_events: {e}")
            import traceback
            traceback.print_exc()
            await interaction.response.send_message(
                f"❌ Произошла ошибка при получении списка: {e}",
                ephemeral=True
            )

    @app_commands.command(name="upcoming", description="Показать ближайшие события")
    async def upcoming_events(self, interaction: discord.Interaction):
        """Показывает ближайшие события"""
        try:
            events = load_events()
            guild_id = str(interaction.guild.id)

            if guild_id not in events or not events[guild_id]:
                embed = discord.Embed(
                    title="📅 Ближайшие события",
                    description="Нет сохраненных событий",
                    color=discord.Color.orange()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            cleaned_events = clean_old_events(events)
            if cleaned_events != events:
                save_events(cleaned_events)
                events = cleaned_events

            if guild_id not in events or not events[guild_id]:
                embed = discord.Embed(
                    title="📅 Ближайшие события",
                    description="Нет предстоящих событий",
                    color=discord.Color.orange()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            now = datetime.now()
            current_month = now.month
            current_day = now.day
            current_hour = now.hour
            current_minute = now.minute

            sorted_events = sort_events_by_date(events[guild_id])

            embed = discord.Embed(
                title="📅 Ближайшие события",
                description="Ближайшие 15 событий:",
                color=discord.Color.orange()
            )

            events_added = 0
            for number, event_data in sorted_events:
                try:
                    day, month = map(int, event_data['date'].split('.'))
                    hour, minute = map(int, event_data['time'].split(':'))

                    event_is_future = (
                            (month > current_month) or
                            (month == current_month and day > current_day) or
                            (month == current_month and day == current_day and hour > current_hour) or
                            (
                                        month == current_month and day == current_day and hour == current_hour and minute >= current_minute)
                    )

                    if event_is_future and events_added < 15:
                        if month == current_month and day == current_day:
                            status = "🔴 СЕГОДНЯ"
                        elif month == current_month and day == current_day + 1:
                            status = "🟡 ЗАВТРА"
                        elif month == current_month and day - current_day <= 7 and day - current_day > 0:
                            status = f"🟢 Через {day - current_day} дн."
                        else:
                            status = "📅"

                        event_text = (
                            f"**📌 Событие #{number}**\n"
                            f"**Дата:** {event_data.get('date_formatted', event_data['date'])}\n"
                            f"**Время:** {event_data['time']}\n"
                            f"**Описание:** {event_data['description']}\n"
                            f"**Автор:** {event_data['author']}"
                        )

                        embed.add_field(
                            name=f"{status} | {day:02d}.{month:02d} в {event_data['time']}",
                            value=event_text,
                            inline=False
                        )
                        events_added += 1
                except:
                    continue

            if events_added == 0:
                embed.description = "Нет предстоящих событий"

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            print(f"Ошибка в upcoming_events: {e}")
            await interaction.response.send_message(
                f"❌ Произошла ошибка при получении ближайших событий: {e}",
                ephemeral=True
            )

    @app_commands.command(name="info", description="Показать информацию о конкретном событии")
    @app_commands.describe(number="Номер события")
    async def show_info(self, interaction: discord.Interaction, number: int):
        """Показывает информацию о конкретном событии"""
        try:
            events = load_events()
            guild_id = str(interaction.guild.id)

            if guild_id not in events:
                await interaction.response.send_message("❌ Нет сохраненных событий", ephemeral=True)
                return

            event_key = str(number)
            if event_key not in events[guild_id]:
                await interaction.response.send_message(f"❌ Событие с номером {number} не найдено", ephemeral=True)
                return

            event_data = events[guild_id][event_key]
            event_passed = is_event_passed(event_data)

            embed = discord.Embed(
                title=f"📌 Информация о событии #{number}",
                color=discord.Color.gold() if not event_passed else discord.Color.red()
            )

            status = "✅ Актуально" if not event_passed else "⚠️ Событие уже прошло"

            embed.add_field(
                name="📅 **ДАТА**",
                value=f"**{event_data.get('date_formatted', event_data['date'])}**",
                inline=True
            )
            embed.add_field(
                name="⏰ **ВРЕМЯ**",
                value=f"**{event_data['time']}**",
                inline=True
            )
            embed.add_field(
                name="📝 **ОПИСАНИЕ**",
                value=f"**{event_data['description']}**",
                inline=False
            )
            embed.add_field(
                name="👤 **АВТОР**",
                value=f"**{event_data['author']}**",
                inline=True
            )
            embed.add_field(
                name="📊 **СТАТУС**",
                value=f"**{status}**",
                inline=True
            )

            if event_passed:
                embed.add_field(
                    name="⚠️ **ВНИМАНИЕ**",
                    value=f"*Событие будет удалено через {DELETE_AFTER_HOURS} часов после прохождения*",
                    inline=False
                )

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            print(f"Ошибка в show_info: {e}")
            await interaction.response.send_message(
                f"❌ Произошла ошибка при получении информации: {e}",
                ephemeral=True
            )

    @app_commands.command(name="delete", description="Удалить событие по номеру")
    @app_commands.describe(number="Номер события для удаления")
    async def delete_event(self, interaction: discord.Interaction, number: int):
        """Удаляет событие по номеру"""
        try:
            events = load_events()
            guild_id = str(interaction.guild.id)

            if guild_id not in events:
                await interaction.response.send_message("❌ Нет сохраненных событий", ephemeral=True)
                return

            event_key = str(number)
            if event_key not in events[guild_id]:
                await interaction.response.send_message(f"❌ Событие с номером {number} не найдено", ephemeral=True)
                return

            deleted_event = events[guild_id].pop(event_key)

            # ВАЖНО: Не удаляем guild_id из events, даже если словарь пустой
            # events[guild_id] остается пустым словарем

            save_events(events)

            embed = discord.Embed(
                title="🗑️ Событие удалено",
                description=f"**Номер:** {number}\n"
                            f"**Дата:** {deleted_event.get('date_formatted', deleted_event['date'])}\n"
                            f"**Время:** {deleted_event['time']}\n"
                            f"**Описание:** {deleted_event['description']}",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)

        except Exception as e:
            print(f"Ошибка в delete_event: {e}")
            import traceback
            traceback.print_exc()
            await interaction.response.send_message(
                f"❌ Произошла ошибка при удалении события: {e}",
                ephemeral=True
            )

    @app_commands.command(name="clear", description="Удалить все события (только для администраторов)")
    async def clear_events(self, interaction: discord.Interaction):
        """Удаляет все события (только для администраторов)"""
        try:
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ У вас недостаточно прав для этой команды", ephemeral=True)
                return

            events = load_events()
            guild_id = str(interaction.guild.id)

            if guild_id in events:
                # ВАЖНО: Очищаем словарь, но не удаляем ключ guild_id
                events[guild_id] = {}
                save_events(events)

                embed = discord.Embed(
                    title="✅ Все события удалены",
                    description="База данных событий полностью очищена. Теперь можно добавлять новые события.",
                    color=discord.Color.green()
                )
                await interaction.response.send_message(embed=embed)
            else:
                # Если сервера нет в events, создаем пустой словарь
                events[guild_id] = {}
                save_events(events)
                await interaction.response.send_message("📋 Нет событий для удаления", ephemeral=True)

        except Exception as e:
            print(f"Ошибка в clear_events: {e}")
            import traceback
            traceback.print_exc()
            await interaction.response.send_message(
                f"❌ Произошла ошибка при очистке событий: {e}",
                ephemeral=True
            )


# Команда помощи
@bot.tree.command(name="help", description="Показать все доступные команды")
async def help_command(interaction: discord.Interaction):
    """Показывает все доступные команды"""
    embed = discord.Embed(
        title="📚 Список команд",
        description="**Все доступные слэш-команды бота:**",
        color=discord.Color.purple()
    )

    commands_info = [
        ("**/event add**", "Добавить новое событие\n`описание` `дата` `время`"),
        ("**/event list**", "Показать все события (с пагинацией)\n`страница` (опционально)"),
        ("**/event upcoming**", "Показать ближайшие 15 событий"),
        ("**/event info**", "Показать информацию о событии\n`номер`"),
        ("**/event delete**", "Удалить событие по номеру\n`номер`"),
        ("**/event clear**", "Удалить все события (для админов)"),
        ("**/help**", "Показать этот список команд")
    ]

    for command, description in commands_info:
        embed.add_field(
            name=command,
            value=f"**{description}**",
            inline=False
        )

    embed.add_field(
        name="📝 **Форматы**",
        value="**Дата:** `ДД.ММ` (например, `25.12`)\n"
              "**Время:** `ЧЧ:ММ` или `ЧЧ-ММ` (например, `15:30`)",
        inline=False
    )

    embed.add_field(
        name="🕐 **Автоудаление**",
        value=f"События удаляются через **{DELETE_AFTER_HOURS} часов** после прохождения\n"
              f"Максимум событий на сервер: **{MAX_EVENTS_PER_GUILD}**",
        inline=False
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)


# Регистрация группы команд
bot.tree.add_command(EventCommands())


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    try:
        if isinstance(error, app_commands.errors.MissingPermissions):
            await interaction.response.send_message("❌ У вас недостаточно прав для этой команды", ephemeral=True)
        else:
            print(f"Ошибка слэш-команды: {error}")
            await interaction.response.send_message(f"❌ Произошла ошибка: {error}", ephemeral=True)
    except:
        print(f"Критическая ошибка обработки: {error}")


if __name__ == "__main__":
    # Создаем файл, если его нет
    if not os.path.exists(DATA_FILE):
        save_events({})
        print(f"Создан файл {DATA_FILE}")

    # Проверяем целостность данных при запуске
    events = load_events()
    print(f"Загружено событий: {len(events)} серверов")

    # Очищаем старые события
    if events:
        cleaned_events = clean_old_events(events)
        if cleaned_events != events:
            save_events(cleaned_events)
            print("Выполнена очистка старых событий при запуске")

    TOKEN = ""
    bot.run(TOKEN)