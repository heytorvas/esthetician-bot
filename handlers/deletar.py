import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
)

from constants import (
    DATE_FORMAT,
    DEL_AWAITING_DATE,
    DEL_CONFIRMING,
    DEL_SELECTING_RECORD,
    MSG_DEL_ASK_DATE,
    MSG_DEL_CONFIRM,
    MSG_DEL_RETURN_TO_LIST,
    MSG_DEL_SELECT_RECORD,
    MSG_DEL_SUCCESS,
    MSG_ERROR_DELETION,
    MSG_ERROR_INVALID_DATE_FORMAT_DDMM,
    MSG_ERROR_NO_RECORDS_FOUND_FOR_DATE,
    MSG_ERROR_RECORD_NOT_FOUND,
    MSG_OPERATION_CANCELLED,
    MSG_PROMPT_DATE_DDMM,
)
from g_sheets import get_sheet
from handlers.commons import menu_command
from utils import (
    get_all_parsed_records,
    get_brazil_datetime_now,
    get_info_from_record,
    get_records_in_range,
    handle_sheet_error,
    parse_ddmm_date,
    reply_or_edit,
    send_final_message,
)

logger = logging.getLogger(__name__)


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
    await reply_or_edit(update, text=MSG_DEL_ASK_DATE, reply_markup=reply_markup)
    return DEL_AWAITING_DATE


async def deletar_date_selection(update: Update, context: CallbackContext) -> int:
    """Handles the user's date choice for deletion."""
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == "del_today":
        selected_date = get_brazil_datetime_now().date()
        return await list_records_for_deletion(update, context, selected_date)
    if choice == "del_other_date":
        await reply_or_edit(update, MSG_PROMPT_DATE_DDMM)
        return DEL_AWAITING_DATE
    return ConversationHandler.END


async def list_records_for_deletion(update: Update, context: CallbackContext, target_date) -> int:
    """Lists records for a given date as selectable buttons for deletion."""
    sheet = get_sheet()
    if not sheet:
        await handle_sheet_error(update)
        return ConversationHandler.END

    all_records = get_all_parsed_records(sheet, include_row_number=True)
    records_to_delete = get_records_in_range(all_records, target_date, target_date)

    date_str = target_date.strftime(DATE_FORMAT)
    if not records_to_delete:
        message = MSG_ERROR_NO_RECORDS_FOUND_FOR_DATE.format(date_str)
        if update.callback_query:
            await update.callback_query.answer(text=message, show_alert=True)
            await menu_command(update, context)
        else:
            await reply_or_edit(update, f"{message} Use /menu para começar de novo.")
        return ConversationHandler.END

    context.user_data["records_for_deletion"] = records_to_delete
    context.user_data["delete_date"] = target_date

    keyboard = []
    message = MSG_DEL_SELECT_RECORD.format(date_str)

    for record in records_to_delete:
        patient, procs_display, price_str = get_info_from_record(record=record)
        button_text = f"{patient} | {procs_display} | {price_str}"
        callback_data = f"del_record_{record['row_number']}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

    keyboard.append([InlineKeyboardButton("🔙 Cancelar", callback_data="cancel_delete")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await reply_or_edit(update, message, reply_markup=reply_markup, parse_mode="Markdown")

    return DEL_SELECTING_RECORD


async def deletar_receive_date(update: Update, context: CallbackContext) -> int:
    """Receives a custom date and lists records for deletion."""
    date_str = update.message.text
    target_date = parse_ddmm_date(date_str)
    if not target_date:
        await reply_or_edit(update, MSG_ERROR_INVALID_DATE_FORMAT_DDMM)
        return DEL_AWAITING_DATE
    return await list_records_for_deletion(update, context, target_date)


async def deletar_ask_confirmation(update: Update, context: CallbackContext) -> int:
    """Asks the user to confirm the deletion of a specific record."""
    query = update.callback_query
    await query.answer()
    row_number = int(query.data.replace("del_record_", ""))
    context.user_data["row_to_delete"] = row_number

    # Find the record details to show in the confirmation message
    records = context.user_data.get("records_for_deletion", [])
    record_to_delete = next((r for r in records if r["row_number"] == row_number), None)

    if not record_to_delete:
        await reply_or_edit(update, MSG_ERROR_RECORD_NOT_FOUND)
        return await list_records_for_deletion(update, context, context.user_data["delete_date"])

    patient, procs_display, price_str = get_info_from_record(record=record_to_delete)

    message = MSG_DEL_CONFIRM.format(patient=patient, procedures=procs_display, price=price_str)

    keyboard = [
        [
            InlineKeyboardButton("Sim, deletar", callback_data="del_confirm_yes"),
            InlineKeyboardButton("Não, voltar", callback_data="del_confirm_no"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await reply_or_edit(update, message, reply_markup=reply_markup, parse_mode="Markdown")

    return DEL_CONFIRMING


async def deletar_receive_selection(update: Update, context: CallbackContext) -> int:
    """Receives the user's confirmation and deletes the record."""
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == "del_confirm_no":
        target_date = context.user_data.get("delete_date")
        if target_date:
            await reply_or_edit(update, MSG_DEL_RETURN_TO_LIST)
            return await list_records_for_deletion(update, context, target_date)
        await reply_or_edit(update, MSG_OPERATION_CANCELLED)
        await menu_command(update, context)
        return ConversationHandler.END

    # Proceed with deletion if 'yes'
    try:
        row_number_to_delete = context.user_data.get("row_to_delete")
        if not row_number_to_delete:
            raise ValueError("Row number to delete not found in context.")

        sheet = get_sheet()
        if not sheet:
            await handle_sheet_error(update)
            return ConversationHandler.END

        sheet.delete_rows(row_number_to_delete)
        await reply_or_edit(update, MSG_DEL_SUCCESS)

        # Send the standard final message
        await send_final_message(update)

        context.user_data.clear()
        return ConversationHandler.END

    except (ValueError, IndexError) as e:
        logger.error(f"Error during deletion confirmation: {e}")
        await reply_or_edit(update, MSG_ERROR_DELETION)
        return ConversationHandler.END
