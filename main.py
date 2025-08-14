import base64
import json
import logging
import os
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CallbackContext,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

from keep_alive import keep_alive

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- State Definitions for ConversationHandler ---
(
    MENU,
    # Registrar States
    REG_AWAITING_DATE,
    REG_AWAITING_PATIENT,
    REG_SELECTING_PROCEDURES,
    REG_SELECTING_PRICE,
    REG_CONFIRMING_MORE,
    # Listar States
    LISTAR_AWAITING_DATE,
    # Calcular States
    CALC_SELECTING_MODE,
    CALC_AWAITING_DATE,
    CALC_AWAITING_RANGE,
    # Analytics States
    ANALYTICS_MENU,
    # Deletar States
    DEL_AWAITING_DATE,
    DEL_SELECTING_RECORD,
    DEL_CONFIRMING,
) = range(14)


# --- Constants ---
PROCEDURE_DESCRIPTIONS = {
    "radiofrequencia": "Radiofrequência",
    "limpezadepele": "Limpeza de Pele",
    "bodyshape": "Body Shape",
    "hiperslim": "Hiper Slim",
    "massagem": "Massagem",
    "spa": "SPA",
    "posoperatorio": "Pós Operatório",
    "ultrassom": "Ultrassom",
    "detox": "Detox",
    "3mh": "3MH",
    "compex": "Compex",
}
VALID_PRICES = [5, 10, 15, 20]


# --- Utility Functions ---
def slugify(text):
    """Converts a string into a 'slug' for consistent matching."""
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    text = text.lower()
    text = text.replace(" ", "").replace("-", "")
    return text


def parse_record_text(text: str, procedure_descriptions: dict) -> tuple[str, list[str], float] | None:
    """
    DEPRECATED: This function is no longer used in the interactive registration flow
    but is kept for reference or potential future use.
    """
    return None


def get_records_in_range(sheet, start_date, end_date) -> List[Dict]:
    """Fetches all records from the sheet and filters them by a date range."""
    all_records = sheet.get_all_records()
    filtered_records = []
    for record in all_records:
        try:
            record_date = datetime.strptime(record.get('Date', ''), "%d/%m/%Y").date()
            if start_date <= record_date <= end_date:
                record['Price'] = float(str(record.get('Price', '0')).replace(',', '.'))
                filtered_records.append(record)
        except (ValueError, TypeError):
            logger.warning(f"Skipping row with invalid data during filtering: {record}")
    return filtered_records


def get_brazil_datetime_now():
    return datetime.now() - timedelta(hours=3)


def get_date_range_for_sum(mode: str, date_input: str | None) -> Optional[Tuple[datetime.date, datetime.date, str]]:
    """Calculates the start date, end date, and a descriptive string for a given mode."""
    now = get_brazil_datetime_now()
    try:
        if mode == 'dia':
            day_str = date_input or now.strftime("%d/%m/%Y")
            start_date = end_date = datetime.strptime(day_str, "%d/%m/%Y").date()
            period_str = f"o dia {day_str}"
        elif mode == 'semana':
            target_date = datetime.strptime(date_input, "%d/%m/%Y") if date_input else now
            start_of_week = target_date - timedelta(days=target_date.weekday())
            end_of_week = start_of_week + timedelta(days=6)
            start_date, end_date = start_of_week.date(), end_of_week.date()
            period_str = f"a semana de {start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
        elif mode == 'mes':
            month_str = date_input or now.strftime("%m/%Y")
            target_month = datetime.strptime(month_str, "%m/%Y")
            start_date = target_month.date().replace(day=1)
            next_month = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
            end_date = next_month - timedelta(days=1)
            period_str = f"o mês {month_str}"
        elif mode == 'periodo':
            if not date_input or len(date_input.split()) != 2:
                return None
            parts = date_input.split()
            start_date = datetime.strptime(parts[0], "%d/%m/%Y").date()
            end_date = datetime.strptime(parts[1], "%d/%m/%Y").date()
            period_str = f"o período de {parts[0]} a {parts[1]}"
        else:
            return None
        return start_date, end_date, period_str
    except (ValueError, AttributeError):
        return None


async def send_final_message(update: Update):
    """Sends a consistent final message and clears user data."""
    await update.effective_message.reply_text("Operação concluída. Use /menu para ver o menu principal.")


# --- Google Sheets Setup ---
def get_sheet():
    """Connects to Google Sheets and returns the worksheet object."""
    try:
        scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/drive']
        creds_base64 = os.environ.get("GCREDS_JSON_BASE64")
        if not creds_base64:
            logger.error("GCREDS_JSON_BASE64 environment variable not set.")
            raise ValueError("Missing Google Credentials in environment.")
        creds_json = base64.b64decode(creds_base64).decode('utf-8')
        creds_dict = json.loads(creds_json)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet_id = os.environ.get("SHEET_ID")
        if not sheet_id:
            raise ValueError("Environment variable SHEET_ID not set.")
        sheet = client.open_by_key(sheet_id).sheet1
        return sheet
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.error(f"Credential configuration error: {e}")
        return None
    except Exception as e:
        logger.error(f"Error connecting to Google Sheets: {e}")
        return None


