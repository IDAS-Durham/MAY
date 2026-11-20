"""Preflight report: problems and warnings found before the world build starts.

Stages report keys relative to their own config block; callers prefix them with `under`.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class Finding:
    key: str
    message: str


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


@dataclass
class PreflightReport:
    problems: List[Finding] = field(default_factory=list)
    warnings: List[Finding] = field(default_factory=list)

    def problem(self, key: str, message: str) -> None:
        self.problems.append(Finding(key, message))

    def warning(self, key: str, message: str) -> None:
        self.warnings.append(Finding(key, message))

    @property
    def has_problems(self) -> bool:
        return bool(self.problems)

    @classmethod
    def merge(cls, *reports: "PreflightReport") -> "PreflightReport":
        """New report with findings in report order, exact duplicates dropped."""
        merged = cls()
        for report in reports:
            for finding in report.problems:
                if finding not in merged.problems:
                    merged.problems.append(finding)
            for finding in report.warnings:
                if finding not in merged.warnings:
                    merged.warnings.append(finding)
        return merged

    def under(self, prefix: str, sep: str = ": ") -> "PreflightReport":
        """New report with every key prefixed: `f"{prefix}{sep}{key}"`."""
        return PreflightReport(
            problems=[self._prefixed(finding, prefix, sep) for finding in self.problems],
            warnings=[self._prefixed(finding, prefix, sep) for finding in self.warnings],
        )

    @staticmethod
    def _prefixed(finding: Finding, prefix: str, sep: str) -> Finding:
        return Finding(f"{prefix}{sep}{finding.key}", finding.message)

    def _body(self) -> str:
        sections = []
        for title, findings in (("Problems", self.problems), ("Warnings", self.warnings)):
            if findings:
                lines = [f"  {finding.key}: {finding.message}" for finding in findings]
                sections.append("\n".join([f"{title}:", *lines]))
        return "\n\n".join(sections)

    def format(self) -> str:
        if not self.problems and not self.warnings:
            return "Preflight passed."
        header = (
            f"Preflight found {_count(len(self.problems), 'problem')}, "
            f"{_count(len(self.warnings), 'warning')}."
        )
        return f"{header}\n\n{self._body()}"

    def raise_if_problems(self, error_class: type, header: str) -> None:
        """Raise `error_class(header + body)`, with `.report` set, if any problems."""
        if not self.has_problems:
            return
        error = error_class(f"{header}\n\n{self._body()}")
        error.report = self
        raise error


class PreflightError(Exception):
    def __init__(self, report: PreflightReport):
        self.report = report
        super().__init__(report.format())
