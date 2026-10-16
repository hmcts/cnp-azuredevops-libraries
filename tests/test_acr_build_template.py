import os
import pathlib
import re
import shutil
import stat
import subprocess
import tempfile
import unittest


TEMPLATE_PATH = pathlib.Path(__file__).resolve().parents[1] / "steps" / "acr-build.yaml"
TEMPLATE = TEMPLATE_PATH.read_text()


def extract_inline_script() -> str:
    """Return the dedented bash body of the ACR Build task's inlineScript."""
    lines = TEMPLATE.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "inlineScript: |")
    body = []
    for line in lines[start + 1:]:
        if line.strip() and not line.startswith("      "):
            break
        body.append(line[6:] if line.strip() else "")
    return "\n".join(body) + "\n"


SCRIPT = extract_inline_script()

# Mirrors the env: block of the task (see steps/acr-build.yaml). The coalesce
# fallbacks are applied here the way Azure DevOps applies them at compile time.
DEFAULT_ENV = {
    "ACR_NAME": "myacr",
    "ACR_RESOURCE_GROUP": "myrg",
    "IMAGE_NAME": "org/repo",
    "IMAGE_TAG": "pr-12",
    "DOCKERFILE": "",
    "BUILD_TARGET": "",
    "ADDITIONAL_TAGS": "",
    "BUILD_CONTEXT": ".",
}


def run_script(**overrides):
    """Run the inline script with a stub `az` and return the args passed to `acr build`."""
    env_vars = {**DEFAULT_ENV, **overrides}
    with tempfile.TemporaryDirectory() as tmp:
        stub = pathlib.Path(tmp) / "az"
        out = pathlib.Path(tmp) / "args.txt"
        stub.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$AZ_ARGS_FILE"\n')
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        env = {
            "PATH": f"{tmp}:{os.environ['PATH']}",
            "AZ_ARGS_FILE": str(out),
            **env_vars,
        }
        subprocess.run(["bash", "-c", SCRIPT], env=env, check=True, capture_output=True, text=True)
        return out.read_text().splitlines()


class AcrBuildScriptTests(unittest.TestCase):
    def test_no_new_parameters_matches_legacy_command(self):
        # Legacy: az acr build -r $(acrName) -t $(Build.Repository.Name):$(imageTag) -g $(acrResourceGroup) .
        self.assertEqual(
            run_script(),
            ["acr", "build", "-r", "myacr", "-t", "org/repo:pr-12", "-g", "myrg", "."],
        )

    def test_all_new_parameters_emit_every_flag(self):
        args = run_script(
            DOCKERFILE="docker/Dockerfile.app",
            BUILD_TARGET="listener",
            ADDITIONAL_TAGS="pr-123-abc,latest",
            BUILD_CONTEXT="src",
        )
        self.assertEqual(
            args,
            [
                "acr", "build", "-r", "myacr", "-t", "org/repo:pr-12", "-g", "myrg",
                "-f", "docker/Dockerfile.app",
                "--target", "listener",
                "-t", "org/repo:pr-123-abc",
                "-t", "org/repo:latest",
                "src",
            ],
        )

    def test_values_with_spaces_stay_single_arguments(self):
        args = run_script(DOCKERFILE="my docker/Dockerfile", BUILD_CONTEXT="my ctx")
        self.assertIn("my docker/Dockerfile", args)
        self.assertEqual(args[-1], "my ctx")

    def test_monorepo_listener_image(self):
        args = run_script(
            IMAGE_NAME="dlrm-aria-doc-mig/doc-intake-store-listener",
            BUILD_TARGET="listener",
        )
        self.assertIn("dlrm-aria-doc-mig/doc-intake-store-listener:pr-12", args)
        self.assertEqual(args[args.index("--target") + 1], "listener")


class AcrBuildTemplateTests(unittest.TestCase):
    def test_new_parameters_default_to_legacy_behaviour(self):
        params = TEMPLATE.split("steps:")[0]
        for name, default in [
            ("imageName", "''"),
            ("dockerfile", "''"),
            ("target", "''"),
            ("acrName", "''"),
            ("acrResourceGroup", "''"),
            ("additionalTags", "[]"),
            ("buildContext", "'.'"),
        ]:
            self.assertRegex(params, rf"(?m)^  {name}: {re.escape(default)}$")

    def test_pipeline_variable_fallbacks(self):
        self.assertIn("coalesce(parameters.acrName, '$(acrName)')", TEMPLATE)
        self.assertIn("coalesce(parameters.acrResourceGroup, '$(acrResourceGroup)')", TEMPLATE)
        self.assertIn("coalesce(parameters.imageName, '$(Build.Repository.Name)')", TEMPLATE)

    def test_task_version_and_script_settings(self):
        self.assertIn("task: AzureCLI@2", TEMPLATE)
        self.assertNotIn("AzureCLI@1", TEMPLATE)
        self.assertIn("scriptType: 'bash'", TEMPLATE)
        self.assertIn("scriptLocation: 'inlineScript'", TEMPLATE)
        self.assertIn("azureSubscription: ${{ parameters.serviceConnection }}", TEMPLATE)

    def test_build_path_condition_is_not_nested(self):
        self.assertIn("${{ if ne(parameters.buildPath, '') }}:", TEMPLATE)
        self.assertNotIn("${{ if ne('${{", TEMPLATE)

    def test_tag_setting_steps_unchanged(self):
        for display_name in (
            "Set Image Tag: Pull Request",
            "Set Image Tag: Branch",
            "Set Image Tag: Custom",
        ):
            self.assertIn(f"displayName: '{display_name}'", TEMPLATE)


@unittest.skipIf(shutil.which("bash") is None, "bash not available")
class BashAvailableTests(unittest.TestCase):
    def test_script_is_valid_bash(self):
        subprocess.run(["bash", "-n", "-c", SCRIPT], check=True)


if __name__ == "__main__":
    unittest.main()
