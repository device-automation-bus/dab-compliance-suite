import jsons
from dataclasses import dataclass

@dataclass
class TestResult:
    device_id: str
    operation: str
    request: str
    outcome: str
    response: str

@dataclass
class TestSuite:
    test_result_list: list[TestResult]
    suite_name: str