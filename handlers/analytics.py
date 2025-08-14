from collections import defaultdict
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
)

from constants import ANALYTICS_MENU, PROCEDURE_DESCRIPTIONS
from g_sheets import get_sheet
from utils import send_final_message, slugify


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
    await update.callback_query.edit_message_text(
        text=message, reply_markup=reply_markup, parse_mode="Markdown"
    )
    return ANALYTICS_MENU


async def analytics_router(update: Update, context: CallbackContext) -> int:
    """Routes analytics menu button presses to the correct report function."""
    query = update.callback_query
    await query.answer()
    command = query.data

    sheet = get_sheet()
    if not sheet:
        await query.edit_message_text(
            "⚠️ Erro de configuração: Não foi possível conectar à planilha."
        )
        return ConversationHandler.END

    all_records = sheet.get_all_records()
    if not all_records:
        await query.edit_message_text("ℹ️ Não há dados suficientes para gerar análises.")
        return ConversationHandler.END

    # Pre-process records to parse dates and prices once
    processed_records = []
    for record in all_records:
        try:
            record["parsed_date"] = datetime.strptime(record.get("Date", ""), "%d/%m/%Y").date()
            record["parsed_price"] = float(str(record.get("Price", "0")).replace(",", "."))
            processed_records.append(record)
        except (ValueError, TypeError):
            continue  # Skip malformed records

    message_text = "Comando não reconhecido."
    if command == "analytics_revenue":
        message_text = analytics_show_revenue(processed_records)
    elif command == "analytics_appointments":
        message_text = analytics_show_appointments(processed_records)
    elif command == "analytics_procedures":
        message_text = analytics_show_procedures(processed_records)
    elif command == "analytics_patients":
        message_text = analytics_show_patients(processed_records)

    await query.edit_message_text(text=message_text, parse_mode="Markdown")

    # After showing the report, send the final message and end.
    await send_final_message(update)
    return ConversationHandler.END


def analytics_show_revenue(records: list[dict]) -> str:
    """Calculates and shows total revenue per month and grand total."""
    monthly_revenue = defaultdict(float)
    for record in records:
        month_key = record["parsed_date"].strftime("%m/%Y")
        monthly_revenue[month_key] += record["parsed_price"]

    if not monthly_revenue:
        return "Nenhum dado de faturamento encontrado."

    message = "💰 *Faturamento Mensal*\n\n"
    total_revenue = 0.0
    # Sort by month/year
    sorted_months = sorted(monthly_revenue.keys(), key=lambda m: datetime.strptime(m, "%m/%Y"))

    for month in sorted_months:
        revenue = monthly_revenue[month]
        total_revenue += revenue
        message += f"*{month}:* R$ {revenue:.2f}\n".replace(".", ",")

    message += f"\n*Total Geral:* R$ {total_revenue:.2f}".replace(".", ",")
    return message


def analytics_show_appointments(records: list[dict]) -> str:
    """Calculates and shows total appointments per month."""
    monthly_appointments = defaultdict(int)
    for record in records:
        month_key = record["parsed_date"].strftime("%m/%Y")
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
        month_key = record["parsed_date"].strftime("%m/%Y")
        procedures = record.get("Procedures", "").split(",")
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
            key=lambda item: (-item[1], PROCEDURE_DESCRIPTIONS.get(item[0], item[0].upper())),
        )
        for slug, count in sorted_procs:
            proc_name = PROCEDURE_DESCRIPTIONS.get(slug, slug.upper())
            message += f"  - {proc_name}: {count}\n"

    return message


def analytics_show_patients(records: list[dict]) -> str:
    """Calculates and shows patient appointment counts per month."""
    monthly_patients = defaultdict(lambda: defaultdict(int))
    for record in records:
        month_key = record["parsed_date"].strftime("%m/%Y")
        patient_name = record.get("Patient", "N/A").title()
        monthly_patients[month_key][patient_name] += 1

    if not monthly_patients:
        return "Nenhum paciente encontrado."

    message = "👤 *Ranking de Pacientes por Mês*\n"
    sorted_months = sorted(monthly_patients.keys(), key=lambda m: datetime.strptime(m, "%m/%Y"))

    for month in sorted_months:
        message += f"\n*{month}*\n"
        # Sort by count (desc) and then by name (asc)
        sorted_patients = sorted(
            monthly_patients[month].items(), key=lambda item: (-item[1], item[0])
        )
        for name, count in sorted_patients:
            message += f"  - {name}: {count}\n"

    return message