# --- Main Menu and Core Commands ---
async def menu_command(update: Update, context: CallbackContext) -> int:
    """Displays the main menu and sets the conversation state."""
    context.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("🚀 Registrar Novo Atendimento", callback_data="menu_registrar")],
        [InlineKeyboardButton("📋 Listar Atendimentos de um Dia", callback_data="menu_listar")],
        [InlineKeyboardButton("🗑️ Deletar Atendimento", callback_data="menu_deletar")],
        [InlineKeyboardButton("📊 Calcular Faturamento", callback_data="menu_calcular")],
        [InlineKeyboardButton("📈 Ver Análises", callback_data="menu_analytics")],
        [InlineKeyboardButton("ℹ️ Ver Procedimentos", callback_data="menu_procedimentos")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # If coming from a canceled operation or another menu, edit the message.
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "Menu Principal. O que você gostaria de fazer?", reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "👋 Olá! Sou seu assistente de agendamentos. O que você gostaria de fazer?",
            reply_markup=reply_markup,
        )
    return MENU


async def menu_router(update: Update, context: CallbackContext) -> int:
    """Routes main menu button presses to the correct conversation flow."""
    query = update.callback_query
    await query.answer()

    command = query.data

    if command == 'menu_registrar':
        return await registrar_start(update, context)
    elif command == 'menu_calcular':
        return await calcular_start(update, context)
    elif command == 'menu_listar':
        return await listar_start(update, context)
    elif command == 'menu_deletar':
        return await deletar_start(update, context)
    elif command == 'menu_analytics':
        return await analytics_start(update, context)
    elif command == 'menu_procedimentos':
        await procedimentos_command(update, context)
        await send_final_message(update)
        return ConversationHandler.END

    return ConversationHandler.END


async def procedimentos_command(update: Update, context: CallbackContext) -> None:
    """Lists all available procedures and their descriptions."""
    message = "📋 Procedimentos Disponíveis:\n\n"
    for slug, description in PROCEDURE_DESCRIPTIONS.items():
        message += f"• {description}\n"
    if update.callback_query:
        await update.callback_query.edit_message_text(message)
    else:
        await update.effective_message.reply_text(message)


