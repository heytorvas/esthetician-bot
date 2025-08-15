from collections import defaultdict
from datetime import date, datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
)

from constants import (
    ANALYTICS_MENU,
    MSG_ANALYTICS_MENU,
    MSG_ANALYTICS_NO_APPOINTMENTS,
    MSG_ANALYTICS_NO_PATIENTS,
    MSG_ANALYTICS_NO_PROCEDURES,
    MSG_ANALYTICS_NO_REVENUE,
    MSG_ANALYTICS_UNKNOWN_COMMAND,
    MSG_ERROR_NO_DATA_FOR_ANALYTICS,
    PROCEDURE_DESCRIPTIONS,
)
from g_sheets import get_sheet
from utils import (
    format_currency,
    get_all_parsed_records,
    handle_sheet_error,
    reply_or_edit,
    send_final_message,
)


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
    await reply_or_edit(
        update, text=MSG_ANALYTICS_MENU, reply_markup=reply_markup, parse_mode="Markdown"
    )
    return ANALYTICS_MENU


async def analytics_router(update: Update, context: CallbackContext) -> int:
    """Routes analytics menu button presses to the correct report function."""
    query = update.callback_query
    await query.answer()
    command = query.data

    sheet = get_sheet()
    if not sheet:
        await handle_sheet_error(update)
        return ConversationHandler.END

    all_records = get_all_parsed_records(sheet)
    if not all_records:
        await reply_or_edit(update, MSG_ERROR_NO_DATA_FOR_ANALYTICS)
        return ConversationHandler.END

    message_text = MSG_ANALYTICS_UNKNOWN_COMMAND
    if command == "analytics_revenue":
        message_text = analytics_show_revenue(all_records)
    elif command == "analytics_appointments":
        message_text = analytics_show_appointments(all_records)
    elif command == "analytics_procedures":
        message_text = analytics_show_procedures(all_records)
    elif command == "analytics_patients":
        message_text = analytics_show_patients(all_records)

    await reply_or_edit(update, text=message_text, parse_mode="Markdown")

    # After showing the report, send the final message and end.
    await send_final_message(update)
    return ConversationHandler.END


def _group_records_by_month(records: list[dict]) -> dict[str, list[dict]]:
    """Groups a list of records into a dictionary keyed by month ('MM/YYYY')."""
    monthly_groups = defaultdict(list)
    for record in records:
        month_key = _get_custom_month(record["parsed_date"])
        monthly_groups[month_key].append(record)
    return monthly_groups


def _get_custom_month(record_date: date) -> str:
    if record_date.day < 7:
        if record_date.month == 1:
            mo, yr = 12, record_date.year - 1
        else:
            mo, yr = record_date.month - 1, record_date.year
    else:
        mo, yr = record_date.month, record_date.year
    return f"{mo}/{yr}"


def analytics_show_revenue(records: list[dict]) -> str:
    """Calculates and shows total revenue per month and grand total."""
    monthly_groups = _group_records_by_month(records)
    if not monthly_groups:
        return MSG_ANALYTICS_NO_REVENUE

    message = "💰 *Faturamento Mensal*\n\n"
    total_revenue = 0.0
    # Sort by month/year
    sorted_months = sorted(monthly_groups.keys(), key=lambda m: datetime.strptime(m, "%m/%Y"))

    for month in sorted_months:
        monthly_records = monthly_groups[month]
        month_revenue = sum(record.get("parsed_price", 0.0) for record in monthly_records)
        total_revenue += month_revenue
        message += f"*{month}:* {format_currency(month_revenue)}\n"

    message += f"\n*Total Geral:* {format_currency(total_revenue)}"
    return message


def analytics_show_appointments(records: list[dict]) -> str:
    """Calculates and shows total appointments per month."""
    monthly_groups = _group_records_by_month(records)
    if not monthly_groups:
        return MSG_ANALYTICS_NO_APPOINTMENTS

    message = "📅 *Atendimentos por Mês*\n\n"
    sorted_months = sorted(monthly_groups.keys(), key=lambda m: datetime.strptime(m, "%m/%Y"))

    for month in sorted_months:
        count = len(monthly_groups[month])
        message += f"*{month}:* {count} atendimentos\n"

    return message


def analytics_show_procedures(records: list[dict]) -> str:
    """Calculates and shows procedure counts per month."""
    monthly_procedures = defaultdict(lambda: defaultdict(int))
    for record in records:
        month_key = _get_custom_month(record["parsed_date"])
        procedures = record.get("Procedures", "").split(",")
        for proc in procedures:
            slug = proc.strip().lower()
            if slug in PROCEDURE_DESCRIPTIONS:
                monthly_procedures[month_key][slug] += 1

    if not monthly_procedures:
        return MSG_ANALYTICS_NO_PROCEDURES

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
        month_key = _get_custom_month(record["parsed_date"])
        patient_name = record.get("Patient", "N/A").title()
        monthly_patients[month_key][patient_name] += 1

    if not monthly_patients:
        return MSG_ANALYTICS_NO_PATIENTS

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
