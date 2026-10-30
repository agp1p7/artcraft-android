import unittest
from patch_lightcraft_export_full import code_mask, wrap_services


class ServicesInitializerTests(unittest.TestCase):
    def wrap(self, expression):
        source = 'let services = ' + expression + ';'
        expected = 'let services = lightcraft_export_services(' + expression + ');'
        self.assertEqual(wrap_services(source), expected)

    def test_default(self):
        self.wrap('lightcraft_ui_egui::Services::default()')

    def test_struct_literal(self):
        self.wrap('Services { ..Default::default() }')

    def test_three_matches_are_one_initializer(self):
        source = 'fn make_services() -> lightcraft_ui_egui::Services {\n    lightcraft_ui_egui::Services {\n        ..lightcraft_ui_egui::Services::default()\n    }\n}\n'
        expression = 'lightcraft_ui_egui::Services {\n        ..lightcraft_ui_egui::Services::default()\n    }'
        expected = source.replace(expression, 'lightcraft_export_services(' + expression + ')', 1)
        self.assertEqual(wrap_services(source), expected)
        self.assertIn('-> lightcraft_ui_egui::Services {', wrap_services(source))

    def test_declarations_are_not_constructors(self):
        source = 'struct Services {}\nimpl Default for Services {}\nlet services = Services::default();'
        expected = source.replace('Services::default()', 'lightcraft_export_services(Services::default())')
        self.assertEqual(wrap_services(source), expected)

    def test_return_type_without_initializer_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'expected=1 actual=0'):
            wrap_services("fn services() -> &'static Services { unreachable!() }")

    def test_multiple_independent_initializers_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'expected=1 actual=2') as caught:
            wrap_services('let a = Services::default();\nlet b = Services::default();')
        self.assertIn('line 1:', str(caught.exception))
        self.assertIn('line 2:', str(caught.exception))

    def test_strings_comments_and_characters(self):
        b = chr(92)
        cases = [
            'Services { value: "a ' + b + '" } still in string", ..Default::default() }',
            'Services { /* } /* nested } */ } */ ..Default::default() }',
            'Services { value: r##"a " } Services { "##, ..Default::default() }',
            "Services { value: '" + b + "u{7d}', ..Default::default() }",
        ]
        for expression in cases:
            with self.subTest(expression=expression):
                self.wrap(expression)
                self.assertEqual(len(code_mask(expression)), len(expression))

    def test_unbalanced_initializer_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'unbalanced braces'):
            wrap_services('let services = Services {')


if __name__ == '__main__':
    unittest.main()
