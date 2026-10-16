"""Run the existing suite on a new audit database; discard token-bearing logs."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "SnapSave-Backend"))
os.chdir(ROOT / "SnapSave-Backend")
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(tempfile.mkdtemp(prefix="suite-", dir=HERE)) / "tests.db").replace("\\", "/")
os.environ["DEBUG"] = "false"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
results = []
class Recorder:
    def pytest_runtest_logreport(self, report):
        if report.when == "call" or report.failed:
            item = {"test": report.nodeid, "phase": report.when, "outcome": report.outcome}
            if report.failed:
                crash = getattr(report.longrepr, "reprcrash", None)
                item["reason"] = crash.message if crash else str(report.longrepr).splitlines()[0]
            results.append(item)

with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    import pytest
    from api.server import app
    from database import Base, engine
    Base.metadata.create_all(engine)
    exit_code = pytest.main(["tests", "-q", "-p", "no:cacheprovider", "--tb=no"], plugins=[Recorder()])
output = {"exit_code": int(exit_code), "results": results}
(HERE / "existing-tests.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
print(json.dumps(output, indent=2))
