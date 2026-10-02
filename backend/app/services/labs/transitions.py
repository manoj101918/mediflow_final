"""Lab order item status rules (pure).

    ordered -> sample_collected -> result_entered -> verified -> released
                     |   ^               |
                     v   | (recollect)   +--> released        (verification off)
               sample_rejected           +--> sample_collected (sent back by a supervisor)
    ordered -> cancelled

Who may do what:
- the ordering doctor creates the order and may cancel items still `ordered`;
- lab technicians and supervisors collect, reject, enter and submit results, and cancel items
  still `ordered` (with a reason);
- with verification on, only a supervisor verifies, sends back and releases; with it off,
  whoever may enter results may also release them (result_entered -> released);
- corrections after release (amendments) follow the release rule.
"""

import enum
from collections.abc import Iterable
from dataclasses import dataclass

from app.db.models import LabItemStatus, LabOrderStatus, UserRole

S = LabItemStatus


class LabAction(enum.StrEnum):
    COLLECT = "collect"
    REJECT = "reject"
    SAVE_RESULTS = "save_results"
    SUBMIT = "submit"
    SEND_BACK = "send_back"
    VERIFY = "verify"
    RELEASE = "release"
    AMEND = "amend"
    CANCEL = "cancel"


@dataclass(frozen=True)
class Move:
    sources: frozenset[LabItemStatus]
    target: LabItemStatus


MOVES: dict[LabAction, Move] = {
    LabAction.COLLECT: Move(frozenset({S.ORDERED, S.SAMPLE_REJECTED}), S.SAMPLE_COLLECTED),
    LabAction.REJECT: Move(frozenset({S.SAMPLE_COLLECTED}), S.SAMPLE_REJECTED),
    # Draft values; the status does not change.
    LabAction.SAVE_RESULTS: Move(frozenset({S.SAMPLE_COLLECTED}), S.SAMPLE_COLLECTED),
    LabAction.SUBMIT: Move(frozenset({S.SAMPLE_COLLECTED}), S.RESULT_ENTERED),
    LabAction.SEND_BACK: Move(frozenset({S.RESULT_ENTERED, S.VERIFIED}), S.SAMPLE_COLLECTED),
    LabAction.VERIFY: Move(frozenset({S.RESULT_ENTERED}), S.VERIFIED),
    # result_entered -> released only when verification is off (see allowed_sources).
    LabAction.RELEASE: Move(frozenset({S.VERIFIED, S.RESULT_ENTERED}), S.RELEASED),
    LabAction.AMEND: Move(frozenset({S.RELEASED}), S.RELEASED),
    LabAction.CANCEL: Move(frozenset({S.ORDERED}), S.CANCELLED),
}

LAB_ROLES = frozenset({UserRole.LAB_TECHNICIAN, UserRole.LAB_SUPERVISOR})
_TECH_ACTIONS = frozenset(
    {LabAction.COLLECT, LabAction.REJECT, LabAction.SAVE_RESULTS, LabAction.SUBMIT}
)
_RELEASE_ACTIONS = frozenset({LabAction.RELEASE, LabAction.AMEND})
_SUPERVISOR_ACTIONS = frozenset({LabAction.VERIFY, LabAction.SEND_BACK})


def role_allowed(action: LabAction, role: UserRole, verification_required: bool) -> bool:
    """Whether a lab role may perform `action` (doctor cancellation is checked separately)."""
    if role not in LAB_ROLES:
        return False
    if role == UserRole.LAB_SUPERVISOR or action in _TECH_ACTIONS or action == LabAction.CANCEL:
        return True
    if action in _RELEASE_ACTIONS:
        return not verification_required
    return action not in _SUPERVISOR_ACTIONS


def allowed_sources(action: LabAction, verification_required: bool) -> frozenset[LabItemStatus]:
    sources = MOVES[action].sources
    if action == LabAction.RELEASE and verification_required:
        return sources - {S.RESULT_ENTERED}
    return sources


def can_move(action: LabAction, current: LabItemStatus, verification_required: bool) -> bool:
    return current in allowed_sources(action, verification_required)


_RELEASED_OR_DONE = frozenset({S.RELEASED, S.CANCELLED})


def derive_order_status(statuses: Iterable[LabItemStatus]) -> LabOrderStatus:
    """An order's status from its items."""
    items = list(statuses)
    live = [s for s in items if s != S.CANCELLED]
    if not live:
        return LabOrderStatus.CANCELLED
    if all(s == S.RELEASED for s in live):
        return LabOrderStatus.RELEASED
    if any(s == S.RELEASED for s in live):
        return LabOrderStatus.PARTIALLY_RELEASED
    if any(s != S.ORDERED for s in live):
        return LabOrderStatus.IN_PROGRESS
    return LabOrderStatus.ORDERED


def is_open(status: LabItemStatus) -> bool:
    return status not in _RELEASED_OR_DONE
