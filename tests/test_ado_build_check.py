import importlib.util
import pathlib
import sys
import types
import unittest


SCRIPT_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "ado-build-check.py"
SPEC = importlib.util.spec_from_file_location("ado_build_check", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader

# Provide lightweight stub so policy tests run even when requests is not installed.
requests_stub = types.ModuleType("requests")
requests_stub.RequestException = Exception
def _unused_get(*_args, **_kwargs):
    raise NotImplementedError("requests.get not used in policy tests")
requests_stub.get = _unused_get
sys.modules.setdefault("requests", requests_stub)

SPEC.loader.exec_module(MODULE)


class AdoBuildCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        MODULE.include_release_branches = False

    @staticmethod
    def build(build_id: int, source_branch: str, reason: str, status: str = "inProgress"):
        return {
            "id": build_id,
            "sourceBranch": source_branch,
            "reason": reason,
            "status": status,
        }

    def test_classify_mainline_beats_reason(self):
        build = self.build(1, "refs/heads/main", "manual")
        self.assertEqual(MODULE.classify_build(build), "mainline")

    def test_classify_manual(self):
        build = self.build(2, "refs/heads/feature/x", "manual")
        self.assertEqual(MODULE.classify_build(build), "manual")

    def test_classify_pr(self):
        build = self.build(3, "refs/pull/12/merge", "pullRequest")
        self.assertEqual(MODULE.classify_build(build), "pr")

    def test_classify_other(self):
        build = self.build(4, "refs/heads/feature/x", "individualCI")
        self.assertEqual(MODULE.classify_build(build), "other")

    def test_mainline_ignores_lower_priorities(self):
        current = self.build(10, "refs/heads/main", "individualCI")
        others = [
            self.build(11, "refs/heads/feature/a", "manual"),
            self.build(12, "refs/pull/1/merge", "pullRequest"),
            self.build(13, "refs/heads/feature/b", "individualCI"),
        ]

        competitors = MODULE.select_competing_builds(current, others)
        self.assertEqual([build["id"] for build in competitors], [10])

    def test_manual_waits_for_mainline_not_pr_or_other(self):
        current = self.build(20, "refs/heads/feature/a", "manual")
        others = [
            self.build(21, "refs/heads/main", "individualCI"),
            self.build(22, "refs/pull/1/merge", "pullRequest"),
            self.build(23, "refs/heads/feature/b", "individualCI"),
        ]

        competitors = MODULE.select_competing_builds(current, others)
        self.assertEqual([build["id"] for build in competitors], [20, 21])

    def test_pr_waits_for_mainline_and_manual(self):
        current = self.build(30, "refs/pull/2/merge", "pullRequest")
        others = [
            self.build(31, "refs/heads/main", "individualCI"),
            self.build(32, "refs/heads/feature/a", "manual"),
            self.build(33, "refs/heads/feature/b", "individualCI"),
        ]

        competitors = MODULE.select_competing_builds(current, others)
        self.assertEqual([build["id"] for build in competitors], [30, 31, 32])

    def test_other_waits_for_everything(self):
        current = self.build(40, "refs/heads/feature/z", "individualCI")
        others = [
            self.build(41, "refs/heads/main", "individualCI"),
            self.build(42, "refs/heads/feature/a", "manual"),
            self.build(43, "refs/pull/3/merge", "pullRequest"),
        ]

        competitors = MODULE.select_competing_builds(current, others)
        self.assertEqual([build["id"] for build in competitors], [40, 41, 42, 43])


if __name__ == "__main__":
    unittest.main()
