import unittest

from bmstu_parser.ingestion.mirror_api import DetailFetch
from bmstu_parser.transform.normalize import Normalizer
from bmstu_parser.transform.ontology import OntologyBuilder


def sample_major():
    summary = {
        "slug": "major",
        "name": "Направление",
        "code": "01.03.01",
        "faculties": [{"slug": "faculty", "title": "Факультет", "chairs": []}],
    }
    detail = {
        "additional": {"name": "Направление", "code": "01.03.01"},
        "faculty": {"slug": "faculty", "title": "Факультет"},
        "chairs": {
            "items": [
                {
                    "slug": "chair",
                    "title": "Кафедра",
                    "faculty": {"slug": "faculty", "title": "Факультет"},
                    "educationalProgram": {
                        "items": [{"name": "Программа", "code": "P"}]
                    },
                }
            ]
        },
    }
    return Normalizer().normalize(DetailFetch(summary, detail, None, "now"))


class OntologyTests(unittest.TestCase):
    def test_objects_and_links_are_deduplicated_and_closed(self) -> None:
        major = sample_major()
        ontology = OntologyBuilder().build([major, major])
        self.assertEqual(len(ontology["objects"]["major"]), 1)
        self.assertEqual(len(ontology["objects"]["department"]), 1)
        object_ids = {
            item["id"] for bucket in ontology["objects"].values() for item in bucket
        }
        self.assertTrue(
            all(
                link["from_id"] in object_ids and link["to_id"] in object_ids
                for link in ontology["links"]
            )
        )


if __name__ == "__main__":
    unittest.main()
