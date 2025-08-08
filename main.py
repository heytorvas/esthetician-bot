import os
import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackContext
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from keep_alive import keep_alive

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

logger = logging.getLogger(__name__)

# Constants
PROCEDURE_DESCRIPTIONS = {
    "RF": "Radiofrequência",
    "LP": "Limpeza de Pele",
    "BS": "Body Shape",
    "HS": "Hiper Slim",
    "MSG": "Massagem",
    "SPA": "SPA",
    "PO": "Pós Operatório",
    "US": "Ultrassom",
    "Detox": "Detox",
    "3MH": "3MH",
    "Compex": "Compex"
}

# --- Google Sheets Setup ---
def get_sheet():
    """Connects to Google Sheets and returns the worksheet object."""
    try:
        scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name('creds.json', scope)
        client = gspread.authorize(creds)
        sheet_id = os.environ.get("SHEET_ID")
        if not sheet_id:
            raise ValueError("Environment variable SHEET_ID not set.")
        sheet = client.open_by_key(sheet_id).sheet1
        return sheet
    except FileNotFoundError:
        logger.error("creds.json not found. Please make sure the service account file is in the same directory.")
        return None
    except Exception as e:
        logger.error(f"Error connecting to Google Sheets: {e}")
        return None

# --- Command Handlers ---

async def procedimentos_command(update: Update, context: CallbackContext) -> None:
    """Lists all available procedures and their descriptions."""
    message = "📋 Procedimentos Disponíveis:\n\n"
    for code, description in PROCEDURE_DESCRIPTIONS.items():
        message += f"• {code}: {description}\n"
    await update.message.reply_text(message)


async def listar_command(update: Update, context: CallbackContext) -> None:
    """Lists all records for a specific day."""
    try:
        args = context.args
        if len(args) != 1:
            await update.message.reply_text("⚠️ Uso incorreto. Formato: /listar DD/MM/YYYY")
            return

        date_str = args[0]
        try:
            target_date = datetime.strptime(date_str, "%d/%m/%Y").date()
        except ValueError:
            await update.message.reply_text("⚠️ Data inválida. Use o formato DD/MM/YYYY.")
            return

        sheet = get_sheet()
        if not sheet:
            await update.message.reply_text("⚠️ Erro de configuração: Não foi possível conectar à planilha.")
            return

        records = sheet.get_all_records()

        day_records = []
        for record in records:
            try:
                if not record.get('Date'):
                    continue
                record_date = datetime.strptime(record['Date'], "%d/%m/%Y").date()
                if record_date == target_date:
                    day_records.append(record)
            except (ValueError, TypeError):
                logger.warning(f"Skipping row with invalid data: {record}")
                continue

        if not day_records:
            await update.message.reply_text(f"ℹ️ Nenhum registro encontrado para o dia {date_str}.")
            return

        message = f"📋 Registros de {date_str}:\n\n"
        for record in day_records:
            price = float(record['Price'])
            message += f"• {record['Time']} - {record['Patient']} - {record['Procedures']} - R$ {price:.2f}\n".replace('.', ',')

        await update.message.reply_text(message)

    except Exception as e:
        logger.error(f"Error in /listar: {e}")
        await update.message.reply_text(f"⚠️ Erro ao buscar registros: {e}")


async def registrar_command(update: Update, context: CallbackContext) -> None:
    """Saves a new procedure record."""
    try:
        # Parse arguments: /registrar <patient name...> <DD/MM/YYYY> <HH:MM> <proc1,proc2> <price>
        args = context.args
        if len(args) < 5:
            await update.message.reply_text(
                "⚠️ Uso incorreto. Formato: /registrar <Nome do Paciente> <DD/MM/YYYY> <HH:MM> <Proc1,Proc2> <Valor>"
            )
            return

        # Re-assemble arguments to support multi-word names
        price_str = args[-1]
        procedures_str = args[-2]
        time_str = args[-3]
        date_str = args[-4]
        patient = " ".join(args[:-4])

        if not patient:
             await update.message.reply_text("⚠️ Nome do paciente não pode estar em branco.")
             return

        # 1. Validate Date and Time
        try:
            datetime_obj = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
        except ValueError:
            await update.message.reply_text("⚠️ Data ou hora inválida. Use o formato DD/MM/YYYY e HH:MM.")
            return

        # 2. Validate Procedures
        procedures_list = [p.strip().upper() for p in procedures_str.split(',')]
        valid_procedures_found = [p for p in procedures_list if p in PROCEDURE_DESCRIPTIONS]
        if not valid_procedures_found:
            await update.message.reply_text(f"⚠️ Nenhum procedimento válido encontrado. Válidos: {', '.join(PROCEDURE_DESCRIPTIONS.keys())}")
            return

        # 3. Validate Price
        try:
            price = float(price_str.replace(',', '.'))
        except ValueError:
            await update.message.reply_text("⚠️ Valor inválido. Use um número (ex: 150.50 ou 150,50).")
            return

        # Append to Google Sheet
        sheet = get_sheet()
        if not sheet:
            await update.message.reply_text("⚠️ Erro de configuração: Não foi possível conectar à planilha.")
            return
            
        row = [
            datetime_obj.strftime("%d/%m/%Y"),
            datetime_obj.strftime("%H:%M"),
            patient,
            ', '.join(valid_procedures_found),
            price
        ]
        sheet.append_row(row)

        # Success message
        reply_message = (
            f"✅ Registro salvo!\n"
            f"Paciente: {patient}\n"
            f"Data/Hora: {datetime_obj.strftime('%d/%m/%Y %H:%M')}\n"
            f"Procedimentos: {', '.join(valid_procedures_found)}\n"
            f"Valor total: R$ {price:.2f}".replace('.', ',')
        )
        await update.message.reply_text(reply_message)

    except Exception as e:
        logger.error(f"Error in /registrar: {e}")
        await update.message.reply_text(f"⚠️ Erro ao salvar: {e}")


