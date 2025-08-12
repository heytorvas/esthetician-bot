import sys
import os
from unittest import TestCase

# Add the parent directory to the path to allow importing 'main'
sys.path.append(os.path.dirname(os.path.realpath(__file__)))

from main import parse_record_text, PROCEDURE_DESCRIPTIONS

class TestParseRecordText(TestCase):
    def test_valid_record_parsing(self):
        test_cases = [
            ("Maria Limpeza de Pele 150", "Maria", ["Limpeza de Pele"], 150.0),
            ("João da Silva Detox 200", "João da Silva", ["Detox"], 200.0),
            ("Ana Pós Operatório, SPA 350.50", "Ana", ["Pós Operatório", "SPA"], 350.50),
            ("Carlos pos-operatorio 100", "Carlos", ["Pós Operatório"], 100.0),
            ("Beatriz limpeza de pele 120", "Beatriz", ["Limpeza de Pele"], 120.0),
            ("Tiago   Pós   Operatório   110", "Tiago", ["Pós Operatório"], 110.0),
            ("Fernanda 3MH 50", "Fernanda", ["3MH"], 50.0),
            ("Tom Brady Limpeza de Pele, Pós Operatório 500", "Tom Brady", ["Limpeza de Pele", "Pós Operatório"], 500.0),
            ("Detox SPA Peter Parker 250", "Peter Parker", ["Detox", "SPA"], 250.0),
            ("Peter Parker Spiderman Detox SPA 300", "Peter Parker Spiderman", ["Detox", "SPA"], 300.0),
            ("Juliana Body Shape 250,99", "Juliana", ["Body Shape"], 250.99),
        ]

        for text, expected_patient, expected_procedures, expected_price in test_cases:
            result = parse_record_text(text, PROCEDURE_DESCRIPTIONS)
            assert result is not None, f"Failed on: {text}"
            patient, procedures, price = result
            assert patient == expected_patient, f"Patient name mismatch on: {text}"
            assert sorted(procedures) == sorted(expected_procedures), f"Procedures mismatch on: {text}"
            assert price == expected_price, f"Price mismatch on: {text}"

    def test_invalid_record_parsing(self):
        invalid_cases = [
            "Maria Limpeza de Pele",
            "José da Silva 150",
            "Detox 100",
            "",
            "JustOneWord",
        ]

        for text in invalid_cases:
            result = parse_record_text(text, PROCEDURE_DESCRIPTIONS)
            assert result is None, f"Expected None for invalid input '{text}', but got a result."