# --- Analytics ---
async def analytics_start(update: Update, context: CallbackContext) -> int:
    """Displays the analytics menu."""
    keyboard = [
        [InlineKeyboardButton("💰 Faturamento", callback_data="analytics_revenue")],
        [InlineKeyboardButton("📅 Atendimentos", callback_data="analytics_appointments")],
        [InlineKeyboardButton("⭐ Procedimentos", callback_data="analytics_procedures")],
        [InlineKeyboardButton("👤 Pacientes", callback_data="analytics_patients")],
        [InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="menu_back")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = "📈 *Menu de Análises*\n\nEscolha qual relatório você deseja ver:"
    await update.callback_query.edit_message_text(text=message, reply_markup=reply_markup, parse_mode='Markdown')
    return ANALYTICS_MENU


async def analytics_router(update: Update, context: CallbackContext) -> int:
    """Routes analytics menu button presses to the correct report function."""
    query = update.callback_query
    await query.answer()
    command = query.data

    sheet = get_sheet()
    if not sheet:
        await query.edit_message_text("⚠️ Erro de configuração: Não foi possível conectar à planilha.")
        return ConversationHandler.END

    all_records = sheet.get_all_records()
    if not all_records:
        await query.edit_message_text("ℹ️ Não há dados suficientes para gerar análises.")
        return ConversationHandler.END

    # Pre-process records to parse dates and prices once
    processed_records = []
    for record in all_records:
        try:
            record['parsed_date'] = datetime.strptime(record.get('Date', ''), "%d/%m/%Y").date()
            record['parsed_price'] = float(str(record.get('Price', '0')).replace(',', '.'))
            processed_records.append(record)
        except (ValueError, TypeError):
            continue # Skip malformed records

    message_text = "Comando não reconhecido."
    if command == 'analytics_revenue':
        message_text = analytics_show_revenue(processed_records)
    elif command == 'analytics_appointments':
        message_text = analytics_show_appointments(processed_records)
    elif command == 'analytics_procedures':
        message_text = analytics_show_procedures(processed_records)
    elif command == 'analytics_patients':
        message_text = analytics_show_patients(processed_records)

    await query.edit_message_text(text=message_text, parse_mode='Markdown')

    # After showing the report, send the final message and end.
    await send_final_message(update)
    return ConversationHandler.END


def analytics_show_revenue(records: list[dict]) -> str:
    """Calculates and shows total revenue per month and grand total."""
    monthly_revenue = defaultdict(float)
    for record in records:
        month_key = record['parsed_date'].strftime("%m/%Y")
        monthly_revenue[month_key] += record['parsed_price']

    if not monthly_revenue:
        return "Nenhum dado de faturamento encontrado."

    message = "💰 *Faturamento Mensal*\n\n"
    total_revenue = 0.0
    # Sort by month/year
    sorted_months = sorted(monthly_revenue.keys(), key=lambda m: datetime.strptime(m, "%m/%Y"))

    for month in sorted_months:
        revenue = monthly_revenue[month]
        total_revenue += revenue
        message += f"*{month}:* R$ {revenue:.2f}\n".replace('.', ',')

    message += f"\n*Total Geral:* R$ {total_revenue:.2f}".replace('.', ',')
    return message


def analytics_show_appointments(records: list[dict]) -> str:
    """Calculates and shows total appointments per month."""
    monthly_appointments = defaultdict(int)
    for record in records:
        month_key = record['parsed_date'].strftime("%m/%Y")
        monthly_appointments[month_key] += 1

    if not monthly_appointments:
        return "Nenhum atendimento encontrado."

    message = "📅 *Atendimentos por Mês*\n\n"
    sorted_months = sorted(monthly_appointments.keys(), key=lambda m: datetime.strptime(m, "%m/%Y"))

    for month in sorted_months:
        count = monthly_appointments[month]
        message += f"*{month}:* {count} atendimentos\n"

    return message


def analytics_show_procedures(records: list[dict]) -> str:
    """Calculates and shows procedure counts per month."""
    monthly_procedures = defaultdict(lambda: defaultdict(int))
    for record in records:
        month_key = record['parsed_date'].strftime("%m/%Y")
        procedures = record.get('Procedures', '').split(',')
        for proc in procedures:
            slug = slugify(proc.strip())
            if slug in PROCEDURE_DESCRIPTIONS:
                monthly_procedures[month_key][slug] += 1

    if not monthly_procedures:
        return "Nenhum procedimento encontrado."

    message = "⭐ *Procedimentos Populares por Mês*\n"
    sorted_months = sorted(monthly_procedures.keys(), key=lambda m: datetime.strptime(m, "%m/%Y"))

    for month in sorted_months:
        message += f"\n*{month}*\n"
        # Sort by count (desc) and then by name (asc)
        sorted_procs = sorted(
            monthly_procedures[month].items(),
            key=lambda item: (-item[1], PROCEDURE_DESCRIPTIONS.get(item[0], item[0].upper()))
        )
        for slug, count in sorted_procs:
            proc_name = PROCEDURE_DESCRIPTIONS.get(slug, slug.upper())
            message += f"  - {proc_name}: {count}\n"

    return message


def analytics_show_patients(records: list[dict]) -> str:
    """Calculates and shows patient appointment counts per month."""
    monthly_patients = defaultdict(lambda: defaultdict(int))
    for record in records:
        month_key = record['parsed_date'].strftime("%m/%Y")
        patient_name = record.get('Patient', 'N/A').title()
        monthly_patients[month_key][patient_name] += 1

    if not monthly_patients:
        return "Nenhum paciente encontrado."

    message = "👤 *Ranking de Pacientes por Mês*\n"
    sorted_months = sorted(monthly_patients.keys(), key=lambda m: datetime.strptime(m, "%m/%Y"))

    for month in sorted_months:
        message += f"\n*{month}*\n"
        # Sort by count (desc) and then by name (asc)
        sorted_patients = sorted(monthly_patients[month].items(), key=lambda item: (-item[1], item[0]))
        for name, count in sorted_patients:
            message += f"  - {name}: {count}\n"

    return message


# --- REGISTRAR Conversation ---
async def registrar_start(update: Update, context: CallbackContext) -> int:
    """Starts the conversation to register a new record."""
    context.user_data.clear() # Clear data from any previous conversation
    keyboard = [
        [InlineKeyboardButton("Hoje", callback_data="reg_today")],
        [InlineKeyboardButton("Outra data (DD/MM)", callback_data="reg_other_date")],
        [InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="menu_back")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = "📅 Para qual data você deseja registrar o novo atendimento?"
    await update.callback_query.edit_message_text(text=message, reply_markup=reply_markup)
    return REG_AWAITING_DATE


async def registrar_date_selection(update: Update, context: CallbackContext) -> int:
    """Handles the user's date choice and asks for the patient's name."""
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == "reg_today":
        context.user_data['date'] = get_brazil_datetime_now().date()
        await query.edit_message_text("👤 Por favor, digite o nome do(a) paciente.")
        return REG_AWAITING_PATIENT
    elif choice == "reg_other_date":
        await query.edit_message_text("📅 Por favor, digite a data no formato `DD/MM`.")
        return REG_AWAITING_DATE # Wait for user to type date
    return ConversationHandler.END


async def registrar_receive_custom_date(update: Update, context: CallbackContext) -> int:
    """Receives a custom date from the user and asks for the patient's name."""
    date_str = update.message.text
    try:
        current_year = get_brazil_datetime_now().year
        target_date = datetime.strptime(f"{date_str}/{current_year}", "%d/%m/%Y").date()
        context.user_data['date'] = target_date
        await update.message.reply_text("👤 Por favor, digite o nome do(a) paciente.")
        return REG_AWAITING_PATIENT
    except ValueError:
        await update.message.reply_text("⚠️ Data inválida. Use o formato DD/MM. Tente novamente ou use /cancelar.")
        return REG_AWAITING_DATE


def build_procedures_keyboard(selected_slugs: set) -> InlineKeyboardMarkup:
    """Builds the keyboard for procedure selection with checkmarks."""
    keyboard = []
    for slug, description in PROCEDURE_DESCRIPTIONS.items():
        text = f"✅ {description}" if slug in selected_slugs else f"⬜️ {description}"
        keyboard.append([InlineKeyboardButton(text, callback_data=f"proc_{slug}")])
    keyboard.append([InlineKeyboardButton("➡️ Continuar", callback_data="proc_done")])
    keyboard.append([InlineKeyboardButton("🔙 Cancelar", callback_data="cancel")])
    return InlineKeyboardMarkup(keyboard)


async def registrar_receive_patient(update: Update, context: CallbackContext) -> int:
    """Receives the patient's name and shows the procedure selection."""
    patient_name = update.message.text.strip()
    if not patient_name:
        await update.message.reply_text("⚠️ Nome do paciente não pode ser vazio. Por favor, tente novamente.")
        return REG_AWAITING_PATIENT

    context.user_data['patient'] = patient_name
    context.user_data['selected_procedures'] = set()

    reply_markup = build_procedures_keyboard(set())
    await update.message.reply_text(
        "📋 Selecione um ou mais procedimentos. Clique em 'Continuar' quando terminar.",
        reply_markup=reply_markup
    )
    return REG_SELECTING_PROCEDURES


async def registrar_procedure_selection(update: Update, context: CallbackContext) -> int:
    """Handles the interactive procedure selection."""
    query = update.callback_query
    await query.answer()
    callback_data = query.data

    if callback_data == "cancel":
        await query.edit_message_text("Operação cancelada.")
        return await menu_command(update, context)

    selected_procedures = context.user_data.get('selected_procedures', set())

    if callback_data == "proc_done":
        if not selected_procedures:
            await context.bot.answer_callback_query(query.id, "⚠️ Você deve selecionar pelo menos um procedimento.", show_alert=True)
            return REG_SELECTING_PROCEDURES

        # Build price keyboard
        price_keyboard = [
            [InlineKeyboardButton(f"R$ {price:.2f}".replace('.', ','), callback_data=f"price_{price}") for price in VALID_PRICES],
            [InlineKeyboardButton("🔙 Voltar", callback_data="price_back")]
        ]
        await query.edit_message_text(
            "💰 Selecione o valor do atendimento:",
            reply_markup=InlineKeyboardMarkup(price_keyboard)
        )
        return REG_SELECTING_PRICE

    # Toggle procedure selection
    proc_slug = callback_data.replace("proc_", "")
    if proc_slug in selected_procedures:
        selected_procedures.remove(proc_slug)
    else:
        selected_procedures.add(proc_slug)

    context.user_data['selected_procedures'] = selected_procedures
    reply_markup = build_procedures_keyboard(selected_procedures)
    await query.edit_message_text(
        "📋 Selecione um ou mais procedimentos. Clique em 'Continuar' quando terminar.",
        reply_markup=reply_markup
    )
    return REG_SELECTING_PROCEDURES


async def registrar_price_selection(update: Update, context: CallbackContext) -> int:
    """Handles the price selection and saves the record."""
    query = update.callback_query
    await query.answer()
    callback_data = query.data

    if callback_data == "price_back":
        reply_markup = build_procedures_keyboard(context.user_data.get('selected_procedures', set()))
        await query.edit_message_text(
            "📋 Selecione um ou mais procedimentos. Clique em 'Continuar' quando terminar.",
            reply_markup=reply_markup
        )
        return REG_SELECTING_PROCEDURES

    price = int(callback_data.replace("price_", ""))
    context.user_data['price'] = price

    # All data collected, now save it
    return await save_record_and_summarize(update, context)


async def save_record_and_summarize(update: Update, context: CallbackContext) -> int:
    """Saves the collected data to the spreadsheet and shows a summary."""
    query = update.callback_query
    sheet = get_sheet()
    if not sheet:
        await query.edit_message_text("⚠️ Erro de configuração: Não foi possível conectar à planilha.")
        return ConversationHandler.END

    try:
        # First, edit the original message to give feedback.
        await query.edit_message_text("Salvando registro...")

        user_data = context.user_data
        date_obj = user_data['date']
        patient = user_data['patient'].upper()
        procedure_slugs = sorted(list(user_data['selected_procedures']))
        procedure_names = [PROCEDURE_DESCRIPTIONS[slug] for slug in procedure_slugs]
        price = user_data['price']

        row = [
            date_obj.strftime("%d/%m/%Y"),
            patient,
            ', '.join(procedure_names).upper(),
            price
        ]
        sheet.append_row(row)

        summary_text = (
            f"✅ *Atendimento salvo com sucesso!*\n\n"
            f"📅 *Data:* {date_obj.strftime('%d/%m/%Y')}\n"
            f"👤 *Paciente:* {patient.title()}\n"
            f"📋 *Procedimentos:* {', '.join(procedure_names)}\n"
            f"💰 *Valor:* R$ {price:.2f}".replace('.', ',')
        )
        # Send the summary as a new message
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=summary_text,
            parse_mode='Markdown'
        )

        # Ask to add another in a new message
        keyboard = [
            [InlineKeyboardButton("Sim, para a mesma data", callback_data="reg_another_yes")],
            [InlineKeyboardButton("Não, finalizar", callback_data="reg_another_no")],
        ]
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Deseja registrar outro atendimento?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return REG_CONFIRMING_MORE

    except Exception as e:
        logger.error(f"Failed to save record: {e}")
        await query.edit_message_text(f"⚠️ Ocorreu um erro ao salvar o registro: {e}")
        return ConversationHandler.END


async def registrar_confirm_more(update: Update, context: CallbackContext) -> int:
    """Handles user's choice to add another record or finish."""
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == "reg_another_yes":
        # Keep the date, clear other data
        date = context.user_data.get('date')
        context.user_data.clear()
        context.user_data['date'] = date
        await query.edit_message_text("👤 Por favor, digite o nome do(a) próximo(a) paciente.")
        return REG_AWAITING_PATIENT
    else: # 'reg_another_no'
        date_obj = context.user_data.get('date')
        await query.edit_message_text("Ok, operação finalizada.")
        context.user_data.clear()
        # Show summary for the day
        await list_records_for_date(update, context, date_obj)
        return ConversationHandler.END


# --- DELETAR Conversation ---
async def deletar_start(update: Update, context: CallbackContext) -> int:
    """Starts the conversation to delete a record."""
    context.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("Hoje", callback_data="del_today")],
        [InlineKeyboardButton("Outra data (DD/MM)", callback_data="del_other_date")],
        [InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="menu_back")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = "🗑️ Para qual data você deseja deletar um atendimento?"
    await update.callback_query.edit_message_text(text=message, reply_markup=reply_markup)
    return DEL_AWAITING_DATE


