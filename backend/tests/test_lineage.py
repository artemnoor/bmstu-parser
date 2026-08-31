import json
import tempfile
import unittest
from pathlib import Path

from bmstu_parser.runtime.lineage import PipelineRun


class LineageTests(unittest.TestCase):
    def test_pipeline_run_persists_stage_artifacts_and_latest_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            source.write_text("source", encoding="utf-8")

            run = PipelineRun(root, "test_pipeline")
            run.stage(
                "transform",
                inputs=["source.txt"],
                outputs=["source.txt"],
                metadata={"rows": 1},
            )
            run.finish(quality={"verification": {"passed": True}})

            manifest = json.loads(run.path.read_text(encoding="utf-8"))
            latest = json.loads(
                (root / "pipeline_runs" / "latest.json").read_text(encoding="utf-8")
            )

            self.assertEqual(manifest["status"], "succeeded")
            self.assertEqual(latest["run_id"], run.run_id)
            self.assertEqual(manifest["stages"][0]["metadata"]["rows"], 1)
            self.assertEqual(
                manifest["stages"][0]["inputs"][0]["sha256"],
                manifest["stages"][0]["outputs"][0]["sha256"],
            )


if __name__ == "__main__":
    unittest.main()
