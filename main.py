import base64
import json
import logging
import os
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CallbackContext,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
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
    REG_SELECTING_DATE,
    REG_ENTERING_RECORD,
    REG_CONFIRMING_MORE,
    # Listar States
    LISTAR_AWAITING_DATE,
    # Calcular States
    CALC_SELECTING_MODE,
    CALC_AWAITING_DATE,
    CALC_AWAITING_RANGE,
    # Analytics States
    ANALYTICS_MENU,
) = range(9)


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


# --- Utility Functions ---
def slugify(text):
    """Converts a string into a 'slug' for consistent matching."""
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    text = text.lower()
    text = text.replace(" ", "").replace("-", "")
    return text


def parse_record_text(text: str, procedure_descriptions: dict) -> tuple[str, list[str], float] | None:
    """
    Parses a text string to extract patient name, procedures, and price.

    Args:
        text: The input string (e.g., "Tom Brady Pós Operatório, Limpeza de Pele 150.50").
        procedure_descriptions: A dictionary mapping slugs to full procedure names.

    Returns:
        A tuple containing (patient_name, list_of_found_procedures, price),
        or None if parsing fails.
    """
    args = text.split()
    if len(args) < 2:
        return None

    # 1. Extract and validate the price from the end of the string
    try:
        price = float(args[-1].replace(',', '.'))
        name_and_procs_text = " ".join(args[:-1]).strip()
    except ValueError:
        return None # Price not found or invalid

    # 2. Create a master regex to find all known procedures flexibly.
    # This is the robust way to handle variations in user input.
    sorted_proc_names = sorted(procedure_descriptions.values(), key=len, reverse=True)
    proc_patterns = []
    for name in sorted_proc_names:
        # Split by space to handle multi-word procedures
        words = name.split(' ')
        processed_words = []
        for word in words:
            # Handle accents for each word
            word_pattern = word.replace('á', '[aá]').replace('é', '[eé]').replace('í', '[ií]').replace('ó', '[oó]').replace('ú', '[uú]').replace('â', '[aâ]').replace('ê', '[eê]').replace('ô', '[oô]').replace('ã', '[aã]').replace('õ', '[oõ]').replace('ç', '[cç]')
            processed_words.append(word_pattern)

        # Join the processed words with the flexible separator
        pattern = r'[-\s,]*'.join(processed_words)
        proc_patterns.append(pattern)

    master_pattern = re.compile('|'.join(proc_patterns), re.IGNORECASE)

    # 3. Find all procedure matches in the text
    matches = list(master_pattern.finditer(name_and_procs_text))
    if not matches:
        return None # No valid procedures found

    # 4. Reconstruct the patient's name from the parts of the string that are not procedures
    patient_parts = []
    last_index = 0
    for match in matches:
        patient_parts.append(name_and_procs_text[last_index:match.start()])
        last_index = match.end()
    patient_parts.append(name_and_procs_text[last_index:])

    patient_name = "".join(patient_parts).strip(" ,-")
    if not patient_name:
        return None # Patient name could not be determined

    # 5. Normalize the found procedures back to their canonical names
    slug_to_name_map = {slugify(name): name for name in procedure_descriptions.values()}
    found_procedures = [slug_to_name_map[slugify(match.group(0))] for match in matches]

    return patient_name, found_procedures, price


def get_records_in_range(sheet, start_date: datetime.date, end_date: datetime.date) -> list[dict]:
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


def get_date_range_for_sum(mode: str, date_input: str | None) -> tuple[datetime.date, datetime.date, str] | None:
    """Calculates the start date, end date, and a descriptive string for a given mode."""
    now = datetime.now()
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
        [InlineKeyboardButton("📊 Calcular Faturamento", callback_data="menu_calcular")],
        [InlineKeyboardButton("📋 Listar Atendimentos de um Dia", callback_data="menu_listar")],
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
    elif command == 'menu_analytics':
        return await analytics_start(update, context)
    elif command == 'menu_procedimentos':
        await procedimentos_command(update, context)
        await query.edit_message_text("Lista de procedimentos exibida acima. Use /menu para voltar ao menu.")
        return ConversationHandler.END

    return ConversationHandler.END


