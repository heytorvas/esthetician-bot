# Esthetician Bot

A Telegram bot designed to help estheticians manage patient procedure records by storing and retrieving data from a Google Sheet.

## Features

- **Register Procedures**: Save new patient records, including procedures performed and price.
- **Calculate Totals**: Sum up earnings over a day, week, month, or custom date range.
- **List Daily Records**: View all procedures performed on a specific day.
- **List Available Procedures**: Get a list of all valid procedure codes and their descriptions.

## Setup

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```

2.  **Create a virtual environment and install dependencies with `uv`:**
    ```bash
    # Install uv if you don't have it: https://github.com/astral-sh/uv
    # Create and activate a virtual environment
    uv venv
    source .venv/bin/activate
    
    # Install dependencies
    uv pip install -r requirements.txt
    ```

3.  **Create Google Service Account Credentials:**
    Follow the official guide to create a service account, enable the Google Sheets and Google Drive APIs, and download the credentials JSON file. Rename this file to `creds.json` and place it in the project's root directory.

4.  **Share the Google Sheet:**
    Share your Google Sheet with the `client_email` found inside your `creds.json` file, giving it "Editor" permissions.

5.  **Set Environment Variables:**
    The bot requires two environment variables. You can set them directly in your terminal or use a `.env` file.

    - `BOT_TOKEN`: Your Telegram bot token from @BotFather.
    - `SHEET_ID`: The ID of your Google Sheet.

    To set them in the terminal (on Linux/macOS):
    ```bash
    export BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
    export SHEET_ID="YOUR_GOOGLE_SHEET_ID"
    ```

## Running the Bot

Once the setup is complete, and with the virtual environment activated (`source .venv/bin/activate`), run the bot with the following command:

```bash
python main.py
```

The bot will start polling for messages.

## Available Commands

- `/procedimentos`
  - Lists all available procedures and their codes.

- `/listar <DD/MM/YYYY>`
  - Lists all records for a specific day.
  - Example: `/listar 08/08/2025`

- `/registrar <Nome do Paciente> <DD/MM/YYYY> <HH:MM> <Procedimentos> <Valor>`
  - Saves a new procedure record. The patient's name can have multiple words.
  - Example: `/registrar Maria da Silva 08/08/2025 15:00 RF,LP 250.50`

- `/calcular <modo> [argumentos...]`
  - Calculates the total value of records for a given period.
  - **Modes:**
    - `dia <DD/MM/YYYY>`: Total for a specific day.
    - `semana [DD/MM/YYYY]`: Total for a week. Defaults to the current week.
    - `mês [MM/YYYY]`: Total for a month. Defaults to the current month.
    - `período <DD/MM/YYYY> <DD/MM/YYYY>`: Total for a custom date range.
