"""Execute the two example nodes without loading the ComfyUI server."""

import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class TextExampleTests(unittest.TestCase):
    def test_workflow_links_match_nodes_and_text_reaches_display(self):
        workflow = json.loads((ROOT / "examples/text_basic.json").read_text(encoding="utf-8"))
        source, target = workflow["nodes"]
        self.assertEqual((source["type"], target["type"]), ("LXText", "LXShowText"))
        self.assertEqual(workflow["links"], [[1, source["id"], 0, target["id"], 0, "STRING"]])
        self.assertEqual(source["outputs"][0]["links"], [1])
        self.assertEqual(target["inputs"][0]["link"], 1)
        modules = {}
        for name in ("_release_example", "_release_example.text_tools", "_release_example.utility"):
            modules[name] = types.ModuleType(name)
            modules[name].__path__ = []
        categories = types.ModuleType("_release_example.categories")
        categories.LX_TEXT_CATEGORY = "text"
        categories.LX_UTILITY_CATEGORY = "utility"
        modules[categories.__name__] = categories
        with patch.dict(sys.modules, modules):
            loaded = []
            for name, relative in (("text_tools.text", "text_tools/text.py"), ("utility.show_text", "utility/show_text.py")):
                spec = importlib.util.spec_from_file_location("_release_example." + name, ROOT / "_plugins" / relative)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                loaded.append(module)
            text_node, display_node = loaded[0].LXText(), loaded[1].LXShowText()
            self.assertEqual(text_node.RETURN_TYPES[0], "STRING")
            self.assertEqual(display_node.INPUT_TYPES()["required"][target["inputs"][0]["name"]][0], "STRING")
            (text,) = text_node.emit(source["widgets_values"][0])
            result = display_node.show(text)
            self.assertEqual(result["ui"]["text"], source["widgets_values"])
            self.assertEqual(result["result"], (text,))


if __name__ == "__main__":
    unittest.main()