async def procedimentos_command(update: Update, context: CallbackContext) -> None:
    """Lists all available procedures and their descriptions."""
    message = "📋 Procedimentos Disponíveis:\n\n"
    for slug, description in PROCEDURE_DESCRIPTIONS.items():
        message += f"• {description}\n"
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

    if command == 'analytics_revenue':
        await analytics_show_revenue(update, processed_records)
    elif command == 'analytics_appointments':
        await analytics_show_appointments(update, processed_records)
    elif command == 'analytics_procedures':
        await analytics_show_procedures(update, processed_records)
    elif command == 'analytics_patients':
        await analytics_show_patients(update, processed_records)

    # After showing the report, show the analytics menu again
    await query.message.reply_text("Use /menu para voltar ao menu principal ou escolha outra análise abaixo.")
    await analytics_start(update, context)
    return ANALYTICS_MENU


async def analytics_show_revenue(update: Update, records: list[dict]):
    """Calculates and shows total revenue per month and grand total."""
    monthly_revenue = defaultdict(float)
    for record in records:
        month_key = record['parsed_date'].strftime("%m/%Y")
        monthly_revenue[month_key] += record['parsed_price']

    if not monthly_revenue:
        await update.effective_message.reply_text("Nenhum dado de faturamento encontrado.")
        return

    message = "💰 *Faturamento Mensal*\n\n"
    total_revenue = 0.0
    # Sort by month/year
    sorted_months = sorted(monthly_revenue.keys(), key=lambda m: datetime.strptime(m, "%m/%Y"))

    for month in sorted_months:
        revenue = monthly_revenue[month]
        total_revenue += revenue
        message += f"*{month}:* R$ {revenue:.2f}\n".replace('.', ',')

    message += f"\n*Total Geral:* R$ {total_revenue:.2f}".replace('.', ',')
    await update.effective_message.reply_text(message, parse_mode='Markdown')


async def analytics_show_appointments(update: Update, records: list[dict]):
    """Calculates and shows total appointments per month."""
    monthly_appointments = defaultdict(int)
    for record in records:
        month_key = record['parsed_date'].strftime("%m/%Y")
        monthly_appointments[month_key] += 1

    if not monthly_appointments:
        await update.effective_message.reply_text("Nenhum atendimento encontrado.")
        return

    message = "📅 *Atendimentos por Mês*\n\n"
    sorted_months = sorted(monthly_appointments.keys(), key=lambda m: datetime.strptime(m, "%m/%Y"))

    for month in sorted_months:
        count = monthly_appointments[month]
        message += f"*{month}:* {count} atendimentos\n"

    await update.effective_message.reply_text(message, parse_mode='Markdown')


async def analytics_show_procedures(update: Update, records: list[dict]):
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
        await update.effective_message.reply_text("Nenhum procedimento encontrado.")
        return

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

    await update.effective_message.reply_text(message, parse_mode='Markdown')


async def analytics_show_patients(update: Update, records: list[dict]):
    """Calculates and shows patient appointment counts per month."""
    monthly_patients = defaultdict(lambda: defaultdict(int))
    for record in records:
        month_key = record['parsed_date'].strftime("%m/%Y")
        patient_name = record.get('Patient', 'N/A').title()
        monthly_patients[month_key][patient_name] += 1

    if not monthly_patients:
        await update.effective_message.reply_text("Nenhum paciente encontrado.")
        return

    message = "👤 *Ranking de Pacientes por Mês*\n"
    sorted_months = sorted(monthly_patients.keys(), key=lambda m: datetime.strptime(m, "%m/%Y"))

    for month in sorted_months:
        message += f"\n*{month}*\n"
        # Sort by count (desc) and then by name (asc)
        sorted_patients = sorted(monthly_patients[month].items(), key=lambda item: (-item[1], item[0]))
        for name, count in sorted_patients:
            message += f"  - {name}: {count}\n"

    await update.effective_message.reply_text(message, parse_mode='Markdown')


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
        selected_date = datetime.now().date()
        return await list_records_for_date(update, context, selected_date)
    elif choice == "list_other_date":
        await query.edit_message_text("📅 Por favor, digite a data no formato `DD/MM`.")
        return LISTAR_AWAITING_DATE
    return ConversationHandler.END


