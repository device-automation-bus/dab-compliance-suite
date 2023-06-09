import jsons
from dataclasses import dataclass

@dataclass
class TestOutcome:
    device_id: str
    operation: str
    request: str
    outcome: str
    response: str

@dataclass
class TestSuite:
    test_outcome_list: tuple[TestOutcome]
    suite_name: str