from enum import Enum
from packaging.version import Version, InvalidVersion


class DABVersion(Version, Enum):
    V2_0 = "2.0"
    V2_1 = "2.1"
    V2_2 = "2.2"


def _to_version(version) -> Version:
    try:
        return Version(str(version).strip())
    except InvalidVersion:
        raise ValueError(f"Incorrect version format: {version}")


def parse(version) -> Version:
    '''Returns version from str or float'''
    return _to_version(version)


def parse_array(versions) -> Version:
    '''Returns highest specified version'''
    if not versions:
        raise ValueError("Empty versions array")
    return max(_to_version(v) for v in versions)
