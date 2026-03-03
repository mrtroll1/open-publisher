import pytest
from datetime import date

from backend.infrastructure.gateways.docs_gateway import DocsGateway


# ===================================================================
#  DocsGateway.format_date_ru()
# ===================================================================

class TestFormatDateRu:

    @pytest.mark.parametrize(
        "d, expected",
        [
            (date(2026, 1, 15), "«15» января 2026 г."),
            (date(2026, 2, 1), "«01» февраля 2026 г."),
            (date(2026, 3, 5), "«05» марта 2026 г."),
            (date(2026, 4, 10), "«10» апреля 2026 г."),
            (date(2026, 5, 20), "«20» мая 2026 г."),
            (date(2026, 6, 30), "«30» июня 2026 г."),
            (date(2026, 7, 7), "«07» июля 2026 г."),
            (date(2026, 8, 8), "«08» августа 2026 г."),
            (date(2026, 9, 9), "«09» сентября 2026 г."),
            (date(2026, 10, 10), "«10» октября 2026 г."),
            (date(2026, 11, 11), "«11» ноября 2026 г."),
            (date(2026, 12, 25), "«25» декабря 2026 г."),
        ],
        ids=[
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
        ],
    )
    def test_all_months(self, d, expected):
        assert DocsGateway.format_date_ru(d) == expected

    def test_day_zero_padded(self):
        result = DocsGateway.format_date_ru(date(2026, 1, 3))
        assert result.startswith("«03»")

    def test_day_two_digits(self):
        result = DocsGateway.format_date_ru(date(2026, 1, 31))
        assert result.startswith("«31»")

    def test_year_in_output(self):
        result = DocsGateway.format_date_ru(date(2025, 6, 15))
        assert "2025 г." in result


# ===================================================================
#  DocsGateway.format_date_en()
# ===================================================================

class TestFormatDateEn:

    @pytest.mark.parametrize(
        "d, expected",
        [
            (date(2026, 1, 15), "15.01.2026"),
            (date(2026, 12, 5), "05.12.2026"),
            (date(2025, 3, 31), "31.03.2025"),
            (date(2026, 7, 1), "01.07.2026"),
        ],
        ids=["mid_month", "dec_single_digit", "march_end", "july_first"],
    )
    def test_format(self, d, expected):
        assert DocsGateway.format_date_en(d) == expected


# ===================================================================
#  DocsGateway._find_placeholder_index()
# ===================================================================

class TestFindPlaceholderIndex:

    def test_finds_placeholder_in_paragraph(self):
        doc = {
            "body": {
                "content": [
                    {
                        "startIndex": 0,
                        "paragraph": {
                            "elements": [
                                {"textRun": {"content": "Some text before"}}
                            ]
                        },
                    },
                    {
                        "startIndex": 50,
                        "paragraph": {
                            "elements": [
                                {"textRun": {"content": "Text with {{PLACEHOLDER}} here"}}
                            ]
                        },
                    },
                ]
            }
        }
        assert DocsGateway._find_placeholder_index(doc, "{{PLACEHOLDER}}") == 50

    def test_returns_none_when_not_found(self):
        doc = {
            "body": {
                "content": [
                    {
                        "startIndex": 0,
                        "paragraph": {
                            "elements": [
                                {"textRun": {"content": "No placeholder here"}}
                            ]
                        },
                    },
                ]
            }
        }
        assert DocsGateway._find_placeholder_index(doc, "{{MISSING}}") is None

    def test_empty_doc(self):
        doc = {"body": {"content": []}}
        assert DocsGateway._find_placeholder_index(doc, "{{X}}") is None

    def test_no_body(self):
        doc = {}
        assert DocsGateway._find_placeholder_index(doc, "{{X}}") is None

    def test_skips_non_paragraph_elements(self):
        doc = {
            "body": {
                "content": [
                    {"startIndex": 0, "table": {}},
                    {
                        "startIndex": 100,
                        "paragraph": {
                            "elements": [
                                {"textRun": {"content": "{{TARGET}}"}}
                            ]
                        },
                    },
                ]
            }
        }
        assert DocsGateway._find_placeholder_index(doc, "{{TARGET}}") == 100

    def test_returns_first_match(self):
        doc = {
            "body": {
                "content": [
                    {
                        "startIndex": 10,
                        "paragraph": {
                            "elements": [
                                {"textRun": {"content": "{{DUP}}"}}
                            ]
                        },
                    },
                    {
                        "startIndex": 200,
                        "paragraph": {
                            "elements": [
                                {"textRun": {"content": "{{DUP}}"}}
                            ]
                        },
                    },
                ]
            }
        }
        assert DocsGateway._find_placeholder_index(doc, "{{DUP}}") == 10

    def test_element_without_text_run(self):
        doc = {
            "body": {
                "content": [
                    {
                        "startIndex": 0,
                        "paragraph": {
                            "elements": [
                                {"inlineObjectElement": {}},
                                {"textRun": {"content": "{{FOUND}}"}},
                            ]
                        },
                    },
                ]
            }
        }
        assert DocsGateway._find_placeholder_index(doc, "{{FOUND}}") == 0
