import base64
import json
import logging
import os

import gspread
from oauth2client.service_account import ServiceAccountCredentials

logger = logging.getLogger(__name__)


# --- Google Sheets Setup ---
def get_sheet():
    """Connects to Google Sheets and returns the worksheet object."""
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_base64 = os.environ.get("GCREDS_JSON_BASE64")
        if not creds_base64:
            logger.error("GCREDS_JSON_BASE64 environment variable not set.")
            raise ValueError("Missing Google Credentials in environment.")
        creds_json = base64.b64decode(creds_base64).decode("utf-8")
        creds_dict = json.loads(creds_json)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet_id = os.environ.get("SHEET_ID")
        if not sheet_id:
            raise ValueError("Environment variable SHEET_ID not set.")
        sheet = client.open_by_key(sheet_id).sheet1
        return sheet
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.error(f"Credential configuration error: {e}")
        return None
    except Exception as e:
        logger.error(f"Error connecting to Google Sheets: {e}")
        return None
