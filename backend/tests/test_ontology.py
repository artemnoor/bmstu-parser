import unittest

from university_data.domain.ids import global_stable_id
from university_data.ontology import build_ontology


class OntologyTests(unittest.TestCase):
    def test_objects_and_links_are_deduplicated_and_closed(self) -> None:
        university_id = global_stable_id("fake", "university", "fake")
        records = {
            "universities": [{"id": university_id, "university_id": "fake"}],
            "faculties": [{"id": "faculty-1", "university_id": "fake"}],
            "departments": [
                {
                    "id": "department-1",
                    "university_id": "fake",
                    "faculty_id": "faculty-1",
                }
            ],
            "programs": [
                {
                    "id": "program-1",
                    "university_id": "fake",
                    "department_id": "department-1",
                }
            ],
        }
        ontology = build_ontology("fake", records)
        object_ids = {item["id"] for item in ontology["objects"]}
        self.assertTrue(
            all(
                link["from"] in object_ids and link["to"] in object_ids
                for link in ontology["links"]
            )
        )
        self.assertEqual(ontology["broken_links"], [])


if __name__ == "__main__":
    unittest.main()
