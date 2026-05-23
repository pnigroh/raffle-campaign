from django.test import SimpleTestCase

from campaigns.schema_validator import validate_form_schema


class SchemaValidatorTopLevelTests(SimpleTestCase):

    def test_empty_dict_is_valid(self):
        """Empty schema triggers the default at render time and is treated as valid here."""
        self.assertEqual(validate_form_schema({}), [])

    def test_top_level_must_be_dict(self):
        errs = validate_form_schema([])
        self.assertTrue(any("must be an object" in e["message"] for e in errs))

    def test_unknown_top_level_key_rejected(self):
        errs = validate_form_schema({"version": 1, "fields": [], "extra": "nope"})
        self.assertTrue(any(e["path"] == "extra" for e in errs))

    def test_version_must_be_int_1_rejects_string(self):
        errs = validate_form_schema({"version": "1", "fields": []})
        self.assertTrue(any("version" in e["path"] for e in errs))

    def test_version_must_be_int_1_rejects_wrong_int(self):
        errs = validate_form_schema({"version": 2, "fields": []})
        self.assertTrue(any("version" in e["path"] for e in errs))

    def test_fields_must_be_list(self):
        errs = validate_form_schema({"version": 1, "fields": {}})
        self.assertTrue(any(e["path"] == "fields" for e in errs))

    def test_required_builtins_must_be_present(self):
        # Missing first_name
        errs = validate_form_schema({
            "version": 1,
            "fields": [
                {"kind": "builtin", "key": "last_name", "required": True, "label": "Last"},
                {"kind": "builtin", "key": "email", "required": True, "label": "Email"},
            ],
        })
        self.assertTrue(any("first_name" in e["message"] for e in errs))

    def test_required_builtins_must_have_required_true(self):
        # Present but required=False
        errs = validate_form_schema({
            "version": 1,
            "fields": [
                {"kind": "builtin", "key": "first_name", "required": False, "label": "F"},
                {"kind": "builtin", "key": "last_name", "required": True, "label": "L"},
                {"kind": "builtin", "key": "email", "required": True, "label": "E"},
            ],
        })
        self.assertTrue(
            any("first_name" in e["message"] and "required" in e["message"] for e in errs)
        )

    def test_minimal_valid_schema(self):
        errs = validate_form_schema({
            "version": 1,
            "fields": [
                {"kind": "builtin", "key": "first_name", "required": True, "label": "First"},
                {"kind": "builtin", "key": "last_name", "required": True, "label": "Last"},
                {"kind": "builtin", "key": "email", "required": True, "label": "Email"},
            ],
        })
        self.assertEqual(errs, [])


class BuiltinShapeTests(SimpleTestCase):

    def test_unknown_builtin_key_rejected(self):
        errs = validate_form_schema({
            "version": 1,
            "fields": [
                {"kind": "builtin", "key": "first_name", "required": True, "label": "F"},
                {"kind": "builtin", "key": "last_name", "required": True, "label": "L"},
                {"kind": "builtin", "key": "email", "required": True, "label": "E"},
                {"kind": "builtin", "key": "favorite_color", "required": False, "label": "C"},
            ],
        })
        self.assertTrue(any("favorite_color" in e["message"] for e in errs))

    def test_state_allowed_states_not_a_list_rejected(self):
        base = [
            {"kind": "builtin", "key": "first_name", "required": True, "label": "F"},
            {"kind": "builtin", "key": "last_name", "required": True, "label": "L"},
            {"kind": "builtin", "key": "email", "required": True, "label": "E"},
        ]
        errs = validate_form_schema({
            "version": 1,
            "fields": base + [{"kind": "builtin", "key": "state", "required": True,
                               "label": "S", "allowed_states": "CA"}],
        })
        self.assertTrue(any("allowed_states" in e["path"] for e in errs))

    def test_state_allowed_states_entry_missing_code_rejected(self):
        base = [
            {"kind": "builtin", "key": "first_name", "required": True, "label": "F"},
            {"kind": "builtin", "key": "last_name", "required": True, "label": "L"},
            {"kind": "builtin", "key": "email", "required": True, "label": "E"},
        ]
        errs = validate_form_schema({
            "version": 1,
            "fields": base + [{"kind": "builtin", "key": "state", "required": True,
                               "label": "S", "allowed_states": [{"label": "California"}]}],
        })
        self.assertTrue(any("allowed_states" in e["path"] for e in errs))

    def test_state_allowed_states_duplicate_codes_rejected(self):
        base = [
            {"kind": "builtin", "key": "first_name", "required": True, "label": "F"},
            {"kind": "builtin", "key": "last_name", "required": True, "label": "L"},
            {"kind": "builtin", "key": "email", "required": True, "label": "E"},
        ]
        errs = validate_form_schema({
            "version": 1,
            "fields": base + [{"kind": "builtin", "key": "state", "required": True,
                               "label": "S", "allowed_states": [
                                   {"code": "CA", "label": "California"},
                                   {"code": "CA", "label": "Cali"},
                               ]}],
        })
        self.assertTrue(any("duplicate" in e["message"].lower() for e in errs))

    def test_state_allowed_states_empty_is_valid(self):
        """Empty list → consumer falls back to default 51."""
        base = [
            {"kind": "builtin", "key": "first_name", "required": True, "label": "F"},
            {"kind": "builtin", "key": "last_name", "required": True, "label": "L"},
            {"kind": "builtin", "key": "email", "required": True, "label": "E"},
        ]
        errs = validate_form_schema({
            "version": 1,
            "fields": base + [{"kind": "builtin", "key": "state", "required": True,
                               "label": "S", "allowed_states": []}],
        })
        self.assertEqual(errs, [])
