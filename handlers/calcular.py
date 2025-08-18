import logging
from collections import defaultdict
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
)

from constants import (
    CALC_AWAITING_DATE,
    CALC_AWAITING_RANGE,
    CALC_GET_CUSTOM_MONTH,
    CALC_MONTHLY_REPORT_CHOICE,
    CALC_SELECTING_MODE,
    DATE_FORMAT,
    MSG_CALC_CHOOSE_PERIOD,
    MSG_CALC_DAY_SUMMARY,
    MSG_CALC_DAY_TOTAL,
    MSG_CALC_GRAND_TOTAL,
    MSG_CALC_INVALID_DATE_RANGE,
    MSG_CALC_INVALID_MONTH_FORMAT,
    MSG_CALC_MONTHLY_REPORT_PROMPT,
    MSG_CALC_NO_RECORDS_FOUND,
    MSG_CALC_PROMPT_CUSTOM_MONTH,
)
from g_sheets import get_sheet
from utils import (
    format_currency,
    get_all_parsed_records,
    get_brazil_datetime_now,
    get_date_range_for_sum,
    get_info_from_record,
    get_monthly_report_date_range,
    get_records_in_range,
    handle_generic_error,
    handle_sheet_error,
    reply_or_edit,
    send_final_message,
)

logger = logging.getLogger(__name__)


