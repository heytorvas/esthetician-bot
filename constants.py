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
    # Analytics States
    ANALYTICS_MENU,
    # Deletar States
    DEL_AWAITING_DATE,
    DEL_SELECTING_RECORD,
    DEL_CONFIRMING,
) = range(14)

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
    "hybrius": "Hybrius"
}
VALID_PRICES = [5, 10, 15, 20]