async def listar_receive_date(update: Update, context: CallbackContext) -> int:
    """Receives the date and lists the records."""
    date_str = update.message.text
    try:
        current_year = datetime.now().year
        target_date = datetime.strptime(f"{date_str}/{current_year}", "%d/%m/%Y").date()
        await list_records_for_date(update, context, target_date)
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("⚠️ Data inválida. Use o formato DD/MM. Tente novamente ou use /cancelar.")
        return LISTAR_AWAITING_DATE


async def list_records_for_date(update: Update, context: CallbackContext, target_date: datetime.date) -> None:
    """Fetches and displays records for a specific date."""
    sheet = get_sheet()
    if not sheet:
        await update.effective_message.reply_text("⚠️ Erro de configuração: Não foi possível conectar à planilha. Operação cancelada.")
        return

    try:
        day_records = get_records_in_range(sheet, target_date, target_date)
        date_str = target_date.strftime("%d/%m/%Y")

        if not day_records:
            await update.effective_message.reply_text(f"ℹ️ Nenhum atendimento encontrado para o dia {date_str}.")
        else:
            message = f"📋 *Atendimentos de {date_str}*\n\n"
            total_day_price = 0.0
            for record in day_records:
                procedure_slugs = [slugify(p.strip()) for p in record.get('Procedures', '').split(',')]
                procedure_names = [PROCEDURE_DESCRIPTIONS.get(slug, slug.upper()) for slug in procedure_slugs]
                patient_name = record.get('Patient', '').title()
                price = record['Price']
                price_str = f"{price:.2f}".replace('.', ',')
                message += f"Paciente: *{patient_name}*\nProcedimentos: *{', '.join(procedure_names)}*\nValor: *R$ {price_str}*\n\n"
                total_day_price += price

            total_price_str = f"{total_day_price:.2f}".replace('.', ',')
            message += f"💰 *Total do dia: {total_price_str}*"
            await update.effective_message.reply_text(message, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error in list_records_for_date: {e}")
        await update.effective_message.reply_text(f"⚠️ Erro ao buscar registros: {e}")

    await send_final_message(update)


# --- REGISTRAR Conversation ---
async def registrar_start(update: Update, context: CallbackContext) -> int:
    """Starts the registration conversation by asking for the date."""
    context.user_data['records_for_date'] = []
    keyboard = [
        [InlineKeyboardButton("Hoje", callback_data="reg_today")],
        [InlineKeyboardButton("Outra data (DD/MM)", callback_data="reg_other_date")],
        [InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="menu_back")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = "🗓️ Para qual data você deseja registrar um atendimento?"
    await update.callback_query.edit_message_text(text=message_text, reply_markup=reply_markup)
    return REG_SELECTING_DATE


async def registrar_date_selection(update: Update, context: CallbackContext) -> int:
    """Handles the user's date choice."""
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == "reg_today":
        selected_date = datetime.now().date()
        context.user_data['selected_date'] = selected_date
        await query.edit_message_text(f"Data selecionada: {selected_date.strftime('%d/%m/%Y')}. \n\n✍️ Agora, por favor, insira o atendimento no formato:\n`<Nome do Paciente> <Procedimentos> <Valor>`")
        return REG_ENTERING_RECORD
    elif choice == "reg_other_date":
        await query.edit_message_text("📅 Por favor, digite a data no formato `DD/MM`.")
        return REG_SELECTING_DATE
    return ConversationHandler.END


async def registrar_receive_custom_date(update: Update, context: CallbackContext) -> int:
    """Parses a custom date in DD/MM format."""
    date_str = update.message.text
    try:
        current_year = datetime.now().year
        selected_date = datetime.strptime(f"{date_str}/{current_year}", "%d/%m/%Y").date()
        context.user_data['selected_date'] = selected_date
        await update.message.reply_text(f"Data selecionada: {selected_date.strftime('%d/%m/%Y')}. \n\n✍️ Agora, por favor, insira o atendimento no formato:\n`<Nome do Paciente> <Procedimentos> <Valor>`")
        return REG_ENTERING_RECORD
    except ValueError:
        await update.message.reply_text("⚠️ Data inválida. Por favor, use o formato `DD/MM`. Tente novamente ou use /cancelar.")
        return REG_SELECTING_DATE


async def registrar_receive_record(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives and processes a single record entry by calling the parsing utility."""
    full_text = update.message.text

    parsed_data = parse_record_text(full_text, PROCEDURE_DESCRIPTIONS)

    if not parsed_data:
        await update.message.reply_text(
            "⚠️ Formato inválido. Não consegui entender a sua mensagem.\n\n"
            "Use o formato: `<Nome do Paciente> <Procedimentos> <Valor>`\n"
            "Exemplo: `Maria Silva Pós Operatório 150`"
        )
        return REG_ENTERING_RECORD

    patient, found_procedures, price = parsed_data

    valid_procedures_slugs = [slugify(p) for p in found_procedures]

    sheet = get_sheet()
    if not sheet:
        await update.message.reply_text("⚠️ Erro de configuração: Não foi possível conectar à planilha.")
        return ConversationHandler.END

    # Store data in uppercase
    patient_upper = patient.upper()
    procedures_upper = ', '.join(slug.upper() for slug in valid_procedures_slugs)
    row = [context.user_data['selected_date'].strftime("%d/%m/%Y"), patient_upper, procedures_upper, price]

    try:
        sheet.append_row(row)
        # For display, use proper names
        procedure_full_names = sorted([PROCEDURE_DESCRIPTIONS[slug] for slug in valid_procedures_slugs])

        context.user_data.setdefault('records_for_date', []).append({
            "patient": patient.title(),
            "procedures": ', '.join(procedure_full_names),
            "price": price
        })

        price_str = f"R$ {price:.2f}".replace('.', ',')
        reply_message = (
            f"✅ *Atendimento Salvo!*\n\n"
            f"Paciente: *{patient.title()}*\n"
            f"Procedimentos: *{', '.join(procedure_full_names)}*\n"
            f"Valor: *{price_str}*"
        )
        await update.message.reply_text(reply_message, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error saving to sheet in conversation: {e}")
        await update.message.reply_text(f"⚠️ Ocorreu um erro ao salvar na planilha: {e}")
        return REG_ENTERING_RECORD

    keyboard = [[InlineKeyboardButton("Sim", callback_data="reg_more_yes"), InlineKeyboardButton("Não", callback_data="reg_more_no")]]
    await update.message.reply_text("Deseja inserir outro atendimento para esta mesma data?", reply_markup=InlineKeyboardMarkup(keyboard))
    return REG_CONFIRMING_MORE


async def registrar_confirm_more(update: Update, context: CallbackContext) -> int:
    """Handles user choice to add more records or finish."""
    query = update.callback_query
    await query.answer()
    if query.data == "reg_more_yes":
        await query.edit_message_text("✍️ Ok, insira o próximo atendimento...")
        return REG_ENTERING_RECORD
    else:
        await query.edit_message_text("✅ Concluído!")
        await end_registration_and_summarize(update, context)
        return ConversationHandler.END


async def end_registration_and_summarize(update: Update, context: CallbackContext):
    """
    Displays a summary of all records for the selected date by re-fetching them
    from the spreadsheet to ensure data is up-to-date.
    """
    selected_date = context.user_data.get('selected_date')
    if not selected_date:
        logger.warning("end_registration_and_summarize called without a selected_date.")
        await update.effective_message.reply_text("Não foi possível gerar o resumo. Por favor, use o comando /listar para ver os registros.")
        return

    await update.effective_message.reply_text(f"Gerando resumo final para {selected_date.strftime('%d/%m/%Y')}...")

    # Reuse the existing function to fetch, format, and send the summary for the selected date.
    # This ensures the summary is always accurate and reflects all records in the sheet.
    await list_records_for_date(update, context, selected_date)

    context.user_data.clear()


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
        return await process_sum_calculation(update, context, None)

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


async def process_sum_calculation(update: Update, context: ContextTypes.DEFAULT_TYPE, date_input: str | None) -> None:
    """Fetches data and calculates the sum for the given mode and date."""
    mode = context.user_data.get('calc_mode')

    date_range_data = get_date_range_for_sum(mode, date_input)
    if not date_range_data:
        await update.effective_message.reply_text("⚠️ Data em formato inválido. Tente novamente ou /cancelar.")
        # Determine which state to return to based on the mode
        if mode == 'periodo':
            context.user_data['next_state'] = CALC_AWAITING_RANGE
        else:
            context.user_data['next_state'] = CALC_AWAITING_DATE
        return

    start_date, end_date, period_str = date_range_data

    sheet = get_sheet()
    if not sheet:
        await update.effective_message.reply_text("⚠️ Erro de configuração: Não foi possível conectar à planilha.")
        return

    try:
        records_in_range = get_records_in_range(sheet, start_date, end_date)
        count = len(records_in_range)

        if count == 0:
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

            await update.effective_message.reply_text(message, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error in process_sum_calculation: {e}")
        await update.effective_message.reply_text(f"⚠️ Erro ao calcular o total: {e}")

    await send_final_message(update)
    context.user_data.clear()


async def cancel_command(update: Update, context: CallbackContext) -> int:
    """Cancels and ends the current conversation, returning to the main menu."""
    await update.message.reply_text("Operação cancelada. Voltando ao menu principal.")
    # We need to call menu_command to display the menu again.
    # Since cancel is a CommandHandler, it doesn't have a callback_query.
    # We pass a modified update object.
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

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", menu_command), CommandHandler("menu", menu_command)],
        states={
            MENU: [CallbackQueryHandler(menu_router, pattern='^menu_')],
            # Registrar States
            REG_SELECTING_DATE: [
                CallbackQueryHandler(registrar_date_selection, pattern='^reg_'),
                MessageHandler(filters.TEXT & ~filters.COMMAND, registrar_receive_custom_date)
            ],
            REG_ENTERING_RECORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, registrar_receive_record)],
            REG_CONFIRMING_MORE: [CallbackQueryHandler(registrar_confirm_more, pattern='^reg_more_')],
            # Listar States
            LISTAR_AWAITING_DATE: [
                CallbackQueryHandler(listar_date_selection, pattern='^list_'),
                MessageHandler(filters.TEXT & ~filters.COMMAND, listar_receive_date)
            ],
            # Analytics States
            ANALYTICS_MENU: [CallbackQueryHandler(analytics_router, pattern='^analytics_')],
            # Calcular States
            CALC_SELECTING_MODE: [CallbackQueryHandler(calcular_mode_selection, pattern='^calc_')],
            CALC_AWAITING_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, calcular_receive_date)],
            CALC_AWAITING_RANGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, calcular_receive_range)],
        },
        fallbacks=[
            CommandHandler("cancelar", cancel_command),
            CallbackQueryHandler(menu_command, pattern='^menu_back$')
        ],
    )

    application.add_handler(conv_handler)
    application.run_polling()


if __name__ == '__main__':
    main()
