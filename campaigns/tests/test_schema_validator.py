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

    BASE_FIELDS = [
        {"kind": "builtin", "key": "first_name", "required": True, "label": "F"},
        {"kind": "builtin", "key": "last_name", "required": True, "label": "L"},
        {"kind": "builtin", "key": "email", "required": True, "label": "E"},
    ]

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
        errs = validate_form_schema({
            "version": 1,
            "fields": self.BASE_FIELDS + [{"kind": "builtin", "key": "state", "required": True,
                               "label": "S", "allowed_states": "CA"}],
        })
        self.assertTrue(any("allowed_states" in e["path"] for e in errs))

    def test_state_allowed_states_entry_missing_code_rejected(self):
        errs = validate_form_schema({
            "version": 1,
            "fields": self.BASE_FIELDS + [{"kind": "builtin", "key": "state", "required": True,
                               "label": "S", "allowed_states": [{"label": "California"}]}],
        })
        self.assertTrue(any("allowed_states" in e["path"] for e in errs))

    def test_state_allowed_states_duplicate_codes_rejected(self):
        errs = validate_form_schema({
            "version": 1,
            "fields": self.BASE_FIELDS + [{"kind": "builtin", "key": "state", "required": True,
                               "label": "S", "allowed_states": [
                                   {"code": "CA", "label": "California"},
                                   {"code": "CA", "label": "Cali"},
                               ]}],
        })
        self.assertTrue(any(
            "allowed_states" in e["path"] and "duplicate" in e["message"].lower()
            for e in errs
        ))

    def test_state_allowed_states_empty_is_valid(self):
        """Empty list → consumer falls back to default 51."""
        errs = validate_form_schema({
            "version": 1,
            "fields": self.BASE_FIELDS + [{"kind": "builtin", "key": "state", "required": True,
                               "label": "S", "allowed_states": []}],
        })
        self.assertEqual(errs, [])


class CustomShapeTests(SimpleTestCase):
    BASE_FIELDS = [
        {"kind": "builtin", "key": "first_name", "required": True, "label": "F"},
        {"kind": "builtin", "key": "last_name", "required": True, "label": "L"},
        {"kind": "builtin", "key": "email", "required": True, "label": "E"},
    ]

    def test_custom_key_must_match_regex(self):
        errs = validate_form_schema({
            "version": 1,
            "fields": self.BASE_FIELDS + [{
                "kind": "custom", "key": "Bad-Key!", "type": "text",
                "required": False, "label": "x",
            }],
        })
        self.assertTrue(any("key" in e["path"] for e in errs))

    def test_custom_key_must_be_unique(self):
        errs = validate_form_schema({
            "version": 1,
            "fields": self.BASE_FIELDS + [
                {"kind": "custom", "key": "why", "type": "text", "required": False, "label": "x"},
                {"kind": "custom", "key": "why", "type": "text", "required": False, "label": "y"},
            ],
        })
        self.assertTrue(any("duplicate" in e["message"].lower() for e in errs))

    def test_custom_key_cannot_collide_with_builtin(self):
        errs = validate_form_schema({
            "version": 1,
            "fields": self.BASE_FIELDS + [{
                "kind": "custom", "key": "phone", "type": "text",
                "required": False, "label": "x",
            }],
        })
        self.assertTrue(any(
            "collides" in e["message"].lower() or "builtin" in e["message"].lower()
            for e in errs
        ))

    def test_custom_key_cannot_collide_with_reserved_name(self):
        errs = validate_form_schema({
            "version": 1,
            "fields": self.BASE_FIELDS + [{
                "kind": "custom", "key": "submission_code_input", "type": "text",
                "required": False, "label": "x",
            }],
        })
        self.assertTrue(any("reserved" in e["message"].lower() for e in errs))

    def test_custom_type_must_be_known(self):
        errs = validate_form_schema({
            "version": 1,
            "fields": self.BASE_FIELDS + [{
                "kind": "custom", "key": "x", "type": "money",
                "required": False, "label": "x",
            }],
        })
        self.assertTrue(any("money" in e["message"] for e in errs))

    def test_select_requires_at_least_two_options(self):
        errs = validate_form_schema({
            "version": 1,
            "fields": self.BASE_FIELDS + [{
                "kind": "custom", "key": "size", "type": "select",
                "required": True, "label": "x",
                "options": [{"value": "s", "label": "S"}],
            }],
        })
        self.assertTrue(any("options" in e["path"] for e in errs))

    def test_select_options_must_have_unique_values(self):
        errs = validate_form_schema({
            "version": 1,
            "fields": self.BASE_FIELDS + [{
                "kind": "custom", "key": "size", "type": "select",
                "required": True, "label": "x",
                "options": [{"value": "s", "label": "S"}, {"value": "s", "label": "Same"}],
            }],
        })
        self.assertTrue(any(
            "options" in e["path"] and "duplicate" in e["message"].lower()
            for e in errs
        ))

    def test_file_max_size_mb_too_high_rejected(self):
        errs = validate_form_schema({
            "version": 1,
            "fields": self.BASE_FIELDS + [{
                "kind": "custom", "key": "f", "type": "file",
                "required": False, "label": "x", "max_size_mb": 51,
            }],
        })
        self.assertTrue(any("max_size_mb" in e["path"] for e in errs))

    def test_file_max_size_mb_zero_rejected(self):
        errs = validate_form_schema({
            "version": 1,
            "fields": self.BASE_FIELDS + [{
                "kind": "custom", "key": "f", "type": "file",
                "required": False, "label": "x", "max_size_mb": 0,
            }],
        })
        self.assertTrue(any("max_size_mb" in e["path"] for e in errs))

    def test_full_example_from_spec_is_valid(self):
        errs = validate_form_schema({
            "version": 1,
            "fields": self.BASE_FIELDS + [
                {"kind": "builtin", "key": "phone", "required": True, "label": "WhatsApp"},
                {"kind": "builtin", "key": "state", "required": True, "label": "Provincia",
                 "allowed_states": [{"code": "CDMX", "label": "Ciudad de México"},
                                    {"code": "JAL", "label": "Jalisco"}]},
                {"kind": "custom", "key": "why_you", "type": "textarea", "required": False,
                 "label": "Why?", "max_length": 600},
                {"kind": "custom", "key": "shirt_size", "type": "select", "required": True,
                 "label": "T", "options": [{"value": "s", "label": "S"},
                                           {"value": "m", "label": "M"}]},
                {"kind": "custom", "key": "age_gate", "type": "checkbox", "required": True,
                 "label": "18+"},
                {"kind": "custom", "key": "extra_receipt", "type": "file", "required": False,
                 "label": "Second", "accept": "image/*", "max_size_mb": 10},
            ],
        })
        self.assertEqual(errs, [])
