import unittest

from support import load_module

m = load_module("packB/settings.py")


class SettingsTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(m.parse_settings(""), {})
        text = " # comment\r\n port = 80\nempty=\nexpr=a=b # literal\nport=81\n"
        self.assertEqual(m.parse_settings(text),
                         {"port": "81", "empty": "", "expr": "a=b # literal"})
        self.assertEqual(m.parse_settings("_x2=yes\nA=one\na=two"),
                         {"_x2": "yes", "A": "one", "a": "two"})
        for text in ["broken", "=value", "2x=yes", "a-b=yes", "é=yes", "aé=yes"]:
            with self.assertRaises(ValueError):
                m.parse_settings(text)
        with self.assertRaisesRegex(ValueError, "line 3"):
            m.parse_settings("# comment\n\nbroken")

    def test_render_and_round_trip(self):
        values = {"z": "", "a": "x=y # literal", "_2": "café"}
        rendered = "_2=café\na=x=y # literal\nz=\n"
        self.assertEqual(m.render_settings(values), rendered)
        self.assertEqual(m.parse_settings(rendered), values)
        self.assertEqual(m.render_settings({}), "")
        self.assertEqual(values, {"z": "", "a": "x=y # literal", "_2": "café"})

    def test_render_rejections(self):
        for key in ["", "2x", "x-y", "é", "aé"]:
            with self.assertRaises(ValueError):
                m.render_settings({key: "ok"})
        for value in [" x", "x ", "\tx", "x\n", "x\ny", "x\ry", "x\vy",
                      "x\fy", "x\x1cy", "x\x1dy", "x\x1ey",
                      "x\x85y", "x\u2028y", "x\u2029y"]:
            with self.assertRaises(ValueError):
                m.render_settings({"key": value})

    def test_overlay_and_prefix(self):
        base = {"db_host": "local", "db_port": "1", "mode": "dev"}
        updates = {"mode": "prod"}
        result = m.overlay(base, updates)
        self.assertEqual(result, {"db_host": "local", "db_port": "1", "mode": "prod"})
        self.assertEqual(base["mode"], "dev")
        self.assertEqual(updates, {"mode": "prod"})
        self.assertIsNot(result, base)
        self.assertEqual(m.select_prefix(base, "db_"), {"db_host": "local", "db_port": "1"})
        self.assertEqual(m.select_prefix(base, "absent"), {})
        self.assertEqual(m.select_prefix(base, ""), base)
        self.assertIsNot(m.select_prefix(base, ""), base)
