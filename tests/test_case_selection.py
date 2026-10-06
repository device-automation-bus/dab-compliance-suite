import unittest

import functionals.functional_helpers as helpers
from main import case_matches, is_manual_test


def _automatic_check(tester, device_id):
    return case_matches("SystemPowerModeSet", "SystemPower*")


def _prompting_check(tester, device_id):
    return helpers.yes_or_no(None, [], "Did it work?")


def _indirect_prompting_check(tester, device_id):
    return _prompting_check(tester, device_id)


def _input_check(test_result, durationInMs=0, expectedLatencyMs=0):
    return input("Did it work? ") == "y"


class CaseMatchesTests(unittest.TestCase):
    def test_exact_match(self):
        for test_id in (
            "SystemPowerModeSet",
            "AppLaunchNegativeTest",
            "InputLongKeyPressKeyDown",
            "SystemSettingsSetOutputResolution",
        ):
            with self.subTest(test_id=test_id):
                self.assertTrue(case_matches(test_id, test_id))

    def test_prefix_wildcard(self):
        cases = [
            ("SystemPowerModeSet", "SystemPower*", True),
            ("AppLaunchNegativeTest", "App*", True),
            ("InputLongKeyPressKeyDown", "Input*", True),
            ("SystemSettingsSetOutputResolution", "App*", False),
        ]
        for test_id, pattern, expected in cases:
            with self.subTest(test_id=test_id, pattern=pattern):
                self.assertEqual(case_matches(test_id, pattern), expected)

    def test_suffix_and_infix_wildcard(self):
        cases = [
            ("AppLaunchNegativeTest", "*NegativeTest", True),
            ("InputLongKeyPressKeyDown", "Input*KeyDown", True),
            ("InputLongKeyPressKeyUp", "Input*KeyDown", False),
            ("SystemSettingsSetOutputResolution", "*Set*Resolution", True),
        ]
        for test_id, pattern, expected in cases:
            with self.subTest(test_id=test_id, pattern=pattern):
                self.assertEqual(case_matches(test_id, pattern), expected)

    def test_single_character_wildcard(self):
        self.assertTrue(case_matches("SystemPowerModeSet", "SystemPower????Set"))
        self.assertFalse(case_matches("SystemPowerModeSet", "SystemPower???Set"))

    def test_character_class(self):
        self.assertTrue(case_matches("AppLaunchNegativeTest", "[AI]pp*"))
        self.assertFalse(case_matches("AppLaunchNegativeTest", "[IS]pp*"))

    def test_matching_is_case_sensitive(self):
        self.assertFalse(case_matches("SystemPowerModeSet", "systempower*"))
        self.assertFalse(case_matches("SystemPowerModeSet", "systempowermodeset"))

    def test_no_wildcard_does_not_match_substring(self):
        self.assertFalse(case_matches("SystemPowerModeSet", "SystemPower"))
        self.assertFalse(case_matches("SystemPowerModeSet", "ModeSet"))

    def test_comma_separated_patterns_select_multiple_suites(self):
        requested_cases = [c.strip() for c in "App*, Input*KeyDown".split(",")]
        listed_ids = [
            "AppLaunchNegativeTest",
            "InputLongKeyPressKeyDown",
            "InputLongKeyPressKeyUp",
            "SystemPowerModeSet",
        ]
        matched = [
            test_id
            for test_id in listed_ids
            if any(case_matches(test_id, pattern) for pattern in requested_cases)
        ]
        self.assertEqual(matched, ["AppLaunchNegativeTest", "InputLongKeyPressKeyDown"])


class IsManualTestTests(unittest.TestCase):
    def test_automatic_functional_case(self):
        self.assertFalse(is_manual_test(("topic", "functional", _automatic_check, "Auto", "2.1", False)))

    def test_functional_case_with_prompt(self):
        self.assertTrue(is_manual_test(("topic", "functional", _prompting_check, "Manual", "2.1", False)))

    def test_prompt_reached_through_helper(self):
        self.assertTrue(is_manual_test(("topic", "functional", _indirect_prompting_check, "Manual", "2.1", False)))

    def test_conformance_case_with_input(self):
        self.assertTrue(is_manual_test(("topic", "{}", _input_check, 200, "Manual", "2.1", False)))

    def test_conformance_case_without_function(self):
        self.assertFalse(is_manual_test(("topic", "{}", None, 200, "Auto", "2.1", False)))


if __name__ == "__main__":
    unittest.main()
