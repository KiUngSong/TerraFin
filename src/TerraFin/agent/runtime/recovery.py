from collections.abc import Iterable
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
        return self.record_round((fingerprint,))

    def record_round(self, fingerprints: Iterable[str | None]) -> bool:
        """Count one failing round, however many of its calls failed.

        A round is one model step's batch of tool calls. An error repeated
        within a batch counts once, so parallel calls sharing a mistake read as
        one failed attempt, not as the model failing to recover.
        """
        self.recoverable_error_rounds += 1
        distinct = {str(fingerprint or "").strip() for fingerprint in fingerprints} - {""}
        for normalized in distinct:
            self.repeated_error_counts[normalized] = self.repeated_error_counts.get(normalized, 0) + 1
        repeated = max((self.repeated_error_counts[normalized] for normalized in distinct), default=0)
        return (
            self.recoverable_error_rounds >= self.policy.max_recoverable_error_rounds
            or repeated >= self.policy.max_repeated_same_error
        )