# --- CALCULAR Conversation ---
async def calcular_start(update: Update, context: CallbackContext) -> int:
    """Starts the sum calculation conversation."""
    keyboard = [
        [
            InlineKeyboardButton("Hoje", callback_data="calc_dia_today"),
            InlineKeyboardButton("Esta Semana", callback_data="calc_semana_this"),
        ],
        [InlineKeyboardButton("Este Mês", callback_data="calc_mes_this")],
        [InlineKeyboardButton("Relatório Mensal", callback_data="calc_monthly_report")],
        [
            InlineKeyboardButton("Outro Dia", callback_data="calc_dia_other"),
            InlineKeyboardButton("Outra Semana", callback_data="calc_semana_other"),
        ],
        [InlineKeyboardButton("Outro Mês", callback_data="calc_mes_other")],
        [InlineKeyboardButton("Período Específico", callback_data="calc_periodo")],
        [InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="menu_back")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await reply_or_edit(update, text=MSG_CALC_CHOOSE_PERIOD, reply_markup=reply_markup)
    return CALC_SELECTING_MODE


async def calcular_mode_selection(update: Update, context: CallbackContext) -> int:
    """Handles the calculation mode selection."""
    query = update.callback_query
    await query.answer()

    if query.data == "calc_monthly_report":
        now = get_brazil_datetime_now()
        current_month_str = now.strftime("%m/%Y")
        keyboard = [
            [
                InlineKeyboardButton(
                    f"Este Mês [{current_month_str}]",
                    callback_data="calc_monthly_this",
                )
            ],
            [InlineKeyboardButton("Outro Mês", callback_data="calc_monthly_other")],
            [InlineKeyboardButton("🔙 Voltar", callback_data="calc_back_to_mode_selection")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            MSG_CALC_MONTHLY_REPORT_PROMPT,
            reply_markup=reply_markup,
        )
        return CALC_MONTHLY_REPORT_CHOICE

    parts = query.data.split("_")
    mode, period = parts[1], parts[2] if len(parts) > 2 else None
    context.user_data["calc_mode"] = mode

    if period in ["today", "this"]:
        await process_sum_calculation(update, context, None)
        return ConversationHandler.END

    prompts = {
        "dia": "📅 Digite o dia (DD/MM/YYYY):",
        "semana": "📅 Digite uma data (DD/MM/YYYY) de referência para a semana:",
        "mes": "📅 Digite o mês (MM/YYYY) de referência:",
        "periodo": "📅 Digite a data de início e fim (DD/MM/YYYY DD/MM/YYYY):",
    }
    await reply_or_edit(update, prompts[mode])
    return CALC_AWAITING_RANGE if mode == "periodo" else CALC_AWAITING_DATE


async def calcular_monthly_report_choice(update: Update, context: CallbackContext) -> int:
    """Handles the choice for the monthly report (current or other month)."""
    query = update.callback_query
    await query.answer()
    context.user_data["calc_mode"] = "periodo"

    if query.data == "calc_monthly_this":
        # Get date range for the current month's report
        date_range = get_monthly_report_date_range()
        start_date, end_date = date_range
        date_input = f"{start_date.strftime(DATE_FORMAT)} {end_date.strftime(DATE_FORMAT)}"
        await process_sum_calculation(update, context, date_input)
        return ConversationHandler.END

    if query.data == "calc_monthly_other":
        await query.edit_message_text(MSG_CALC_PROMPT_CUSTOM_MONTH)
        return CALC_GET_CUSTOM_MONTH

    # Handle 'calc_back_to_mode_selection'
    return await calcular_start(update, context)


async def calcular_receive_custom_month(update: Update, context: CallbackContext) -> int:
    """Receives a custom month (MM/YYYY) for the monthly report."""
    month_input = update.message.text
    context.user_data["calc_mode"] = "periodo"

    date_range = get_monthly_report_date_range(month_str=month_input)

    if not date_range:
        await update.message.reply_text(MSG_CALC_INVALID_MONTH_FORMAT)
        return CALC_GET_CUSTOM_MONTH

    start_date, end_date = date_range
    date_range_str = f"{start_date.strftime(DATE_FORMAT)} {end_date.strftime(DATE_FORMAT)}"
    await process_sum_calculation(update, context, date_range_str)
    return ConversationHandler.END


async def calcular_receive_date(update: Update, context: CallbackContext) -> int:
    """Receives a single date for calculation."""
    await process_sum_calculation(update, context, update.message.text)
    return ConversationHandler.END


async def calcular_receive_range(update: Update, context: CallbackContext) -> int:
    """Receives a date range for calculation."""
    await process_sum_calculation(update, context, update.message.text)
    return ConversationHandler.END


async def process_sum_calculation(
    update: Update, context: CallbackContext, date_input: str | None
) -> int:
    """Fetches data and calculates the sum for the given mode and date."""
    mode = context.user_data.get("calc_mode")

    date_range_data = get_date_range_for_sum(mode, date_input)
    if not date_range_data:
        await reply_or_edit(update, MSG_CALC_INVALID_DATE_RANGE)
        return CALC_AWAITING_RANGE if mode == "periodo" else CALC_AWAITING_DATE

    start_date, end_date, period_str = date_range_data

    sheet = get_sheet()
    if not sheet:
        await handle_sheet_error(update)
        return ConversationHandler.END

    try:
        all_records = get_all_parsed_records(sheet)
        records_in_range = get_records_in_range(all_records, start_date, end_date)
        count = len(records_in_range)

        if count == 0:
            await reply_or_edit(update, MSG_CALC_NO_RECORDS_FOUND.format(period_str))
        else:
            total = sum(record["parsed_price"] for record in records_in_range)
            total_str = format_currency(total)

            # Group records by date for detailed breakdown
            records_by_date = defaultdict(list)
            for record in records_in_range:
                records_by_date[record["Date"]].append(record)

            # Sort dates for chronological order
            sorted_dates = sorted(
                records_by_date.keys(), key=lambda d: datetime.strptime(d, DATE_FORMAT)
            )

            # Add a header for the report period
            report_header = (
                f"📄 *Relatório de Atendimentos*\n"
                f"🗓️ *Período:* de {start_date.strftime(DATE_FORMAT)} a {end_date.strftime(DATE_FORMAT)}\n"
                f"{'═' * 20}\n"
            )
            message_parts = [report_header]

            for i, date_str in enumerate(sorted_dates):
                # Add a separator between days
                if i > 0:
                    message_parts.append("\n" + "─" * 20 + "\n")

                day_records = records_by_date[date_str]
                day_total = sum(r["parsed_price"] for r in day_records)
                day_total_str = format_currency(day_total)
                record_count = len(day_records)
                record_text = "atendimento" if record_count == 1 else "atendimentos"

                # Add a more structured header for the day
                message_parts.append(
                    MSG_CALC_DAY_SUMMARY.format(
                        date=date_str, count=record_count, record_text=record_text
                    )
                )

                # Add individual records for the day
                for record in day_records:
                    patient, procs_display, price_str = get_info_from_record(record=record)
                    message_parts.append(f"  • *{patient}* | {procs_display} | {price_str}")

                message_parts.append(MSG_CALC_DAY_TOTAL.format(total=day_total_str))

            # Add a final separator before the grand total if applicable
            if mode != "dia" and len(sorted_dates) > 1:
                message_parts.append("\n" + "═" * 20)

            message = "\n".join(message_parts)

            # Add grand total summary if not for a single day
            if mode != "dia":
                message += MSG_CALC_GRAND_TOTAL.format(count=count, total=total_str)

            await reply_or_edit(update, message, parse_mode="Markdown")

    except Exception as e:
        return await handle_generic_error(update, e, context)

    await send_final_message(update)
    context.user_data.clear()
    return ConversationHandler.END
