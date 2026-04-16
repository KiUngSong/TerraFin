from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RecoveryPolicy:
    max_recoverable_error_rounds: int = 3
    max_repeated_same_error: int = 2


@dataclass(slots=True)
class RecoveryTracker:
    policy: RecoveryPolicy
    recoverable_error_rounds: int = 0
    repeated_error_counts: dict[str, int] = field(default_factory=dict)

    def record(self, fingerprint: str | None) -> bool:
        self.recoverable_error_rounds += 1
        normalized = str(fingerprint or "").strip()
        if normalized:
            self.repeated_error_counts[normalized] = self.repeated_error_counts.get(normalized, 0) + 1
        repeated = self.repeated_error_counts.get(normalized, 0) if normalized else 0
        return (
            self.recoverable_error_rounds >= self.policy.max_recoverable_error_rounds
            or repeated >= self.policy.max_repeated_same_error
        )

