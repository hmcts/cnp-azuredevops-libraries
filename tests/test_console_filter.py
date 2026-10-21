# test for the filtered console view
import importlib.util
import pathlib
import unittest


SCRIPT_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "console_filter.py"
SPEC = importlib.util.spec_from_file_location("console_filter", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)
filter_console = MODULE.filter_console


class ConsoleFilterTests(unittest.TestCase):
    def test_displayed_resource_count_includes_data_reads(self):
        text = """Terraform will perform the following actions:

  # azurerm_resource.one will be updated in-place
  ~ resource "azurerm_resource" "one" { name = "updated" }

  # azurerm_resource.two will be updated in-place
  ~ resource "azurerm_resource" "two" { name = "updated" }

  # data.example.lookup will be read during apply
  <= data "example" "lookup" { id = (known after apply) }

Plan: 0 to add, 2 to change, 0 to destroy.

Changes to Outputs:
  ~ output_value = "before" -> "after"
"""
        by_address = {
            "azurerm_resource.one": [
                {"data_read": False, "tags_only": False, "change_type": "update"}
            ],
            "azurerm_resource.two": [
                {"data_read": False, "tags_only": False, "change_type": "update"}
            ],
            "data.example.lookup": [
                {"data_read": True, "tags_only": False, "change_type": "read"}
            ],
        }

        output = filter_console(text, by_address)

        self.assertIn(
            "3 of 3 resource change(s) shown; 0 tag-only change(s) hidden; "
            "1 data read shown.",
            output,
        )
        self.assertIn("data.example.lookup will be read during apply", output)
        self.assertIn('Changes to Outputs:\n  ~ output_value = "before" -> "after"', output)
        self.assertLess(output.index("resource change(s) shown"), output.index("Changes to Outputs:"))

    def test_data_read_details_remain_visible_without_resource_changes(self):
        text = """Terraform will perform the following actions:

  # data.example.lookup will be read during apply
  <= data "example" "lookup" { id = (known after apply) }

Plan: 0 to add, 0 to change, 0 to destroy.
"""
        by_address = {
            "data.example.lookup": [
                {"data_read": True, "tags_only": False, "change_type": "read"}
            ],
        }

        output = filter_console(text, by_address)

        self.assertIn("data.example.lookup will be read during apply", output)
        self.assertIn(
            "1 of 1 resource change(s) shown; 0 tag-only change(s) hidden; "
            "1 data read shown.",
            output,
        )

    def test_output_only_plan_keeps_output_changes(self):
        text = '''Terraform will perform the following actions:

Plan: 0 to add, 0 to change, 0 to destroy.

Changes to Outputs:
  + output_value = "created"
'''

        output = filter_console(text, {})

        self.assertIn("No planned resource changes.", output)
        self.assertIn('Changes to Outputs:\n  + output_value = "created"', output)


if __name__ == "__main__":
    unittest.main()