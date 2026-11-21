"""Check the counter endpoint after moving it into the unified package."""

import importlib.util
import json
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import patch

from aiohttp import web


class CounterRouteTests(unittest.TestCase):
    def setUp(self):
        self.routes = web.RouteTableDef()
        server = types.ModuleType("server")
        server.PromptServer = types.SimpleNamespace(
            instance=types.SimpleNamespace(routes=self.routes),
        )
        path = Path(__file__).resolve().parents[1] / "_plugins/imagebatch/routes.py"
        spec = importlib.util.spec_from_file_location("_test_imagebatch_routes", path)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"server": server}):
            spec.loader.exec_module(self.module)
        self.loader = types.SimpleNamespace(
            _cache_lock=threading.RLock(),
            _counters={"automatic": 3},
            _fixed_counters={"fixed": 5},
        )

    def test_reset_clears_both_counter_modes(self):
        self.module.register_routes(self.loader)
        route, = self.routes
        self.assertEqual((route.method, route.path), ("POST", "/lx_imagebatch/reset_counter"))
        # This endpoint has no await points; it needs no socket-backed event loop.
        coroutine = route.handler(None)
        with self.assertRaises(StopIteration) as completed:
            coroutine.send(None)
        response = completed.exception.value
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.text)["status"], "success")
        self.assertEqual(self.loader._counters, {})
        self.assertEqual(self.loader._fixed_counters, {})

    def test_registering_twice_keeps_one_handler(self):
        self.module.register_routes(self.loader)
        self.module.register_routes(self.loader)
        self.assertEqual(len(self.routes), 1)


if __name__ == "__main__":
    unittest.main()
