import logging
from datetime import date, datetime, timedelta

from telegram import Update

from constants import (
    DATE_FORMAT,
    MSG_ERROR_GENERIC,
    MSG_ERROR_SHEET_CONNECTION,
    MSG_FINAL,
    PROCEDURE_DESCRIPTIONS,
)

logger = logging.getLogger(__name__)


# --- Reusable Bot Responses & Actions ---
async def reply_or_edit(update: Update, text: str, reply_markup=None, parse_mode=None):
    """Edits the message if it's a callback query, otherwise sends a new message."""
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, reply_markup=reply_markup, parse_mode=parse_mode
        )
    else:
        await update.effective_message.reply_text(
            text, reply_markup=reply_markup, parse_mode=parse_mode
        )


async def handle_sheet_error(update: Update):
    """Sends a standardized sheet connection error message."""
    await reply_or_edit(update, MSG_ERROR_SHEET_CONNECTION)


async def handle_generic_error(update: Update, e: Exception, context):
    """Logs and sends a standardized generic error message, then ends the conversation."""
    logger.error(f"An unexpected error occurred: {e}", exc_info=True)
    await reply_or_edit(update, MSG_ERROR_GENERIC.format(e))
    context.user_data.clear()
    return -1  # ConversationHandler.END


async def send_final_message(update: Update):
    """Sends a consistent final message and clears user data."""
    await update.effective_message.reply_text(MSG_FINAL)


# --- Data & String Manipulation ---
def format_currency(value: float) -> str:
    """Formats a number into a Brazilian Real (BRL) currency string."""
    try:
        return f"R$ {float(value):.2f}".replace(".", ",")
    except (ValueError, TypeError):
        return "R$ 0,00"


def get_all_parsed_records(sheet, include_row_number=False) -> list[dict]:
    """Fetches all records from the sheet, parses essential fields, and optionally includes the row number."""
    all_values = sheet.get_all_values()
    if not all_values or len(all_values) < 2:
        return []

    header = all_values[0]
    parsed_records = []
    for i, row in enumerate(all_values[1:], start=2):  # Row numbers start from 2
        try:
            record = dict(zip(header, row, strict=False))
            record["parsed_date"] = datetime.strptime(record.get("Date", ""), DATE_FORMAT).date()
            record["parsed_price"] = float(str(record.get("Price", "0")).replace(",", "."))
            if include_row_number:
                record["row_number"] = i
            parsed_records.append(record)
        except (ValueError, TypeError, IndexError):
            logger.warning(f"Skipping row with invalid data during parsing: {row}")
            continue
    return parsed_records


def get_info_from_record(record: dict) -> tuple[str, str, str]:
    patient = record.get("Patient", "N/A").title()
    procs_str = record.get("Procedures", "N/A")

    procedure_slugs = [p.strip().lower() for p in procs_str.split(",")]
    procedure_names = [PROCEDURE_DESCRIPTIONS.get(slug) for slug in procedure_slugs]
    procs_display = ", ".join(procedure_names) if procedure_names else "N/A"

    price_val = record.get("parsed_price", record.get("Price", 0.0))
    price = format_currency(price_val)

    return patient, procs_display, price


def get_records_in_range(all_parsed_records: list[dict], start_date, end_date) -> list[dict]:
    """Filters a list of pre-parsed records by a date range."""
    filtered_records = []
    for record in all_parsed_records:
        if start_date <= record.get("parsed_date", datetime.min.date()) <= end_date:
            filtered_records.append(record)
    return filtered_records


def get_brazil_datetime_now():
    return datetime.now() - timedelta(hours=3)


def get_date_range_for_sum(mode: str, date_input: str | None) -> tuple[date, date, str] | None:
    """Calculates the start date, end date, and a descriptive string for a given mode."""
    now = get_brazil_datetime_now()
    try:
        if mode == "dia":
            day_str = date_input or now.strftime(DATE_FORMAT)
            start_date = end_date = datetime.strptime(day_str, DATE_FORMAT).date()
            period_str = f"o dia {day_str}"
        elif mode == "semana":
            target_date = datetime.strptime(date_input, DATE_FORMAT) if date_input else now
            start_of_week = target_date - timedelta(days=target_date.weekday())
            end_of_week = start_of_week + timedelta(days=6)
            start_date, end_date = start_of_week.date(), end_of_week.date()
            period_str = (
                f"a semana de {start_date.strftime(DATE_FORMAT)} a {end_date.strftime(DATE_FORMAT)}"
            )
        elif mode == "mes":
            month_str = date_input or now.strftime("%m/%Y")
            target_month = datetime.strptime(month_str, "%m/%Y")
            start_date = target_month.date().replace(day=1)
            next_month = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
            end_date = next_month - timedelta(days=1)
            period_str = f"o mês {month_str}"
        elif mode == "periodo":
            if not date_input or len(date_input.split()) != 2:
                return None
            parts = date_input.split()
            start_date = datetime.strptime(parts[0], DATE_FORMAT).date()
            end_date = datetime.strptime(parts[1], DATE_FORMAT).date()
            period_str = f"o período de {parts[0]} a {parts[1]}"
        else:
            return None
        return start_date, end_date, period_str
    except (ValueError, AttributeError):
        return None


def get_monthly_report_date_range(
    month_str: str | None = None,
) -> tuple[date, date] | None:
    """Calculates the monthly report date range (day 7 to day 6 of next month).
    If month_str (MM/YYYY) is provided, it's used as the reference.
    If None, the current month is used as the reference.
    """
    try:
        # Determine the reference date: either from the input string or the current time
        if month_str:
            ref_date = datetime.strptime(month_str, "%m/%Y")
        else:
            ref_date = get_brazil_datetime_now()

        # The start date is the 7th of the reference month.
        start_date = ref_date.replace(day=7).date()

        # To robustly find the next month, go to the 1st of the reference month,
        # add 32 days (which always lands in the next month), and then set the day to 6.
        first_day_of_ref_month = ref_date.replace(day=1)
        next_month_date = first_day_of_ref_month + timedelta(days=32)
        end_date = next_month_date.replace(day=6).date()

        return start_date, end_date
    except (ValueError, AttributeError):
        return None


def parse_ddmm_date(date_str: str) -> date | None:
    """Parses a DD/MM date string, assuming the current year."""
    try:
        current_year = get_brazil_datetime_now().year
        return datetime.strptime(f"{date_str.strip()}/{current_year}", DATE_FORMAT).date()
    except (ValueError, AttributeError):
        return None
