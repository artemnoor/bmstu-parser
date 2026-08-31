import unittest

from bmstu_parser.ingestion.mirror_api import DetailFetch
from bmstu_parser.transform.normalize import Normalizer
from bmstu_parser.transform.text import clean_text


class TransformTests(unittest.TestCase):
    def test_html_text_keeps_semantic_lines(self) -> None:
        self.assertEqual(
            clean_text("<p>Первый&nbsp;текст</p><ul><li>Второй</li></ul>"),
            "Первый текст\nВторой",
        )

    def test_program_is_nested_under_department_and_choice_is_explicit(self) -> None:
        summary = {
            "slug": "test-major",
            "name": "Тестовое направление",
            "code": "01.03.01",
            "faculties": [
                {
                    "slug": "test-faculty",
                    "code": "Ф",
                    "title": "Тестовый факультет",
                    "chairs": [
                        {"slug": "test-chair", "code": "К", "title": "Тестовая кафедра"}
                    ],
                }
            ],
        }
        detail = {
            "additional": {"name": "Тестовое направление", "code": "01.03.01"},
            "faculty": {"slug": "test-faculty", "title": "Тестовый факультет"},
            "points": [
                {"title": "Математика", "point": 40, "isChoice": False},
                {"title": "Физика", "point": 39, "isChoice": True},
            ],
            "chairs": {
                "items": [
                    {
                        "slug": "test-chair",
                        "code": "К",
                        "title": "Тестовая кафедра",
                        "faculty": {
                            "slug": "test-faculty",
                            "title": "Тестовый факультет",
                        },
                        "educationalProgram": {
                            "items": [
                                {
                                    "name": "Тестовая программа",
                                    "code": "П01",
                                    "enrol": True,
                                    "discipline": ["Программирование"],
                                }
                            ]
                        },
                    }
                ]
            },
        }
        major = Normalizer().normalize(
            DetailFetch(summary, detail, None, "2026-01-01T00:00:00+00:00")
        )
        self.assertEqual(major.status, "ok")
        self.assertEqual(len(major.departments), 1)
        self.assertEqual(
            major.departments[0].educational_programs[0].department_id,
            major.departments[0].id,
        )
        self.assertEqual(
            major.entrance_requirements[0].requirement_type, "обязательный"
        )
        self.assertEqual(major.entrance_requirements[1].requirement_type, "по выбору")


if __name__ == "__main__":
    unittest.main()
