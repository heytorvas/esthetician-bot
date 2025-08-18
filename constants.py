# --- State Definitions for ConversationHandler ---
(
    MENU,
    # Registrar States
    REG_AWAITING_DATE,
    REG_AWAITING_PATIENT,
    REG_SELECTING_PROCEDURES,
    REG_SELECTING_PRICE,
    REG_CONFIRMING_MORE,
    # Listar States
    LISTAR_AWAITING_DATE,
    # Calcular States
    CALC_SELECTING_MODE,
    CALC_AWAITING_DATE,
    CALC_AWAITING_RANGE,
    CALC_MONTHLY_REPORT_CHOICE,
    CALC_GET_CUSTOM_MONTH,
    # Analytics States
    ANALYTICS_MENU,
    # Deletar States
    DEL_AWAITING_DATE,
    DEL_SELECTING_RECORD,
    DEL_CONFIRMING,
) = range(16)

PROCEDURE_DESCRIPTIONS = {
    "radiofrequencia": "Radiofrequência",
    "limpezadepele": "Limpeza de Pele",
    "bodyshape": "Body Shape",
    "hiperslim": "Hiper Slim",
    "massagem": "Massagem",
    "spa": "SPA",
    "posoperatorio": "Pós Operatório",
    "ultrassom": "Ultrassom",
    "detox": "Detox",
    "3mh": "3MH",
    "compex": "Compex",
    "drenagem": "Drenagem",
    "hybrius": "Hybrius",
    "carboxiterapia": "Carboxiterapia",
}
VALID_PRICES = [5, 10, 15, 20]


# --- Formatting ---
DATE_FORMAT = "%d/%m/%Y"


# --- User-Facing Messages ---
MSG_MAIN_MENU = "Menu Principal. O que você gostaria de fazer?"
MSG_GREETING = "👋 Olá! Sou seu assistente de agendamentos. O que você gostaria de fazer?"
MSG_OPERATION_CANCELLED = "Operação cancelada."
MSG_FINAL = "Operação concluída. Use /menu para ver o menu principal."

# Errors
MSG_ERROR_SHEET_CONNECTION = "⚠️ Erro de configuração: Não foi possível conectar à planilha."
MSG_ERROR_INVALID_DATE_FORMAT_DDMM = (
    "⚠️ Data inválida. Use o formato DD/MM. Tente novamente ou use /cancelar."
)
MSG_ERROR_GENERIC = "⚠️ Ocorreu um erro: {}"
MSG_ERROR_NO_RECORDS_FOUND_FOR_DATE = "ℹ️ Nenhum atendimento encontrado para o dia {}."
MSG_ERROR_NO_DATA_FOR_ANALYTICS = "ℹ️ Não há dados suficientes para gerar análises."
MSG_ERROR_DELETION = "⚠️ Ocorreu um erro ao processar a sua seleção. Tente novamente."
MSG_ERROR_RECORD_NOT_FOUND = "⚠️ Erro: Atendimento não encontrado. Tente novamente."

# Prompts
MSG_PROMPT_DATE_DDMM = "📅 Por favor, digite a data no formato `DD/MM`."
MSG_PROMPT_PATIENT_NAME = "👤 Por favor, digite o nome do(a) paciente."

# Registrar Command
MSG_REG_ASK_DATE = "📅 Para qual data você deseja registrar o novo atendimento?"
MSG_REG_PATIENT_NAME_EMPTY = "⚠️ Nome do paciente não pode ser vazio. Por favor, tente novamente."
MSG_REG_NO_PROCEDURE_SELECTED = "⚠️ Você deve selecionar pelo menos um procedimento."
MSG_REG_SELECT_PROCEDURES = (
    "📋 Selecione um ou mais procedimentos. Clique em 'Continuar' quando terminar."
)
MSG_REG_SELECT_PRICE = "💰 Selecione o valor do atendimento:"
MSG_REG_SAVING = "Salvando registro..."
MSG_REG_SUCCESS = (
    "✅ *Atendimento salvo com sucesso!*\n\n"
    "📅 *Data:* {date}\n"
    "👤 *Paciente:* {patient}\n"
    "📋 *Procedimentos:* {procedures}\n"
    "💰 *Valor:* {price}"
)
MSG_REG_ASK_ANOTHER = "Deseja registrar outro atendimento?"
MSG_REG_FINISHED = "Ok, operação finalizada."

# Deletar Command
MSG_DEL_ASK_DATE = "🗑️ Para qual data você deseja deletar um atendimento?"
MSG_DEL_SELECT_RECORD = "Selecione o atendimento para deletar em *{}*:\n\n"
MSG_DEL_CONFIRM = (
    "Você tem certeza que deseja deletar o seguinte atendimento?\n\n"
    "👤 *Paciente:* {patient}\n"
    "📋 *Procedimentos:* {procedures}\n"
    "💰 *Valor:* {price}"
)
MSG_DEL_SUCCESS = "✅ Atendimento deletado com sucesso!"
MSG_DEL_RETURN_TO_LIST = "Ok, voltando para a lista de atendimentos."

# Calcular Command
MSG_CALC_CHOOSE_PERIOD = "📊 Escolha o período para a listagem dos atendimentos:"
MSG_CALC_INVALID_DATE_RANGE = "⚠️ Data em formato inválido. Tente novamente ou /cancelar."
MSG_CALC_NO_RECORDS_FOUND = "ℹ️ Nenhum atendimento encontrado para {}."
MSG_CALC_DAY_SUMMARY = "🗓️ *{date}* ({count} {record_text})"
MSG_CALC_DAY_TOTAL = "\n💰 *Total do Dia:* R$ {total}"
MSG_CALC_GRAND_TOTAL = "\n\n📊 *Total de {count} atendimentos: R$ {total}*"
MSG_CALC_PROMPT_CUSTOM_MONTH = "📅 Por favor, digite o mês e ano no formato `MM/YYYY`:"
MSG_CALC_INVALID_MONTH_FORMAT = (
    "⚠️ Formato de data inválido. Por favor, use `MM/YYYY`. Tente novamente ou /cancelar."
)
MSG_CALC_MONTHLY_REPORT_PROMPT = "Gerar relatório mensal para o mês atual ou escolher outro?"

# Analytics Command
MSG_ANALYTICS_MENU = "📈 *Menu de Análises*\n\nEscolha qual relatório você deseja ver:"
MSG_ANALYTICS_NO_REVENUE = "Nenhum dado de faturamento encontrado."
MSG_ANALYTICS_NO_APPOINTMENTS = "Nenhum atendimento encontrado."
MSG_ANALYTICS_NO_PROCEDURES = "Nenhum procedimento encontrado."
MSG_ANALYTICS_NO_PATIENTS = "Nenhum paciente encontrado."
MSG_ANALYTICS_UNKNOWN_COMMAND = "Comando não reconhecido."