async def calcular_command(update: Update, context: CallbackContext) -> None:
    """Calculates the sum of prices over a given period."""
    try:
        args = context.args
        if not args:
            await update.message.reply_text("⚠️ Uso: /calcular <dia|semana|mês|período> [argumentos...]")
            return

        mode = args[0].lower()
        now = datetime.now()
        start_date, end_date = None, None
        period_str = ""

        if mode == 'dia':
            if len(args) != 2:
                await update.message.reply_text("⚠️ Uso: /calcular dia DD/MM/YYYY")
                return
            day_str = args[1]
            start_date = datetime.strptime(day_str, "%d/%m/%Y").date()
            end_date = start_date
            period_str = f"o dia {day_str}"

        elif mode == 'semana':
            target_date = now
            if len(args) > 1:
                target_date = datetime.strptime(args[1], "%d/%m/%Y")
            start_of_week = target_date - timedelta(days=target_date.weekday())
            end_of_week = start_of_week + timedelta(days=6)
            start_date, end_date = start_of_week.date(), end_of_week.date()
            period_str = f"a semana de {start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"

        elif mode == 'mês':
            month_str = now.strftime("%m/%Y")
            if len(args) > 1:
                month_str = args[1]
            target_month = datetime.strptime(month_str, "%m/%Y")
            start_date = target_month.date().replace(day=1)
            next_month = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
            end_date = next_month - timedelta(days=1)
            period_str = f"o mês {month_str}"

        elif mode == 'período':
            if len(args) != 3:
                await update.message.reply_text("⚠️ Uso: /calcular período DD/MM/YYYY DD/MM/YYYY")
                return
            start_date = datetime.strptime(args[1], "%d/%m/%Y").date()
            end_date = datetime.strptime(args[2], "%d/%m/%Y").date()
            period_str = f"o período de {args[1]} a {args[2]}"
        
        else:
            await update.message.reply_text("⚠️ Modo inválido. Use 'dia', 'semana', 'mês' ou 'período'.")
            return

        # Fetch and process data
        sheet = get_sheet()
        if not sheet:
            await update.message.reply_text("⚠️ Erro de configuração: Não foi possível conectar à planilha.")
            return
            
        records = sheet.get_all_records()
        total = 0.0
        count = 0

        for record in records:
            try:
                # gspread might read empty rows as empty strings
                if not record.get('Date'):
                    continue
                record_date = datetime.strptime(record['Date'], "%d/%m/%Y").date()
                if start_date <= record_date <= end_date:
                    price = float(record['Price'])
                    total += price
                    count += 1
            except (ValueError, TypeError):
                # Ignore rows with invalid date or price format
                logger.warning(f"Skipping row with invalid data: {record}")
                continue
        
        if count == 0:
            await update.message.reply_text(f"ℹ️ Nenhum registro encontrado para {period_str}.")
        else:
            reply_message = (
                f"📊 Total de {count} registros de {period_str}: R$ {total:.2f}"
            ).replace('.', ',')
            await update.message.reply_text(reply_message)

    except ValueError:
        await update.message.reply_text("⚠️ Data em formato inválido. Use DD/MM/YYYY ou MM/YYYY.")
    except Exception as e:
        logger.error(f"Error in /sum: {e}")
        await update.message.reply_text(f"⚠️ Erro ao calcular a soma: {e}")


def main() -> None:
    """Start the bot."""
    # Start the web server to keep the bot alive on Replit
    keep_alive()

    # Get the bot token from environment variables
    bot_token = os.environ.get("BOT_TOKEN")
    if not bot_token:
        logger.error("Environment variable BOT_TOKEN not set.")
        return

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(bot_token).build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("procedimentos", procedimentos_command))
    application.add_handler(CommandHandler("listar", listar_command))
    application.add_handler(CommandHandler("registrar", registrar_command))
    application.add_handler(CommandHandler("calcular", calcular_command))

    # Run the bot until the user presses Ctrl-C
    application.run_polling()


if __name__ == '__main__':
    main()
