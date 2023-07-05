from dataclasses import dataclass
from typing import List

@dataclass
class TestResult:
    test_id: str
    device_id: str
    operation: str
    request: str
    outcome: str
    response: str
    logs: List[str]

@dataclass
class TestSuite:
    test_result_list: List[TestResult]
    suite_name: str