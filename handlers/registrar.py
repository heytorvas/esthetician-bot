import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
)

from constants import (
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
from utils import get_brazil_datetime_now

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
    message = "📅 Para qual data você deseja registrar o novo atendimento?"
    await update.callback_query.edit_message_text(text=message, reply_markup=reply_markup)
    return REG_AWAITING_DATE


async def registrar_date_selection(update: Update, context: CallbackContext) -> int:
    """Handles the user's date choice and asks for the patient's name."""
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == "reg_today":
        context.user_data["date"] = get_brazil_datetime_now().date()
        await query.edit_message_text("👤 Por favor, digite o nome do(a) paciente.")
        return REG_AWAITING_PATIENT
    if choice == "reg_other_date":
        await query.edit_message_text("📅 Por favor, digite a data no formato `DD/MM`.")
        return REG_AWAITING_DATE  # Wait for user to type date
    return ConversationHandler.END


async def registrar_receive_custom_date(update: Update, context: CallbackContext) -> int:
    """Receives a custom date from the user and asks for the patient's name."""
    date_str = update.message.text
    try:
        current_year = get_brazil_datetime_now().year
        target_date = datetime.strptime(f"{date_str}/{current_year}", "%d/%m/%Y").date()
        context.user_data["date"] = target_date
        await update.message.reply_text("👤 Por favor, digite o nome do(a) paciente.")
        return REG_AWAITING_PATIENT
    except ValueError:
        await update.message.reply_text(
            "⚠️ Data inválida. Use o formato DD/MM. Tente novamente ou use /cancelar."
        )
        return REG_AWAITING_DATE


async def registrar_receive_patient(update: Update, context: CallbackContext) -> int:
    """Receives the patient's name and shows the procedure selection."""
    patient_name = update.message.text.strip()
    if not patient_name:
        await update.message.reply_text(
            "⚠️ Nome do paciente não pode ser vazio. Por favor, tente novamente."
        )
        return REG_AWAITING_PATIENT

    context.user_data["patient"] = patient_name
    context.user_data["selected_procedures"] = set()

    reply_markup = registrar_build_procedures_keyboard(set())
    await update.message.reply_text(
        "📋 Selecione um ou mais procedimentos. Clique em 'Continuar' quando terminar.",
        reply_markup=reply_markup,
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

    selected_procedures = context.user_data.get("selected_procedures", set())

    if callback_data == "proc_done":
        if not selected_procedures:
            await context.bot.answer_callback_query(
                query.id, "⚠️ Você deve selecionar pelo menos um procedimento.", show_alert=True
            )
            return REG_SELECTING_PROCEDURES

        # Build price keyboard
        price_keyboard = [
            [
                InlineKeyboardButton(
                    f"R$ {price:.2f}".replace(".", ","), callback_data=f"price_{price}"
                )
                for price in VALID_PRICES
            ],
            [InlineKeyboardButton("🔙 Voltar", callback_data="price_back")],
        ]
        await query.edit_message_text(
            "💰 Selecione o valor do atendimento:",
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
    await query.edit_message_text(
        "📋 Selecione um ou mais procedimentos. Clique em 'Continuar' quando terminar.",
        reply_markup=reply_markup,
    )
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
        await query.edit_message_text(
            "📋 Selecione um ou mais procedimentos. Clique em 'Continuar' quando terminar.",
            reply_markup=reply_markup,
        )
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
        await query.edit_message_text(
            "⚠️ Erro de configuração: Não foi possível conectar à planilha."
        )
        return ConversationHandler.END

    try:
        # First, edit the original message to give feedback.
        await query.edit_message_text("Salvando registro...")

        user_data = context.user_data
        date_obj = user_data["date"]
        patient = user_data["patient"].upper()
        procedure_slugs = sorted(list(user_data["selected_procedures"]))
        procedure_names = [PROCEDURE_DESCRIPTIONS[slug] for slug in procedure_slugs]
        price = user_data["price"]

        row = [date_obj.strftime("%d/%m/%Y"), patient, ", ".join(procedure_names).upper(), price]
        sheet.append_row(row)

        summary_text = (
            f"✅ *Atendimento salvo com sucesso!*\n\n"
            f"📅 *Data:* {date_obj.strftime('%d/%m/%Y')}\n"
            f"👤 *Paciente:* {patient.title()}\n"
            f"📋 *Procedimentos:* {', '.join(procedure_names)}\n"
            f"💰 *Valor:* R$ {price:.2f}".replace(".", ",")
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
            text="Deseja registrar outro atendimento?",
            reply_markup=InlineKeyboardMarkup(keyboard),
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
        date = context.user_data.get("date")
        context.user_data.clear()
        context.user_data["date"] = date
        await query.edit_message_text("👤 Por favor, digite o nome do(a) próximo(a) paciente.")
        return REG_AWAITING_PATIENT
    # 'reg_another_no'
    date_obj = context.user_data.get("date")
    await query.edit_message_text("Ok, operação finalizada.")
    context.user_data.clear()
    # Show summary for the day
    await list_records_for_date(update, context, date_obj)
    return ConversationHandler.END


def registrar_build_procedures_keyboard(selected_slugs: set) -> InlineKeyboardMarkup:
    """Builds the keyboard for procedure selection with checkmarks."""
    keyboard = []
    for slug, description in PROCEDURE_DESCRIPTIONS.items():
        text = f"✅ {description}" if slug in selected_slugs else f"⬜️ {description}"
        keyboard.append([InlineKeyboardButton(text, callback_data=f"proc_{slug}")])
    keyboard.append([InlineKeyboardButton("➡️ Continuar", callback_data="proc_done")])
    keyboard.append([InlineKeyboardButton("🔙 Cancelar", callback_data="cancel")])
    return InlineKeyboardMarkup(keyboard)
