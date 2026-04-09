"""Normalized scanner output types — pure dataclasses, no Django deps."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class NormalizedFinding:
    rule_id: str = ''
    severity: str = 'info'
    file_path: str = ''
    line: Optional[int] = None
    message: str = ''


@dataclass
class ToolOutput:
    findings: list = field(default_factory=list)
    raw_stdout: str = ''
    raw_stderr: str = ''
    returncode: int = 0
