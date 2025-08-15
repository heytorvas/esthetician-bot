import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
)

from constants import (
    DATE_FORMAT,
    MSG_ERROR_INVALID_DATE_FORMAT_DDMM,
    MSG_OPERATION_CANCELLED,
    MSG_PROMPT_DATE_DDMM,
    MSG_PROMPT_PATIENT_NAME,
    MSG_REG_ASK_ANOTHER,
    MSG_REG_ASK_DATE,
    MSG_REG_FINISHED,
    MSG_REG_NO_PROCEDURE_SELECTED,
    MSG_REG_PATIENT_NAME_EMPTY,
    MSG_REG_SAVING,
    MSG_REG_SELECT_PRICE,
    MSG_REG_SELECT_PROCEDURES,
    MSG_REG_SUCCESS,
    PROCEDURE_DESCRIPTIONS,
    REG_AWAITING_DATE,
    REG_AWAITING_PATIENT,
    REG_CONFIRMING_MORE,
    REG_SELECTING_PRICE,
    REG_SELECTING_PROCEDURES,
    VALID_PRICES,
)
from g_sheets import get_sheet
from handlers.commons import list_records_for_date, menu_command
from utils import (
    format_currency,
    get_brazil_datetime_now,
    handle_generic_error,
    handle_sheet_error,
    parse_ddmm_date,
    reply_or_edit,
)

logger = logging.getLogger(__name__)


