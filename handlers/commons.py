import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
)

from constants import MENU, PROCEDURE_DESCRIPTIONS
from g_sheets import get_sheet
from utils import get_records_in_range, send_final_message, slugify

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
        await update.callback_query.edit_message_text(
            "Menu Principal. O que você gostaria de fazer?", reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "👋 Olá! Sou seu assistente de agendamentos. O que você gostaria de fazer?",
            reply_markup=reply_markup,
        )
    return MENU


async def list_records_for_date(update: Update, context: CallbackContext, target_date) -> int:
    """Fetches and displays records for a specific date."""
    sheet = get_sheet()
    if not sheet:
        error_message = (
            "⚠️ Erro de configuração: Não foi possível conectar à planilha. Operação cancelada."
        )
        if update.callback_query:
            await update.callback_query.edit_message_text(error_message)
        else:
            await update.effective_message.reply_text(error_message)
        return ConversationHandler.END

    try:
        day_records = get_records_in_range(sheet, target_date, target_date)
        date_str = target_date.strftime("%d/%m/%Y")

        if not day_records:
            message = f"ℹ️ Nenhum atendimento encontrado para o dia {date_str}."
            if update.callback_query:
                await update.callback_query.edit_message_text(message)
            else:
                await update.effective_message.reply_text(message)
            await send_final_message(update)
            return ConversationHandler.END

        message = f"📋 *Atendimentos de {date_str}*\n\n"
        total_day_price = 0.0
        for record in day_records:
            procedure_slugs = [slugify(p.strip()) for p in record.get("Procedures", "").split(",")]
            procedure_names = [
                PROCEDURE_DESCRIPTIONS.get(slug, slug.upper()) for slug in procedure_slugs
            ]
            patient_name = record.get("Patient", "").title()
            price = record.get("Price", 0.0)
            total_day_price += price
            message += (
                f"👤 *Paciente:* {patient_name}\n"
                f"   *Procedimentos:* {', '.join(procedure_names)}\n"
                f"   *Valor:* R$ {price:.2f}\n\n".replace(".", ",")
            )

        message += f"💰 *Total do dia:* R$ {total_day_price:.2f}".replace(".", ",")

        if update.callback_query:
            await update.callback_query.edit_message_text(message, parse_mode="Markdown")
        else:
            await update.effective_message.reply_text(message, parse_mode="Markdown")

        await send_final_message(update)
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error listing records: {e}")
        await update.effective_message.reply_text(f"⚠️ Erro ao buscar registros: {e}")
        return ConversationHandler.END
