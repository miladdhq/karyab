from datetime import datetime, timedelta, timezone

from karyab.auto import AutoState, Decision, next_action, plan_cycle

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


def _cfg(cap=8, threshold=55.0):
    from dataclasses import replace

    from karyab.config import Config
    return replace(Config.default(), daily_cap=cap, threshold=threshold)


def _c(pid, value=70.0, token=3, draft=""):
    return {"project_id": pid, "value": value, "token": token, "title": f"p{pid}",
            "rejected": False, "draft": draft, "slug": f"s{pid}", "reasons": []}


# --- the cap is a hard stop, not a suggestion ------------------------------

def test_auto_stops_at_the_daily_cap():
    plan = plan_cycle([_c(1), _c(2)], _cfg(cap=2), spent_today=2, now=NOW)
    assert plan.decision is Decision.CAP_REACHED
    assert plan.candidates == []


def test_auto_only_plans_up_to_the_remaining_cap():
    plan = plan_cycle([_c(1), _c(2), _c(3)], _cfg(cap=3), spent_today=2, now=NOW)
    assert len(plan.candidates) == 1, "one bid of headroom means one candidate"


def test_below_threshold_projects_are_never_auto_proposed():
    plan = plan_cycle([_c(1, value=40.0)], _cfg(threshold=55.0), spent_today=0, now=NOW)
    assert plan.candidates == []
    assert plan.decision is Decision.NOTHING_TO_DO


def test_a_project_already_drafted_is_still_offered():
    plan = plan_cycle([_c(1, draft="سلام")], _cfg(), spent_today=0, now=NOW)
    assert [c["project_id"] for c in plan.candidates] == [1]


def test_candidates_come_highest_scoring_first():
    plan = plan_cycle([_c(1, value=60.0), _c(2, value=90.0)], _cfg(), spent_today=0, now=NOW)
    assert [c["project_id"] for c in plan.candidates] == [2, 1]


# --- approval is mandatory and per-bid --------------------------------------

def test_auto_never_returns_submit_without_an_approval():
    state = AutoState(enabled=True, approved={}, last_scan=None)
    action = next_action(state, [_c(1)], _cfg(), spent_today=0, now=NOW)
    assert action.kind != "submit", "a bid must never be sent unapproved"
    assert action.kind == "await_approval"
    assert action.project_id == 1


def test_an_approval_covers_only_the_project_it_was_given_for():
    state = AutoState(enabled=True, approved={1: "متن تایید شده"}, last_scan=NOW)
    action = next_action(state, [_c(2)], _cfg(), spent_today=0, now=NOW)
    assert action.kind == "await_approval"
    assert action.project_id == 2, "approving one project must not approve another"


def test_an_approved_project_becomes_submittable_with_its_approved_text():
    state = AutoState(enabled=True, approved={1: "متن تایید شده"}, last_scan=NOW)
    action = next_action(state, [_c(1)], _cfg(), spent_today=0, now=NOW)
    assert action.kind == "submit"
    assert action.text == "متن تایید شده"


def test_the_submitted_text_is_what_was_approved_not_what_was_drafted():
    # The user edits in the approval dialog; the edit is what must be sent.
    state = AutoState(enabled=True, approved={1: "ویرایش شده"}, last_scan=NOW)
    action = next_action(state, [_c(1, draft="پیش‌نویس اصلی")], _cfg(),
                         spent_today=0, now=NOW)
    assert action.text == "ویرایش شده"


def test_disabling_auto_stops_everything_even_with_approvals_pending():
    state = AutoState(enabled=False, approved={1: "متن"}, last_scan=NOW)
    action = next_action(state, [_c(1)], _cfg(), spent_today=0, now=NOW)
    assert action.kind == "idle"


def test_reaching_the_cap_overrides_a_standing_approval():
    state = AutoState(enabled=True, approved={1: "متن"}, last_scan=NOW)
    action = next_action(state, [_c(1)], _cfg(cap=1), spent_today=1, now=NOW)
    assert action.kind == "idle", "the cap outranks an approval given earlier"


# --- scanning ---------------------------------------------------------------

def test_auto_scans_when_it_has_never_scanned():
    state = AutoState(enabled=True, approved={}, last_scan=None)
    assert next_action(state, [], _cfg(), spent_today=0, now=NOW).kind == "scan"


def test_auto_rescans_only_after_the_interval():
    cfg = _cfg()
    fresh = AutoState(enabled=True, approved={}, last_scan=NOW - timedelta(minutes=1))
    stale = AutoState(enabled=True, approved={},
                      last_scan=NOW - timedelta(seconds=cfg.poll_seconds + 60))
    assert next_action(fresh, [], cfg, spent_today=0, now=NOW).kind == "idle"
    assert next_action(stale, [], cfg, spent_today=0, now=NOW).kind == "scan"