# --- REGISTRAR Conversation ---
async def registrar_start(update: Update, context: CallbackContext) -> int:
    """Starts the conversation to register a new record."""
    context.user_data.clear()  # Clear data from any previous conversation
    keyboard = [
        [InlineKeyboardButton("Hoje", callback_data="reg_today")],
        [InlineKeyboardButton("Outra data (DD/MM)", callback_data="reg_other_date")],
        [InlineKeyboardButton("🔙 Voltar ao Menu", callback_data="menu_back")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await reply_or_edit(update, text=MSG_REG_ASK_DATE, reply_markup=reply_markup)
    return REG_AWAITING_DATE


async def registrar_date_selection(update: Update, context: CallbackContext) -> int:
    """Handles the user's date choice and asks for the patient's name."""
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == "reg_today":
        context.user_data["date"] = get_brazil_datetime_now().date()
        await reply_or_edit(update, MSG_PROMPT_PATIENT_NAME)
        return REG_AWAITING_PATIENT
    if choice == "reg_other_date":
        await reply_or_edit(update, MSG_PROMPT_DATE_DDMM)
        return REG_AWAITING_DATE  # Wait for user to type date
    return ConversationHandler.END


async def registrar_receive_custom_date(update: Update, context: CallbackContext) -> int:
    """Receives a custom date from the user and asks for the patient's name."""
    date_str = update.message.text
    target_date = parse_ddmm_date(date_str)
    if not target_date:
        await reply_or_edit(update, MSG_ERROR_INVALID_DATE_FORMAT_DDMM)
        return REG_AWAITING_DATE

    context.user_data["date"] = target_date
    await reply_or_edit(update, MSG_PROMPT_PATIENT_NAME)
    return REG_AWAITING_PATIENT


async def registrar_receive_patient(update: Update, context: CallbackContext) -> int:
    """Receives the patient's name and shows the procedure selection."""
    patient_name = update.message.text.strip()
    if not patient_name:
        await reply_or_edit(update, MSG_REG_PATIENT_NAME_EMPTY)
        return REG_AWAITING_PATIENT

    context.user_data["patient"] = patient_name
    context.user_data["selected_procedures"] = set()

    reply_markup = registrar_build_procedures_keyboard(set())
    await reply_or_edit(update, MSG_REG_SELECT_PROCEDURES, reply_markup=reply_markup)
    return REG_SELECTING_PROCEDURES


async def registrar_procedure_selection(update: Update, context: CallbackContext) -> int:
    """Handles the interactive procedure selection."""
    query = update.callback_query
    await query.answer()
    callback_data = query.data

    if callback_data == "cancel":
        await reply_or_edit(update, MSG_OPERATION_CANCELLED)
        return await menu_command(update, context)

    selected_procedures = context.user_data.get("selected_procedures", set())

    if callback_data == "proc_done":
        if not selected_procedures:
            await context.bot.answer_callback_query(
                query.id, MSG_REG_NO_PROCEDURE_SELECTED, show_alert=True
            )
            return REG_SELECTING_PROCEDURES

        # Build price keyboard
        price_keyboard = [
            [
                InlineKeyboardButton(format_currency(price), callback_data=f"price_{price}")
                for price in VALID_PRICES
            ],
            [InlineKeyboardButton("🔙 Voltar", callback_data="price_back")],
        ]
        await reply_or_edit(
            update,
            MSG_REG_SELECT_PRICE,
            reply_markup=InlineKeyboardMarkup(price_keyboard),
        )
        return REG_SELECTING_PRICE

    # Toggle procedure selection
    proc_slug = callback_data.replace("proc_", "")
    if proc_slug in selected_procedures:
        selected_procedures.remove(proc_slug)
    else:
        selected_procedures.add(proc_slug)

    context.user_data["selected_procedures"] = selected_procedures
    reply_markup = registrar_build_procedures_keyboard(selected_procedures)
    await reply_or_edit(update, MSG_REG_SELECT_PROCEDURES, reply_markup=reply_markup)
    return REG_SELECTING_PROCEDURES


async def registrar_price_selection(update: Update, context: CallbackContext) -> int:
    """Handles the price selection and saves the record."""
    query = update.callback_query
    await query.answer()
    callback_data = query.data

    if callback_data == "price_back":
        reply_markup = registrar_build_procedures_keyboard(
            context.user_data.get("selected_procedures", set())
        )
        await reply_or_edit(update, MSG_REG_SELECT_PROCEDURES, reply_markup=reply_markup)
        return REG_SELECTING_PROCEDURES

    price = int(callback_data.replace("price_", ""))
    context.user_data["price"] = price

    # All data collected, now save it
    return await save_record_and_summarize(update, context)


async def save_record_and_summarize(update: Update, context: CallbackContext) -> int:
    """Saves the collected data to the spreadsheet and shows a summary."""
    query = update.callback_query
    sheet = get_sheet()
    if not sheet:
        await handle_sheet_error(update)
        return ConversationHandler.END

    try:
        # First, edit the original message to give feedback.
        await reply_or_edit(update, MSG_REG_SAVING)

        user_data = context.user_data
        date_obj = user_data["date"]
        patient = user_data["patient"].upper()
        procedure_slugs = sorted(list(user_data["selected_procedures"]))
        procedure_names = [PROCEDURE_DESCRIPTIONS[slug] for slug in procedure_slugs]
        price = user_data["price"]

        row = [date_obj.strftime(DATE_FORMAT), patient, ", ".join(procedure_slugs).upper(), price]
        sheet.append_row(row)

        summary_text = MSG_REG_SUCCESS.format(
            date=date_obj.strftime(DATE_FORMAT),
            patient=patient.title(),
            procedures=", ".join(procedure_names),
            price=format_currency(price),
        )
        # Send the summary as a new message
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=summary_text, parse_mode="Markdown"
        )

        # Ask to add another in a new message
        keyboard = [
            [InlineKeyboardButton("Sim, para a mesma data", callback_data="reg_another_yes")],
            [InlineKeyboardButton("Não, finalizar", callback_data="reg_another_no")],
        ]
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=MSG_REG_ASK_ANOTHER,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return REG_CONFIRMING_MORE

    except Exception as e:
        return await handle_generic_error(update, e, context)


async def registrar_confirm_more(update: Update, context: CallbackContext) -> int:
    """Handles user's choice to add another record or finish."""
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == "reg_another_yes":
        # Keep the date, clear other data
        date = context.user_data.get("date")
        context.user_data.clear()
        context.user_data["date"] = date
        await reply_or_edit(update, MSG_PROMPT_PATIENT_NAME)
        return REG_AWAITING_PATIENT
    # 'reg_another_no'
    date_obj = context.user_data.get("date")
    await reply_or_edit(update, MSG_REG_FINISHED)
    context.user_data.clear()
    # Show summary for the day
    await list_records_for_date(update, context, date_obj)
    return ConversationHandler.END


def registrar_build_procedures_keyboard(selected_slugs: set) -> InlineKeyboardMarkup:
    """Builds the keyboard for procedure selection with checkmarks."""
    keyboard = []
    for slug in sorted(PROCEDURE_DESCRIPTIONS):
        description = PROCEDURE_DESCRIPTIONS[slug]
        text = f"✅ {description}" if slug in selected_slugs else f"⬜️ {description}"
        keyboard.append([InlineKeyboardButton(text, callback_data=f"proc_{slug}")])
    keyboard.append([InlineKeyboardButton("➡️ Continuar", callback_data="proc_done")])
    keyboard.append([InlineKeyboardButton("🔙 Cancelar", callback_data="cancel")])
    return InlineKeyboardMarkup(keyboard)
