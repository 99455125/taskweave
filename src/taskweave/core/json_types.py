"""JSON values shared by wire and plugin contracts."""
from typing import TypeAlias, Union

JSON: TypeAlias = Union[None, bool, int, float, str, list["JSON"], dict[str, "JSON"]]