async def deletar_date_selection(update: Update, context: CallbackContext) -> int:
    """Handles the user's date choice for deletion."""
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == "del_today":
        selected_date = get_brazil_datetime_now().date()
        return await list_records_for_deletion(update, context, selected_date)
    elif choice == "del_other_date":
        await query.edit_message_text("📅 Por favor, digite a data no formato `DD/MM`.")
        return DEL_AWAITING_DATE
    return ConversationHandler.END


def get_records_with_row_numbers(sheet, target_date) -> List[Dict]:
    """Fetches records for a date and includes their row number."""
    all_values = sheet.get_all_values()
    header = all_values[0]
    records_with_rows = []
    for i, row in enumerate(all_values[1:], start=2): # Start from row 2
        try:
            record_date_str = row[header.index('Date')]
            record_date = datetime.strptime(record_date_str, "%d/%m/%Y").date()
            if record_date == target_date:
                record = dict(zip(header, row))
                record['row_number'] = i
                record['Price'] = float(str(record.get('Price', '0')).replace(',', '.'))
                records_with_rows.append(record)
        except (ValueError, TypeError, IndexError):
            continue
    return records_with_rows


async def list_records_for_deletion(update: Update, context: CallbackContext, target_date) -> int:
    """Lists records for a given date as selectable buttons for deletion."""
    sheet = get_sheet()
    if not sheet:
        error_message = "⚠️ Erro de configuração: Não foi possível conectar à planilha."
        if update.callback_query:
            await update.callback_query.edit_message_text(error_message)
        else:
            await update.message.reply_text(error_message)
        return ConversationHandler.END

    records_to_delete = get_records_with_row_numbers(sheet, target_date)
    if not records_to_delete:
        message = f"ℹ️ Nenhum atendimento encontrado para {target_date.strftime('%d/%m/%Y')}."
        if update.callback_query:
            await update.callback_query.answer(text=message, show_alert=True)
            await menu_command(update, context)
        else:
            await update.message.reply_text(f"{message} Use /menu para começar de novo.")
        return ConversationHandler.END

    context.user_data['records_for_deletion'] = records_to_delete
    context.user_data['delete_date'] = target_date

    keyboard = []
    message = f"Selecione o atendimento para deletar em *{target_date.strftime('%d/%m/%Y')}*:\n\n"

    # Create a reverse mapping from slug to proper case
    slug_to_proper_case = {slug: desc for slug, desc in PROCEDURE_DESCRIPTIONS.items()}
    # Create a mapping from the sheet's format (uppercase, no space) to slug
    sheet_format_to_slug = {slugify(desc).upper(): slug for slug, desc in PROCEDURE_DESCRIPTIONS.items()}


    for record in records_to_delete:
        patient = record.get('Patient', 'N/A').title()
        procs_str = record.get('Procedures', 'N/A')

        # Map uppercase procedures from sheet to proper case for display
        procs_list_from_sheet = [p.strip() for p in procs_str.split(',')]

        proper_procs_list = []
        for proc_from_sheet in procs_list_from_sheet:
            # Normalize the string from the sheet in the same way slugs are created, but keep it uppercase
            sheet_slug = slugify(proc_from_sheet).upper()
            # Find the original slug
            original_slug = sheet_format_to_slug.get(sheet_slug)
            # Get the proper description
            proper_name = slug_to_proper_case.get(original_slug, proc_from_sheet)
            proper_procs_list.append(proper_name)

        procs_display = ', '.join(proper_procs_list)

        price = record.get('Price', 0.0)
        button_text = f"{patient} | {procs_display} | R$ {price:.2f}".replace('.', ',')
        callback_data = f"del_record_{record['row_number']}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

    keyboard.append([InlineKeyboardButton("🔙 Cancelar", callback_data="cancel_delete")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

    return DEL_SELECTING_RECORD


async def deletar_receive_date(update: Update, context: CallbackContext) -> int:
    """Receives a custom date and lists records for deletion."""
    date_str = update.message.text
    try:
        current_year = get_brazil_datetime_now().year
        target_date = datetime.strptime(f"{date_str}/{current_year}", "%d/%m/%Y").date()
        return await list_records_for_deletion(update, context, target_date)
    except ValueError:
        await update.message.reply_text("⚠️ Data inválida. Use o formato DD/MM. Tente novamente ou use /cancelar.")
        return DEL_AWAITING_DATE


async def deletar_ask_confirmation(update: Update, context: CallbackContext) -> int:
    """Asks the user to confirm the deletion of a specific record."""
    query = update.callback_query
    await query.answer()
    row_number = int(query.data.replace("del_record_", ""))
    context.user_data['row_to_delete'] = row_number

    # Find the record details to show in the confirmation message
    records = context.user_data.get('records_for_deletion', [])
    record_to_delete = next((r for r in records if r['row_number'] == row_number), None)

    if not record_to_delete:
        await query.edit_message_text("⚠️ Erro: Atendimento não encontrado. Tente novamente.")
        return await list_records_for_deletion(update, context, context.user_data['delete_date'])

    upper_to_proper_case = {v.upper(): v for v in PROCEDURE_DESCRIPTIONS.values()}
    patient = record_to_delete.get('Patient', 'N/A').title()
    procs_str = record_to_delete.get('Procedures', 'N/A')
    procs_list_upper = procs_str.split(', ')
    proper_procs_list = [upper_to_proper_case.get(p, p) for p in procs_list_upper]
    procs_display = ', '.join(proper_procs_list)
    price = record_to_delete.get('Price', 0.0)

    message = (
        f"Você tem certeza que deseja deletar o seguinte atendimento?\n\n"
        f"👤 *Paciente:* {patient}\n"
        f"📋 *Procedimentos:* {procs_display}\n"
        f"💰 *Valor:* R$ {price:.2f}".replace('.', ',')
    )

    keyboard = [
        [
            InlineKeyboardButton("Sim, deletar", callback_data="del_confirm_yes"),
            InlineKeyboardButton("Não, voltar", callback_data="del_confirm_no"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')

    return DEL_CONFIRMING


async def deletar_receive_selection(update: Update, context: CallbackContext) -> int:
    """Receives the user's confirmation and deletes the record."""
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == "del_confirm_no":
        target_date = context.user_data.get('delete_date')
        if target_date:
            await query.edit_message_text("Ok, voltando para a lista de atendimentos.")
            return await list_records_for_deletion(update, context, target_date)
        else:
            await query.edit_message_text("Operação cancelada.")
            await menu_command(update, context)
            return ConversationHandler.END

    # Proceed with deletion if 'yes'
    try:
        row_number_to_delete = context.user_data.get('row_to_delete')
        if not row_number_to_delete:
            raise ValueError("Row number to delete not found in context.")

        sheet = get_sheet()
        if not sheet:
            await query.edit_message_text("⚠️ Erro de configuração: Não foi possível conectar à planilha.")
            return ConversationHandler.END

        sheet.delete_rows(row_number_to_delete)
        await query.edit_message_text("✅ Atendimento deletado com sucesso!")

        # Send the standard final message
        await send_final_message(update)

        context.user_data.clear()
        return ConversationHandler.END

    except (ValueError, IndexError) as e:
        logger.error(f"Error during deletion confirmation: {e}")
        await query.edit_message_text("⚠️ Ocorreu um erro ao processar a sua seleção. Tente novamente.")
        return ConversationHandler.END


# --- LISTAR Conversation ---
async def listar_start(update: Update, context: CallbackContext) -> int:
    """Starts the conversation to list records for a day."""
    keyboard = [
        [InlineKeyboardButton("Hoje", callback_data="list_today")],
        [InlineKeyboardButton("Outra data (DD/MM)", callback_data="list_other_date")],
        [InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="menu_back")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = "📅 Para qual data você deseja listar os atendimentos?"
    await update.callback_query.edit_message_text(text=message, reply_markup=reply_markup)
    return LISTAR_AWAITING_DATE


async def listar_date_selection(update: Update, context: CallbackContext) -> int:
    """Handles the user's date choice for listing."""
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == "list_today":
        selected_date = get_brazil_datetime_now().date()
        await list_records_for_date(update, context, selected_date)
        return ConversationHandler.END
    elif choice == "list_other_date":
        await query.edit_message_text("📅 Por favor, digite a data no formato `DD/MM`.")
        return LISTAR_AWAITING_DATE
    return ConversationHandler.END


async def listar_receive_date(update: Update, context: CallbackContext) -> int:
    """Receives the date and lists the records."""
    date_str = update.message.text
    try:
        current_year = get_brazil_datetime_now().year
        target_date = datetime.strptime(f"{date_str}/{current_year}", "%d/%m/%Y").date()
        await list_records_for_date(update, context, target_date)
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("⚠️ Data inválida. Use o formato DD/MM. Tente novamente ou use /cancelar.")
        return LISTAR_AWAITING_DATE


async def list_records_for_date(update: Update, context: CallbackContext, target_date) -> int:
    """Fetches and displays records for a specific date."""
    sheet = get_sheet()
    if not sheet:
        error_message = "⚠️ Erro de configuração: Não foi possível conectar à planilha. Operação cancelada."
        if update.callback_query:
            await update.callback_query.edit_message_text(error_message)
        else:
            await update.effective_message.reply_text(error_message)
        return ConversationHandler.END

    try:
        day_records = get_records_in_range(sheet, target_date, target_date)
        date_str = target_date.strftime("%d/%m/%Y")

        if not day_records:
            message = f"ℹ️ Nenhum atendimento encontrado para o dia {date_str}."
            if update.callback_query:
                await update.callback_query.edit_message_text(message)
            else:
                await update.effective_message.reply_text(message)
            await send_final_message(update)
            return ConversationHandler.END

        message = f"📋 *Atendimentos de {date_str}*\n\n"
        total_day_price = 0.0
        for record in day_records:
            procedure_slugs = [slugify(p.strip()) for p in record.get('Procedures', '').split(',')]
            procedure_names = [PROCEDURE_DESCRIPTIONS.get(slug, slug.upper()) for slug in procedure_slugs]
            patient_name = record.get('Patient', '').title()
            price = record.get('Price', 0.0)
            total_day_price += price
            message += (
                f"👤 *Paciente:* {patient_name}\n"
                f"   *Procedimentos:* {', '.join(procedure_names)}\n"
                f"   *Valor:* R$ {price:.2f}\n\n".replace('.', ',')
            )

        message += f"💰 *Total do dia:* R$ {total_day_price:.2f}".replace('.', ',')

        if update.callback_query:
            await update.callback_query.edit_message_text(message, parse_mode='Markdown')
        else:
            await update.effective_message.reply_text(message, parse_mode='Markdown')

        await send_final_message(update)
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error listing records: {e}")
        await update.effective_message.reply_text(f"⚠️ Erro ao buscar registros: {e}")
        return ConversationHandler.END


# --- CALCULAR Conversation ---
async def calcular_start(update: Update, context: CallbackContext) -> int:
    """Starts the sum calculation conversation."""
    keyboard = [
        [InlineKeyboardButton("Hoje", callback_data="calc_dia_today"), InlineKeyboardButton("Esta Semana", callback_data="calc_semana_this")],
        [InlineKeyboardButton("Este Mês", callback_data="calc_mes_this")],
        [InlineKeyboardButton("Outro Dia", callback_data="calc_dia_other"), InlineKeyboardButton("Outra Semana", callback_data="calc_semana_other")],
        [InlineKeyboardButton("Outro Mês", callback_data="calc_mes_other")],
        [InlineKeyboardButton("Período Específico", callback_data="calc_periodo")],
        [InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="menu_back")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = "📊 Escolha o período para o cálculo do faturamento:"
    await update.callback_query.edit_message_text(text=message, reply_markup=reply_markup)
    return CALC_SELECTING_MODE


async def calcular_mode_selection(update: Update, context: CallbackContext) -> int:
    """Handles the calculation mode selection."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split('_')
    mode, period = parts[1], parts[2] if len(parts) > 2 else None
    context.user_data['calc_mode'] = mode

    if period in ['today', 'this']:
        await process_sum_calculation(update, context, None)
        return ConversationHandler.END

    prompts = {
        'dia': "📅 Digite o dia (DD/MM/YYYY):",
        'semana': "📅 Digite uma data (DD/MM/YYYY) de referência para a semana:",
        'mes': "📅 Digite o mês (MM/YYYY) de referência:",
        'periodo': "📅 Digite a data de início e fim (DD/MM/YYYY DD/MM/YYYY):"
    }
    await query.edit_message_text(prompts[mode])
    return CALC_AWAITING_RANGE if mode == 'periodo' else CALC_AWAITING_DATE


async def calcular_receive_date(update: Update, context: CallbackContext) -> int:
    """Receives a single date for calculation."""
    await process_sum_calculation(update, context, update.message.text)
    return ConversationHandler.END


async def calcular_receive_range(update: Update, context: CallbackContext) -> int:
    """Receives a date range for calculation."""
    await process_sum_calculation(update, context, update.message.text)
    return ConversationHandler.END


async def process_sum_calculation(update: Update, context: CallbackContext, date_input: Optional[str]) -> int:
    """Fetches data and calculates the sum for the given mode and date."""
    mode = context.user_data.get('calc_mode')

    date_range_data = get_date_range_for_sum(mode, date_input)
    if not date_range_data:
        if update.callback_query:
            await update.callback_query.edit_message_text("⚠️ Data em formato inválido. Tente novamente ou /cancelar.")
        else:
            await update.effective_message.reply_text("⚠️ Data em formato inválido. Tente novamente ou /cancelar.")
        # Determine which state to return to based on the mode
        if mode == 'periodo':
            return CALC_AWAITING_RANGE
        else:
            return CALC_AWAITING_DATE

    start_date, end_date, period_str = date_range_data

    sheet = get_sheet()
    if not sheet:
        if update.callback_query:
            await update.callback_query.edit_message_text("⚠️ Erro de configuração: Não foi possível conectar à planilha.")
        else:
            await update.effective_message.reply_text("⚠️ Erro de configuração: Não foi possível conectar à planilha.")
        return ConversationHandler.END

    try:
        records_in_range = get_records_in_range(sheet, start_date, end_date)
        count = len(records_in_range)

        if count == 0:
            if update.callback_query:
                await update.callback_query.edit_message_text(f"ℹ️ Nenhum atendimento encontrado para {period_str}.")
            else:
                await update.effective_message.reply_text(f"ℹ️ Nenhum atendimento encontrado para {period_str}.")
        else:
            total = sum(record['Price'] for record in records_in_range)
            total_str = f"{total:.2f}".replace('.', ',')
            daily_summary = defaultdict(lambda: {'total': 0.0, 'count': 0})
            for record in records_in_range:
                record_date_obj = datetime.strptime(record['Date'], "%d/%m/%Y").date()
                daily_summary[record_date_obj]['total'] += record['Price']
                daily_summary[record_date_obj]['count'] += 1
            sorted_daily_summary = sorted(daily_summary.items())
            daily_breakdown = []
            for date_obj, summary_data in sorted_daily_summary:
                day_total_str = f"{summary_data['total']:.2f}".replace('.', ',')
                record_count = summary_data['count']
                record_text = 'atendimento' if record_count == 1 else 'atendimentos'
                daily_breakdown.append(f"{date_obj.strftime('%d/%m/%Y')} ({record_count} {record_text}): R$ {day_total_str}")

            message = "Resumo diário:\n" + "\n".join(daily_breakdown)

            if mode != 'dia':
                message += f"\n\n📊 *Total de {count} atendimentos para {period_str}: R$ {total_str}*"

            if update.callback_query:
                await update.callback_query.edit_message_text(message, parse_mode='Markdown')
            else:
                await update.effective_message.reply_text(message, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in process_sum_calculation: {e}")
        if update.callback_query:
            await update.callback_query.edit_message_text(f"⚠️ Erro ao calcular o total: {e}")
        else:
            await update.effective_message.reply_text(f"⚠️ Erro ao calcular o total: {e}")

    await send_final_message(update)
    context.user_data.clear()
    return ConversationHandler.END


async def cancel_command(update: Update, context: CallbackContext) -> int:
    """Cancels and ends the current conversation, returning to the main menu."""
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Operação cancelada. Voltando ao menu principal.")
    else:
        await update.message.reply_text("Operação cancelada. Voltando ao menu principal.")

    # We need to call menu_command to display the menu again.
    await menu_command(update, context)
    return ConversationHandler.END


async def post_init(application: Application) -> None:
    """Post-initialization function to set bot commands."""
    await application.bot.delete_my_commands()
    await application.bot.set_my_commands([
        ('menu', 'Exibe o menu principal de ações.'),
        ('cancelar', 'Cancela a operação atual e volta ao menu.')
    ])


def main() -> None:
    """Start the bot."""
    keep_alive()
    bot_token = os.environ.get("BOT_TOKEN")
    if not bot_token:
        logger.error("Environment variable BOT_TOKEN not set.")
        return

    application = Application.builder().token(bot_token).post_init(post_init).build()

    # Analytics reports
    analytics_handler = CallbackQueryHandler(analytics_router, pattern="^analytics_")

    # Conversation handler for the main menu
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("menu", menu_command),
            CommandHandler("start", menu_command),
            CallbackQueryHandler(menu_router, pattern="^menu_"),
        ],
        states={
            MENU: [
                CallbackQueryHandler(menu_router, pattern="^menu_"),
            ],
            REG_AWAITING_DATE: [
                CallbackQueryHandler(registrar_date_selection, pattern="^reg_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, registrar_receive_custom_date),
            ],
            REG_AWAITING_PATIENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, registrar_receive_patient)
            ],
            REG_SELECTING_PROCEDURES: [
                CallbackQueryHandler(registrar_procedure_selection, pattern="^proc_")
            ],
            REG_SELECTING_PRICE: [
                CallbackQueryHandler(registrar_price_selection, pattern="^price_")
            ],
            REG_CONFIRMING_MORE: [
                CallbackQueryHandler(registrar_confirm_more, pattern="^reg_another_")
            ],
            LISTAR_AWAITING_DATE: [
                CallbackQueryHandler(listar_date_selection, pattern="^list_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, listar_receive_date),
            ],
            CALC_SELECTING_MODE: [
                CallbackQueryHandler(calcular_mode_selection, pattern="^calc_")
            ],
            CALC_AWAITING_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, calcular_receive_date)
            ],
            CALC_AWAITING_RANGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, calcular_receive_range)
            ],
            DEL_AWAITING_DATE: [
                CallbackQueryHandler(deletar_date_selection, pattern="^del_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, deletar_receive_date)
            ],
            DEL_SELECTING_RECORD: [
                CallbackQueryHandler(deletar_ask_confirmation, pattern="^del_record_")
            ],
            DEL_CONFIRMING: [
                CallbackQueryHandler(deletar_receive_selection, pattern="^del_confirm_")
            ],
            ANALYTICS_MENU: [
                analytics_handler,
                CallbackQueryHandler(menu_command, pattern="^menu_back"),
            ],
        },
        fallbacks=[
            CommandHandler("cancelar", cancel_command),
            CallbackQueryHandler(cancel_command, pattern="^cancel$"),
            CallbackQueryHandler(cancel_command, pattern="^cancel_delete$"),
            CallbackQueryHandler(menu_command, pattern="^menu_back"),
        ],
        map_to_parent={
            ConversationHandler.END: MENU
        }
    )

    application.add_handler(conv_handler)
    application.run_polling()


if __name__ == "__main__":
    main()
