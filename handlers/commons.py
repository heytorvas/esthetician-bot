import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
)

from constants import (
    DATE_FORMAT,
    MENU,
    MSG_ERROR_GENERIC,
    MSG_ERROR_NO_RECORDS_FOUND_FOR_DATE,
    MSG_ERROR_SHEET_CONNECTION,
    MSG_GREETING,
    MSG_MAIN_MENU,
)
from g_sheets import get_sheet
from utils import (
    format_currency,
    get_all_parsed_records,
    get_info_from_record,
    get_records_in_range,
    send_final_message,
)

logger = logging.getLogger(__name__)


async def menu_command(update: Update, context: CallbackContext) -> int:
    """Displays the main menu and sets the conversation state."""
    context.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("🚀 Registrar Novo Atendimento", callback_data="menu_registrar")],
        [
            InlineKeyboardButton(
                "📋 Listar | Calcular Atendimentos",
                callback_data="menu_calcular",
            )
        ],
        [InlineKeyboardButton("🗑️ Deletar Atendimento", callback_data="menu_deletar")],
        [InlineKeyboardButton("📈 Ver Análises", callback_data="menu_analytics")],
        [InlineKeyboardButton("ℹ️ Ver Procedimentos", callback_data="menu_procedimentos")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # If coming from a canceled operation or another menu, edit the message.
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(MSG_MAIN_MENU, reply_markup=reply_markup)
    else:
        await update.message.reply_text(
            MSG_GREETING,
            reply_markup=reply_markup,
        )
    return MENU


async def list_records_for_date(update: Update, context: CallbackContext, target_date) -> int:
    """Fetches and displays records for a specific date."""
    sheet = get_sheet()
    if not sheet:
        error_message = MSG_ERROR_SHEET_CONNECTION + " Operação cancelada."
        if update.callback_query:
            await update.callback_query.edit_message_text(error_message)
        else:
            await update.effective_message.reply_text(error_message)
        return ConversationHandler.END

    try:
        all_records = get_all_parsed_records(sheet)
        day_records = get_records_in_range(all_records, target_date, target_date)
        date_str = target_date.strftime(DATE_FORMAT)

        if not day_records:
            message = MSG_ERROR_NO_RECORDS_FOUND_FOR_DATE.format(date_str)
            if update.callback_query:
                await update.callback_query.edit_message_text(message)
            else:
                await update.effective_message.reply_text(message)
            await send_final_message(update)
            return ConversationHandler.END

        message_parts = [f"📋 *Atendimentos de {date_str}*\n"]
        total_day_price = 0.0

        for record in day_records:
            patient, procs_display, price_str = get_info_from_record(record)
            total_day_price += record["parsed_price"]
            message_parts.append(
                f"👤 *Paciente:* {patient}\n"
                f"   *Procedimentos:* {procs_display}\n"
                f"   *Valor:* {price_str}\n"
            )

        message_parts.append(f"💰 *Total do dia:* {format_currency(total_day_price)}")
        message = "\n".join(message_parts)

        if update.callback_query:
            await update.callback_query.edit_message_text(message, parse_mode="Markdown")
        else:
            await update.effective_message.reply_text(message, parse_mode="Markdown")

        await send_final_message(update)
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error listing records: {e}")
        await update.effective_message.reply_text(MSG_ERROR_GENERIC.format(e))
        return ConversationHandler.END
