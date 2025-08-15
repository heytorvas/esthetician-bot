import logging
from collections import defaultdict
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
)

from constants import (
    CALC_AWAITING_DATE,
    CALC_AWAITING_RANGE,
    CALC_SELECTING_MODE,
)
from g_sheets import get_sheet
from utils import (
    get_brazil_datetime_now,
    get_date_range_for_sum,
    get_info_from_record,
    get_records_in_range,
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
    message = "📊 Escolha o período para a listagem dos atendimentos:"
    await update.callback_query.edit_message_text(text=message, reply_markup=reply_markup)
    return CALC_SELECTING_MODE


async def calcular_mode_selection(update: Update, context: CallbackContext) -> int:
    """Handles the calculation mode selection."""
    query = update.callback_query
    await query.answer()

    if query.data == "calc_monthly_report":
        now = get_brazil_datetime_now()
        end_date = now.replace(day=6).date()
        # Go to the first day of the current month, then subtract one day to get to the last day of the previous month
        first_day_of_current_month = now.replace(day=1)
        last_day_of_previous_month = first_day_of_current_month - timedelta(days=1)
        start_date = last_day_of_previous_month.replace(day=7).date()

        context.user_data["calc_mode"] = "periodo"
        date_input = f"{start_date.strftime('%d/%m/%Y')} {end_date.strftime('%d/%m/%Y')}"
        await process_sum_calculation(update, context, date_input)
        return ConversationHandler.END

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
    await query.edit_message_text(prompts[mode])
    return CALC_AWAITING_RANGE if mode == "periodo" else CALC_AWAITING_DATE


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
        if update.callback_query:
            await update.callback_query.edit_message_text(
                "⚠️ Data em formato inválido. Tente novamente ou /cancelar."
            )
        else:
            await update.effective_message.reply_text(
                "⚠️ Data em formato inválido. Tente novamente ou /cancelar."
            )
        # Determine which state to return to based on the mode
        if mode == "periodo":
            return CALC_AWAITING_RANGE
        return CALC_AWAITING_DATE

    start_date, end_date, period_str = date_range_data

    sheet = get_sheet()
    if not sheet:
        if update.callback_query:
            await update.callback_query.edit_message_text(
                "⚠️ Erro de configuração: Não foi possível conectar à planilha."
            )
        else:
            await update.effective_message.reply_text(
                "⚠️ Erro de configuração: Não foi possível conectar à planilha."
            )
        return ConversationHandler.END

    try:
        records_in_range = get_records_in_range(sheet, start_date, end_date)
        count = len(records_in_range)

        if count == 0:
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    f"ℹ️ Nenhum atendimento encontrado para {period_str}."
                )
            else:
                await update.effective_message.reply_text(
                    f"ℹ️ Nenhum atendimento encontrado para {period_str}."
                )
        else:
            total = sum(record["Price"] for record in records_in_range)
            total_str = f"{total:.2f}".replace(".", ",")

            # Group records by date for detailed breakdown
            records_by_date = defaultdict(list)
            for record in records_in_range:
                records_by_date[record["Date"]].append(record)

            # Sort dates for chronological order
            sorted_dates = sorted(
                records_by_date.keys(), key=lambda d: datetime.strptime(d, "%d/%m/%Y")
            )

            message_parts = []
            for i, date_str in enumerate(sorted_dates):
                # Add a separator between days
                if i > 0:
                    message_parts.append("\n" + "─" * 20 + "\n")

                day_records = records_by_date[date_str]
                day_total = sum(r["Price"] for r in day_records)
                day_total_str = f"{day_total:.2f}".replace(".", ",")
                record_count = len(day_records)
                record_text = "atendimento" if record_count == 1 else "atendimentos"

                # Add a more structured header for the day
                message_parts.append(f"🗓️ *{date_str}* ({record_count} {record_text})")

                # Add individual records for the day
                for record in day_records:
                    patient, procs_display, price_str = get_info_from_record(record=record)
                    message_parts.append(f"  • *{patient}* | {procs_display} | R$ {price_str}")

                message_parts.append(f"\n💰 *Total do Dia:* R$ {day_total_str}")

            # Add a final separator before the grand total if applicable
            if mode != "dia" and len(sorted_dates) > 1:
                message_parts.append("\n" + "═" * 20)

            message = "\n".join(message_parts)

            # Add grand total summary if not for a single day
            if mode != "dia":
                message += (
                    f"\n\n📊 *Total de {count} atendimentos para {period_str}: R$ {total_str}*"
                )

            if update.callback_query:
                await update.callback_query.edit_message_text(message, parse_mode="Markdown")
            else:
                await update.effective_message.reply_text(message, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in process_sum_calculation: {e}")
        if update.callback_query:
            await update.callback_query.edit_message_text(f"⚠️ Erro ao calcular o total: {e}")
        else:
            await update.effective_message.reply_text(f"⚠️ Erro ao calcular o total: {e}")

    await send_final_message(update)
    context.user_data.clear()
    return ConversationHandler.END
