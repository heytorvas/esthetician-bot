import logging
import os

from telegram import Update
from telegram.ext import (
    Application,
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from constants import (
    ANALYTICS_MENU,
    CALC_AWAITING_DATE,
    CALC_AWAITING_RANGE,
    CALC_SELECTING_MODE,
    DEL_AWAITING_DATE,
    DEL_CONFIRMING,
    DEL_SELECTING_RECORD,
    MENU,
    PROCEDURE_DESCRIPTIONS,
    REG_AWAITING_DATE,
    REG_AWAITING_PATIENT,
    REG_CONFIRMING_MORE,
    REG_SELECTING_PRICE,
    REG_SELECTING_PROCEDURES,
)
from handlers.analytics import analytics_router, analytics_start
from handlers.calcular import (
    calcular_mode_selection,
    calcular_receive_date,
    calcular_receive_range,
    calcular_start,
)
from handlers.commons import menu_command
from handlers.deletar import (
    deletar_ask_confirmation,
    deletar_date_selection,
    deletar_receive_date,
    deletar_receive_selection,
    deletar_start,
)
from handlers.registrar import (
    registrar_confirm_more,
    registrar_date_selection,
    registrar_price_selection,
    registrar_procedure_selection,
    registrar_receive_custom_date,
    registrar_receive_patient,
    registrar_start,
)
from keep_alive import keep_alive
from utils import send_final_message

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


async def menu_router(update: Update, context: CallbackContext) -> int:
    """Routes main menu button presses to the correct conversation flow."""
    query = update.callback_query
    await query.answer()

    command = query.data

    if command == "menu_registrar":
        return await registrar_start(update, context)
    if command == "menu_calcular":
        return await calcular_start(update, context)
    if command == "menu_deletar":
        return await deletar_start(update, context)
    if command == "menu_analytics":
        return await analytics_start(update, context)
    if command == "menu_procedimentos":
        await procedimentos_command(update, context)
        await send_final_message(update)
        return ConversationHandler.END

    return ConversationHandler.END


async def procedimentos_command(update: Update, context: CallbackContext) -> None:
    """Lists all available procedures and their descriptions."""
    message = "📋 Procedimentos Disponíveis:\n\n"
    for slug, description in PROCEDURE_DESCRIPTIONS.items():
        message += f"• {description}\n"
    if update.callback_query:
        await update.callback_query.edit_message_text(message)
    else:
        await update.effective_message.reply_text(message)


async def cancel_command(update: Update, context: CallbackContext) -> int:
    """Cancels and ends the current conversation, returning to the main menu."""
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "Operação cancelada. Voltando ao menu principal."
        )
    else:
        await update.message.reply_text("Operação cancelada. Voltando ao menu principal.")

    # We need to call menu_command to display the menu again.
    await menu_command(update, context)
    return ConversationHandler.END


async def post_init(application: Application) -> None:
    """Post-initialization function to set bot commands."""
    await application.bot.delete_my_commands()
    await application.bot.set_my_commands(
        [
            ("menu", "Exibe o menu principal de ações."),
            ("cancelar", "Cancela a operação atual e volta ao menu."),
        ]
    )


def main() -> None:
    """Start the bot."""
    keep_alive()
    bot_token = os.environ.get("BOT_TOKEN")
    if not bot_token:
        logger.error("Environment variable BOT_TOKEN not set.")
        return

    application = Application.builder().token(bot_token).post_init(post_init).build()

    # Conversation handler for the main menu
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("menu", menu_command),
            CommandHandler("start", menu_command),
            CallbackQueryHandler(menu_router, pattern="^menu_"),
        ],
        states={
            MENU: [
                CallbackQueryHandler(menu_router, pattern="^menu_"),
            ],
            REG_AWAITING_DATE: [
                CallbackQueryHandler(registrar_date_selection, pattern="^reg_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, registrar_receive_custom_date),
            ],
            REG_AWAITING_PATIENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, registrar_receive_patient)
            ],
            REG_SELECTING_PROCEDURES: [
                CallbackQueryHandler(registrar_procedure_selection, pattern="^proc_")
            ],
            REG_SELECTING_PRICE: [
                CallbackQueryHandler(registrar_price_selection, pattern="^price_")
            ],
            REG_CONFIRMING_MORE: [
                CallbackQueryHandler(registrar_confirm_more, pattern="^reg_another_")
            ],
            CALC_SELECTING_MODE: [CallbackQueryHandler(calcular_mode_selection, pattern="^calc_")],
            CALC_AWAITING_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, calcular_receive_date)
            ],
            CALC_AWAITING_RANGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, calcular_receive_range)
            ],
            DEL_AWAITING_DATE: [
                CallbackQueryHandler(deletar_date_selection, pattern="^del_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, deletar_receive_date),
            ],
            DEL_SELECTING_RECORD: [
                CallbackQueryHandler(deletar_ask_confirmation, pattern="^del_record_")
            ],
            DEL_CONFIRMING: [
                CallbackQueryHandler(deletar_receive_selection, pattern="^del_confirm_")
            ],
            ANALYTICS_MENU: [
                CallbackQueryHandler(analytics_router, pattern="^analytics_"),
                CallbackQueryHandler(menu_command, pattern="^menu_back"),
            ],
        },
        fallbacks=[
            CommandHandler("cancelar", cancel_command),
            CallbackQueryHandler(cancel_command, pattern="^cancel$"),
            CallbackQueryHandler(cancel_command, pattern="^cancel_delete$"),
            CallbackQueryHandler(menu_command, pattern="^menu_back"),
        ],
        map_to_parent={ConversationHandler.END: MENU},
    )

    application.add_handler(conv_handler)
    application.run_polling()


if __name__ == "__main__":
    main()
