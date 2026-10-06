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

    @property
    def test_result(self) -> str:
        """Alias kept in sync with 'outcome' for tests/writers using either name."""
        return self.outcome

    @test_result.setter
    def test_result(self, value: str) -> None:
        self.outcome = value

@dataclass
class TestSuite:
    test_result_list: List[TestResult]
    suite_name: str