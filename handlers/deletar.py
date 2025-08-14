import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
)

from constants import (
    DEL_AWAITING_DATE,
    DEL_CONFIRMING,
    DEL_SELECTING_RECORD,
    PROCEDURE_DESCRIPTIONS,
)
from g_sheets import get_sheet
from handlers.commons import menu_command
from utils import get_brazil_datetime_now, send_final_message, slugify

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
    if choice == "del_other_date":
        await query.edit_message_text("📅 Por favor, digite a data no formato `DD/MM`.")
        return DEL_AWAITING_DATE
    return ConversationHandler.END


def get_records_with_row_numbers(sheet, target_date) -> list[dict]:
    """Fetches records for a date and includes their row number."""
    all_values = sheet.get_all_values()
    header = all_values[0]
    records_with_rows = []
    for i, row in enumerate(all_values[1:], start=2):  # Start from row 2
        try:
            record_date_str = row[header.index("Date")]
            record_date = datetime.strptime(record_date_str, "%d/%m/%Y").date()
            if record_date == target_date:
                record = dict(zip(header, row, strict=False))
                record["row_number"] = i
                record["Price"] = float(str(record.get("Price", "0")).replace(",", "."))
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

    context.user_data["records_for_deletion"] = records_to_delete
    context.user_data["delete_date"] = target_date

    keyboard = []
    message = f"Selecione o atendimento para deletar em *{target_date.strftime('%d/%m/%Y')}*:\n\n"

    # Create a reverse mapping from slug to proper case
    slug_to_proper_case = {slug: desc for slug, desc in PROCEDURE_DESCRIPTIONS.items()}
    # Create a mapping from the sheet's format (uppercase, no space) to slug
    sheet_format_to_slug = {
        slugify(desc).upper(): slug for slug, desc in PROCEDURE_DESCRIPTIONS.items()
    }

    for record in records_to_delete:
        patient = record.get("Patient", "N/A").title()
        procs_str = record.get("Procedures", "N/A")

        # Map uppercase procedures from sheet to proper case for display
        procs_list_from_sheet = [p.strip() for p in procs_str.split(",")]

        proper_procs_list = []
        for proc_from_sheet in procs_list_from_sheet:
            # Normalize the string from the sheet in the same way slugs are created, but keep it uppercase
            sheet_slug = slugify(proc_from_sheet).upper()
            # Find the original slug
            original_slug = sheet_format_to_slug.get(sheet_slug)
            # Get the proper description
            proper_name = slug_to_proper_case.get(original_slug, proc_from_sheet)
            proper_procs_list.append(proper_name)

        procs_display = ", ".join(proper_procs_list)

        price = record.get("Price", 0.0)
        button_text = f"{patient} | {procs_display} | R$ {price:.2f}".replace(".", ",")
        callback_data = f"del_record_{record['row_number']}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

    keyboard.append([InlineKeyboardButton("🔙 Cancelar", callback_data="cancel_delete")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(
            message, reply_markup=reply_markup, parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="Markdown")

    return DEL_SELECTING_RECORD


async def deletar_receive_date(update: Update, context: CallbackContext) -> int:
    """Receives a custom date and lists records for deletion."""
    date_str = update.message.text
    try:
        current_year = get_brazil_datetime_now().year
        target_date = datetime.strptime(f"{date_str}/{current_year}", "%d/%m/%Y").date()
        return await list_records_for_deletion(update, context, target_date)
    except ValueError:
        await update.message.reply_text(
            "⚠️ Data inválida. Use o formato DD/MM. Tente novamente ou use /cancelar."
        )
        return DEL_AWAITING_DATE


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
        await query.edit_message_text("⚠️ Erro: Atendimento não encontrado. Tente novamente.")
        return await list_records_for_deletion(update, context, context.user_data["delete_date"])

    upper_to_proper_case = {v.upper(): v for v in PROCEDURE_DESCRIPTIONS.values()}
    patient = record_to_delete.get("Patient", "N/A").title()
    procs_str = record_to_delete.get("Procedures", "N/A")
    procs_list_upper = procs_str.split(", ")
    proper_procs_list = [upper_to_proper_case.get(p, p) for p in procs_list_upper]
    procs_display = ", ".join(proper_procs_list)
    price = record_to_delete.get("Price", 0.0)

    message = (
        f"Você tem certeza que deseja deletar o seguinte atendimento?\n\n"
        f"👤 *Paciente:* {patient}\n"
        f"📋 *Procedimentos:* {procs_display}\n"
        f"💰 *Valor:* R$ {price:.2f}".replace(".", ",")
    )

    keyboard = [
        [
            InlineKeyboardButton("Sim, deletar", callback_data="del_confirm_yes"),
            InlineKeyboardButton("Não, voltar", callback_data="del_confirm_no"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode="Markdown")

    return DEL_CONFIRMING


async def deletar_receive_selection(update: Update, context: CallbackContext) -> int:
    """Receives the user's confirmation and deletes the record."""
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == "del_confirm_no":
        target_date = context.user_data.get("delete_date")
        if target_date:
            await query.edit_message_text("Ok, voltando para a lista de atendimentos.")
            return await list_records_for_deletion(update, context, target_date)
        await query.edit_message_text("Operação cancelada.")
        await menu_command(update, context)
        return ConversationHandler.END

    # Proceed with deletion if 'yes'
    try:
        row_number_to_delete = context.user_data.get("row_to_delete")
        if not row_number_to_delete:
            raise ValueError("Row number to delete not found in context.")

        sheet = get_sheet()
        if not sheet:
            await query.edit_message_text(
                "⚠️ Erro de configuração: Não foi possível conectar à planilha."
            )
            return ConversationHandler.END

        sheet.delete_rows(row_number_to_delete)
        await query.edit_message_text("✅ Atendimento deletado com sucesso!")

        # Send the standard final message
        await send_final_message(update)

        context.user_data.clear()
        return ConversationHandler.END

    except (ValueError, IndexError) as e:
        logger.error(f"Error during deletion confirmation: {e}")
        await query.edit_message_text(
            "⚠️ Ocorreu um erro ao processar a sua seleção. Tente novamente."
        )
        return ConversationHandler.END
