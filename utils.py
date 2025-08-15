import logging
import unicodedata
from datetime import datetime, timedelta

from telegram import Update

from constants import PROCEDURE_DESCRIPTIONS

logger = logging.getLogger(__name__)


# --- Utility Functions ---
def slugify(text):
    """Converts a string into a 'slug' for consistent matching."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = text.replace(" ", "").replace("-", "")
    return text


def get_info_from_record(record: dict) -> tuple[str, str, str]:
    patient = record.get("Patient", "N/A").title()
    procs_str = record.get("Procedures", "N/A")
    procedure_names = [
        PROCEDURE_DESCRIPTIONS.get(slug)
        for slug in [p.strip().lower() for p in procs_str.split(",")]
    ]
    procs_display = ", ".join(procedure_names)
    price = f"{record.get('Price', 0.0):.2f}".replace(".", ",")
    return patient, procs_display, price


def get_records_in_range(sheet, start_date, end_date) -> list[dict]:
    """Fetches all records from the sheet and filters them by a date range."""
    all_records = sheet.get_all_records()
    filtered_records = []
    for record in all_records:
        try:
            record_date = datetime.strptime(record.get("Date", ""), "%d/%m/%Y").date()
            if start_date <= record_date <= end_date:
                record["Price"] = float(str(record.get("Price", "0")).replace(",", "."))
                filtered_records.append(record)
        except (ValueError, TypeError):
            logger.warning(f"Skipping row with invalid data during filtering: {record}")
    return filtered_records


def get_brazil_datetime_now():
    return datetime.now() - timedelta(hours=3)


def get_date_range_for_sum(
    mode: str, date_input: str | None
) -> tuple[datetime.date, datetime.date, str] | None:
    """Calculates the start date, end date, and a descriptive string for a given mode."""
    now = get_brazil_datetime_now()
    try:
        if mode == "dia":
            day_str = date_input or now.strftime("%d/%m/%Y")
            start_date = end_date = datetime.strptime(day_str, "%d/%m/%Y").date()
            period_str = f"o dia {day_str}"
        elif mode == "semana":
            target_date = datetime.strptime(date_input, "%d/%m/%Y") if date_input else now
            start_of_week = target_date - timedelta(days=target_date.weekday())
            end_of_week = start_of_week + timedelta(days=6)
            start_date, end_date = start_of_week.date(), end_of_week.date()
            period_str = (
                f"a semana de {start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
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
            start_date = datetime.strptime(parts[0], "%d/%m/%Y").date()
            end_date = datetime.strptime(parts[1], "%d/%m/%Y").date()
            period_str = f"o período de {parts[0]} a {parts[1]}"
        else:
            return None
        return start_date, end_date, period_str
    except (ValueError, AttributeError):
        return None


async def send_final_message(update: Update):
    """Sends a consistent final message and clears user data."""
    await update.effective_message.reply_text(
        "Operação concluída. Use /menu para ver o menu principal."
    )
