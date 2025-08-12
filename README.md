# Esthetician Bot

A Telegram bot designed to help estheticians manage patient procedure records by storing and retrieving data from a Google Sheet.

## Features

- **Interactive Menus**: A fully menu-driven interface for all operations.
- **Register Procedures**: Save new patient records through a guided conversation.
- **Calculate Totals**: Sum up earnings over a day, week, month, or custom date range using an interactive menu.
- **List Daily Records**: View all procedures performed on a specific day, chosen interactively.
- **Advanced Analytics**: Access a dedicated analytics menu to view detailed reports on:
  - **Monthly Revenue**: Track total income per month and a grand total.
  - **Monthly Appointments**: See the total number of appointments each month.
  - **Procedure Popularity**: View a ranked list of procedures by month.
  - **Patient Leaderboard**: See a monthly ranking of patients by appointment count.
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
    - Follow the official guide to create a service account and enable the Google Sheets and Google Drive APIs.
    - Download the credentials JSON file.
    - **Do not** save this file in the project. Instead, encode its contents into a Base64 string. You can use this command on Linux/macOS:
      ```bash
      cat your-credentials-file.json | base64 -w 0
      ```

4.  **Share the Google Sheet:**
    Share your Google Sheet with the `client_email` found inside your credentials JSON file, giving it "Editor" permissions.

5.  **Set Environment Variables:**
    The bot requires three environment variables. You can set them directly in your terminal or use a `.env` file.

    - `BOT_TOKEN`: Your Telegram bot token from @BotFather.
    - `SHEET_ID`: The ID of your Google Sheet.
    - `GCREDS_JSON_BASE64`: The Base64-encoded string of your Google credentials from step 3.

    To set them in the terminal (on Linux/macOS):
    ```bash
    export BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
    export SHEET_ID="YOUR_GOOGLE_SHEET_ID"
    export GCREDS_JSON_BASE64="YOUR_BASE64_ENCODED_STRING"
    ```

## Running the Bot

Once the setup is complete, and with the virtual environment activated (`source .venv/bin/activate`), run the bot with the following command:

```bash
python main.py
```

The bot will start polling for messages.

## Available Commands

The bot now operates through an interactive menu system.

- `/menu`
  - Displays the main menu with buttons for all major actions:
    - **🚀 Registrar Novo Atendimento**: Starts a guided conversation to add one or more records for a specific date. The bot will ask for the date and then for each record's details (`<Patient Name> <Procedures> <Price>`).
    - **📊 Calcular Faturamento**: Opens a menu to calculate total revenue for today, this week, this month, or a custom date range.
    - **📋 Listar Atendimentos de um Dia**: Asks for a date and then displays all records for that day, including a daily total.
    - **📈 Ver Relatórios**: Acesso a um menu de relatórios com as seguintes opções:
      - **Faturamento Mensal**: Mostra o faturamento total por mês e um total geral.
      - **Atendimentos Mensais**: Exibe o número total de atendimentos de cada mês.
      - **Procedimentos Mais Realizados**: Lista os procedimentos em ordem decrescente de quantidade realizada.
      - **Ranking de Pacientes**: Mostra os pacientes que mais realizaram procedimentos em um mês.
    - **ℹ️ Ver Procedimentos**: Shows a list of all valid procedures.

- `/cancelar`
  - Cancels any ongoing operation (like registering or listing records) and returns you to the main menu.
