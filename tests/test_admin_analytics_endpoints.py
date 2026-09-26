"""
test_admin_analytics_endpoints.py

Smoke test for the admin & analytics endpoints built on top of the existing
modules: departments/employees roster, the journey/interaction/purchase/feedback
list endpoints, the points ledger, the analytics aggregations and active calls.

Same shape as test_endpoints.py on purpose: a live-server script rather than a
pytest fixture soup, because the two things it needs most cannot be created
through the API — departments and employees are admin-seeded org data with no
create endpoint. Set the two department ids below; every other row is created
here through the API itself.

Run with the backend already running:
    uvicorn app.main:app --reload

Then in another terminal:
    python tests/test_admin_analytics_endpoints.py

Requires: pip install requests

Side effects: this script creates a customer, a campaign, a journey, its
interactions, a purchase and feedback, and awards points. It does not clean up
after itself — same as test_endpoints.py. It also requires the two employee_points
columns from docs/schema-changes.sql to have been applied to the database.
"""

import sys
import uuid
from datetime import datetime, timedelta, timezone

import requests

BASE_URL = "http://127.0.0.1:8000"

# ---- The data this script cannot create via API ----
# Both departments must have at least one is_online = true employee: the script
# reads the employee ids from /available-employees, which only considers online
# employees.
#   SELECT department_id, name FROM departments;
DEPARTMENT_ID = "11111111-1111-1111-1111-111111111111"  # e.g. Sales

# The transfer target, which must also have at least one online employee — the
# transfer is assigned by /available-employees, exactly like a fresh call.
SECOND_DEPARTMENT_ID = "22222222-2222-2222-2222-222222222222"  # e.g. Electronics

NONEXISTENT_ID = "99999999-9999-9999-9999-999999999999"

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

results = []


def check(name, condition, detail=""):
    status = PASS if condition else FAIL
    results.append((name, status, detail))
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and status == FAIL else ""))


def skip(name, detail=""):
    results.append((name, SKIP, detail))
    print(f"[{SKIP}] {name}" + (f" -- {detail}" if detail else ""))


def get(path, params=None, **kwargs):
    """
    GET a path with query parameters.

    Always pass a params dict rather than interpolating into the URL: an ISO
    datetime carries a ``+00:00`` offset, and a bare ``+`` in a query string
    decodes as a space, which turns a valid timestamp into a 400.
    """
    return requests.get(f"{BASE_URL}{path}", params=params, **kwargs)


def post(path, **kwargs):
    return requests.post(f"{BASE_URL}{path}", **kwargs)


def error_shape(response):
    """Every error must be {"error": ..., "message": ...}, never a traceback."""
    try:
        body = response.json()
    except ValueError:
        return False

    return (
        isinstance(body, dict)
        and set(body) == {"error", "message"}
        and all(isinstance(value, str) and value for value in body.values())
    )


def random_contact_number():
    return "9" + str(uuid.uuid4().int)[:9]


def random_campaign_code():
    return f"ANALYTICS-{uuid.uuid4().hex[:8]}"


def available_employee(department_id):
    """The employee /available-employees would hand the next customer."""
    response = get(f"/api/v1/departments/{department_id}/available-employees")

    if response.status_code != 200:
        return None, response

    return response.json(), response


def main():
    print(f"\nRunning admin/analytics endpoint tests against {BASE_URL}\n" + "-" * 60)

    health = get("/health")
    check("GET /health returns 200", health.status_code == 200, health.text)
    if health.status_code != 200:
        print("\nBackend is not healthy. Stopping.")
        print_summary()
        return

    # ================= Step 1: departments & employees =================
    departments = get("/api/v1/departments")
    check(
        "GET /api/v1/departments returns 200",
        departments.status_code == 200,
        f"status={departments.status_code}, body={departments.text[:200]}",
    )

    department_rows = departments.json() if departments.status_code == 200 else []
    check(
        "GET /api/v1/departments returns at least one department",
        bool(department_rows),
        f"body={departments.text[:200]}",
    )
    check(
        "each department row carries department_id, name, description",
        all(
            {"department_id", "name", "description"} <= set(row)
            for row in department_rows
        ),
        f"sample={department_rows[:1]}",
    )

    single = get(f"/api/v1/departments/{DEPARTMENT_ID}")
    check(
        "GET /api/v1/departments/{id} returns the department",
        single.status_code == 200
        and single.json().get("department_id") == DEPARTMENT_ID,
        f"status={single.status_code}, body={single.text[:200]}",
    )

    unknown = get(f"/api/v1/departments/{NONEXISTENT_ID}")
    check(
        "GET /api/v1/departments/{unknown} returns 404 with the error shape",
        unknown.status_code == 404 and error_shape(unknown),
        f"status={unknown.status_code}, body={unknown.text[:200]}",
    )

    employees = get("/api/v1/employees")
    check(
        "GET /api/v1/employees returns 200",
        employees.status_code == 200,
        f"status={employees.status_code}, body={employees.text[:200]}",
    )

    employee_rows = employees.json() if employees.status_code == 200 else []
    check(
        "each employee row carries the roster fields",
        bool(employee_rows)
        and all(
            {"employee_id", "employee_code", "name", "role", "department_id", "is_online"}
            <= set(row)
            for row in employee_rows
        ),
        f"sample={employee_rows[:1]}",
    )

    in_department = get(f"/api/v1/employees?department_id={DEPARTMENT_ID}")
    check(
        "?department_id= returns only that department's employees",
        in_department.status_code == 200
        and all(
            row["department_id"] == DEPARTMENT_ID for row in in_department.json()
        ),
        f"status={in_department.status_code}, body={in_department.text[:200]}",
    )

    online = get("/api/v1/employees?is_online=true")
    check(
        "?is_online=true returns only online employees",
        online.status_code == 200
        and all(row["is_online"] is True for row in online.json()),
        f"status={online.status_code}, body={online.text[:200]}",
    )

    offline = get("/api/v1/employees", params={"is_online": "false"})
    check(
        "?is_online=false returns only offline employees",
        offline.status_code == 200
        and all(row["is_online"] is False for row in offline.json()),
        f"status={offline.status_code}, body={offline.text[:200]}",
    )

    if employee_rows:
        employee_id = employee_rows[0]["employee_id"]
        one_employee = get(f"/api/v1/employees/{employee_id}")
        check(
            "GET /api/v1/employees/{id} returns the employee",
            one_employee.status_code == 200
            and one_employee.json()["employee_id"] == employee_id,
            f"status={one_employee.status_code}, body={one_employee.text[:200]}",
        )

    unknown_employee = get(f"/api/v1/employees/{NONEXISTENT_ID}")
    check(
        "GET /api/v1/employees/{unknown} returns 404 with the error shape",
        unknown_employee.status_code == 404 and error_shape(unknown_employee),
        f"status={unknown_employee.status_code}, body={unknown_employee.text[:200]}",
    )

    unknown_filter = get(f"/api/v1/employees?department_id={NONEXISTENT_ID}")
    check(
        "?department_id={unknown} returns an empty list, not an error",
        unknown_filter.status_code == 200 and unknown_filter.json() == [],
        f"status={unknown_filter.status_code}, body={unknown_filter.text[:200]}",
    )

    # ================= Step 2: list + filter =================
    customer = post(
        "/api/v1/customers",
        json={
            "contact_number": random_contact_number(),
            "age_group": "26-35",
            "occupation": "Analytics Tester",
            "previous_customer": False,
        },
    )
    customer_id = customer.json().get("customer_id") if customer.status_code == 201 else None
    check(
        "POST /api/v1/customers creates the customer this run needs (201)",
        customer.status_code == 201 and bool(customer_id),
        f"status={customer.status_code}, body={customer.text[:200]}",
    )

    campaign = post(
        "/api/v1/campaigns",
        json={
            "campaign_code": random_campaign_code(),
            "name": "Analytics Test Campaign",
            "campaign_team": "Analytics",
        },
    )
    campaign_id = campaign.json().get("campaign_id") if campaign.status_code == 201 else None
    check(
        "POST /api/v1/campaigns creates the campaign this run needs (201)",
        campaign.status_code == 201 and bool(campaign_id),
        f"status={campaign.status_code}, body={campaign.text[:200]}",
    )

    if not customer_id:
        print("\nCannot continue without a customer_id. Stopping early.")
        print_summary()
        return

    journey = post(
        "/api/v1/journeys",
        json={"customer_id": customer_id, "campaign_id": campaign_id},
    )
    journey_id = journey.json().get("journey_id") if journey.status_code == 201 else None
    check(
        "POST /api/v1/journeys starts the journey this run needs (201)",
        journey.status_code == 201 and bool(journey_id),
        f"status={journey.status_code}, body={journey.text[:200]}",
    )

    if not journey_id:
        print("\nCannot continue without a journey_id. Stopping early.")
        print_summary()
        return

    first_employee, available_response = available_employee(DEPARTMENT_ID)
    check(
        "GET /api/v1/departments/{id}/available-employees still works",
        first_employee is not None,
        f"status={available_response.status_code}, body={available_response.text[:200]}",
    )

    if first_employee is None:
        print(
            f"\nNo online employee in {DEPARTMENT_ID}. Set DEPARTMENT_ID to a "
            "department that has one, then re-run."
        )
        print_summary()
        return

    interaction = post(
        f"/api/v1/journeys/{journey_id}/interactions",
        json={
            "employee_id": first_employee["employee_id"],
            "department_id": first_employee["department_id"],
        },
    )
    interaction_id = (
        interaction.json().get("interaction_id")
        if interaction.status_code == 201
        else None
    )
    check(
        "POST /api/v1/journeys/{id}/interactions starts the interaction (201)",
        interaction.status_code == 201 and bool(interaction_id),
        f"status={interaction.status_code}, body={interaction.text[:200]}",
    )

    receiving_employee = None
    receiving_interaction_id = None

    if SECOND_DEPARTMENT_ID:
        transfer = post(
            f"/api/v1/interactions/{interaction_id}/transfer",
            json={"department_id": SECOND_DEPARTMENT_ID},
        )
        if transfer.status_code == 200:
            receiving_employee = {
                "employee_id": transfer.json()["new_employee_id"],
                "department_id": SECOND_DEPARTMENT_ID,
            }
            receiving_interaction_id = transfer.json()["new_interaction_id"]
        check(
            "POST /api/v1/interactions/{id}/transfer hands off to the second department",
            transfer.status_code == 200,
            f"status={transfer.status_code}, body={transfer.text[:200]}",
        )

        if receiving_interaction_id:
            ended = post(f"/api/v1/interactions/{receiving_interaction_id}/end")
            check(
                "the receiving interaction can be ended",
                ended.status_code == 200,
                f"status={ended.status_code}, body={ended.text[:200]}",
            )
    else:
        skip(
            "transfer hand-off",
            "SECOND_DEPARTMENT_ID is not set; set it to cover the "
            "feedback-after-transfer attribution case",
        )

    # ---- journeys list ----
    by_customer = get(f"/api/v1/journeys?customer_id={customer_id}")
    check(
        "GET /api/v1/journeys?customer_id= returns this customer's journeys",
        by_customer.status_code == 200
        and any(row["journey_id"] == journey_id for row in by_customer.json()),
        f"status={by_customer.status_code}, body={by_customer.text[:200]}",
    )

    if campaign_id:
        by_campaign = get(f"/api/v1/journeys?campaign_id={campaign_id}")
        check(
            "GET /api/v1/journeys?campaign_id= returns this campaign's journeys",
            by_campaign.status_code == 200
            and any(row["journey_id"] == journey_id for row in by_campaign.json()),
            f"status={by_campaign.status_code}, body={by_campaign.text[:200]}",
        )

    by_status = get("/api/v1/journeys?status=active")
    check(
        "GET /api/v1/journeys?status=active returns only active journeys",
        by_status.status_code == 200
        and all(row["status"] == "active" for row in by_status.json()),
        f"status={by_status.status_code}, body={by_status.text[:200]}",
    )

    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    long_ago = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    longer_ago = (datetime.now(timezone.utc) - timedelta(days=300)).isoformat()

    in_window = get(
        "/api/v1/journeys",
        params={"started_after": yesterday, "started_before": tomorrow},
    )
    check(
        "GET /api/v1/journeys with a date range includes today's journey",
        in_window.status_code == 200
        and any(row["journey_id"] == journey_id for row in in_window.json()),
        f"status={in_window.status_code}, body={in_window.text[:200]}",
    )

    out_of_window = get(
        "/api/v1/journeys",
        params={"started_after": long_ago, "started_before": longer_ago},
    )
    check(
        "GET /api/v1/journeys with a past date range excludes today's journey",
        out_of_window.status_code == 200
        and all(row["journey_id"] != journey_id for row in out_of_window.json()),
        f"status={out_of_window.status_code}, body={out_of_window.text[:200]}",
    )

    limited = get("/api/v1/journeys", params={"limit": 2})
    check(
        "?limit=2 returns at most 2 journeys",
        limited.status_code == 200 and len(limited.json()) <= 2,
        f"status={limited.status_code}, count={len(limited.json()) if limited.status_code == 200 else 'n/a'}",
    )

    offset = get("/api/v1/journeys", params={"limit": 2, "offset": 2})
    check(
        "?limit=2&offset=2 returns a different page",
        offset.status_code == 200
        and [
            row["journey_id"] for row in offset.json()
        ] != [row["journey_id"] for row in limited.json()],
        f"status={offset.status_code}, body={offset.text[:200]}",
    )

    too_big = get("/api/v1/journeys", params={"limit": 100000})
    check(
        "?limit above the maximum is rejected with the error shape",
        too_big.status_code == 400 and error_shape(too_big),
        f"status={too_big.status_code}, body={too_big.text[:200]}",
    )

    unknown_customer = get(
        "/api/v1/journeys", params={"customer_id": NONEXISTENT_ID}
    )
    check(
        "?customer_id={unknown} returns an empty list, not an error",
        unknown_customer.status_code == 200 and unknown_customer.json() == [],
        f"status={unknown_customer.status_code}, body={unknown_customer.text[:200]}",
    )

    # ---- interactions list ----
    by_employee = get(f"/api/v1/interactions?employee_id={first_employee['employee_id']}")
    check(
        "GET /api/v1/interactions?employee_id= returns the employee's history",
        by_employee.status_code == 200
        and any(row["interaction_id"] == interaction_id for row in by_employee.json()),
        f"status={by_employee.status_code}, body={by_employee.text[:200]}",
    )

    by_journey = get(f"/api/v1/interactions?journey_id={journey_id}")
    check(
        "GET /api/v1/interactions?journey_id= returns every interaction of the journey",
        by_journey.status_code == 200
        and len(by_journey.json()) >= (2 if receiving_interaction_id else 1),
        f"status={by_journey.status_code}, body={by_journey.text[:200]}",
    )

    if receiving_interaction_id:
        receiver_history = get(
            f"/api/v1/interactions?employee_id={receiving_employee['employee_id']}"
        )
        check(
            "the receiving employee's history contains the transferred-to interaction",
            receiver_history.status_code == 200
            and any(
                row["interaction_id"] == receiving_interaction_id
                for row in receiver_history.json()
            ),
            f"status={receiver_history.status_code}, body={receiver_history.text[:200]}",
        )

        sender_history = get(
            "/api/v1/interactions"
            f"?employee_id={first_employee['employee_id']}"
            f"&department_id={first_employee['department_id']}"
        )
        check(
            "the transferring employee's history does not contain the successor interaction",
            sender_history.status_code == 200
            and all(
                row["interaction_id"] != receiving_interaction_id
                for row in sender_history.json()
            ),
            f"status={sender_history.status_code}, body={sender_history.text[:200]}",
        )

    unknown_interactions = get(f"/api/v1/interactions?employee_id={NONEXISTENT_ID}")
    check(
        "?employee_id={unknown} returns an empty list, not an error",
        unknown_interactions.status_code == 200 and unknown_interactions.json() == [],
        f"status={unknown_interactions.status_code}, body={unknown_interactions.text[:200]}",
    )

    # ---- purchase, then the purchases list ----
    product_category = f"Analytics-{uuid.uuid4().hex[:6]}"
    purchase = post(
        f"/api/v1/journeys/{journey_id}/purchase",
        json={"product_category": product_category, "amount": "1234.50"},
    )
    purchase_id = (
        purchase.json().get("purchase_id") if purchase.status_code == 201 else None
    )
    check(
        "POST /api/v1/journeys/{id}/purchase records the purchase (201)",
        purchase.status_code == 201 and bool(purchase_id),
        f"status={purchase.status_code}, body={purchase.text[:200]}",
    )

    by_category = get(f"/api/v1/purchases?product_category={product_category}")
    check(
        "GET /api/v1/purchases?product_category= returns the purchase",
        by_category.status_code == 200
        and any(row["purchase_id"] == purchase_id for row in by_category.json()),
        f"status={by_category.status_code}, body={by_category.text[:200]}",
    )

    purchases_in_window = get(
        "/api/v1/purchases",
        params={"purchased_after": yesterday, "purchased_before": tomorrow},
    )
    check(
        "GET /api/v1/purchases with a date range includes today's purchase",
        purchases_in_window.status_code == 200
        and any(row["purchase_id"] == purchase_id for row in purchases_in_window.json()),
        f"status={purchases_in_window.status_code}, body={purchases_in_window.text[:200]}",
    )

    purchases_out_of_window = get(
        "/api/v1/purchases",
        params={"purchased_after": long_ago, "purchased_before": longer_ago},
    )
    check(
        "GET /api/v1/purchases with a past date range excludes today's purchase",
        purchases_out_of_window.status_code == 200
        and all(
            row["purchase_id"] != purchase_id
            for row in purchases_out_of_window.json()
        ),
        f"status={purchases_out_of_window.status_code}, body={purchases_out_of_window.text[:200]}",
    )

    purchases_limited = get(
        "/api/v1/purchases",
        params={"product_category": product_category, "limit": 2},
    )
    check(
        "GET /api/v1/purchases honours ?limit=",
        purchases_limited.status_code == 200 and len(purchases_limited.json()) <= 2,
        f"status={purchases_limited.status_code}, body={purchases_limited.text[:200]}",
    )

    # ================= Step 3: feedback attribution =================
    feedback = post(
        f"/api/v1/journeys/{journey_id}/feedback",
        json={"overall_rating": 5, "employee_rating": 5, "department_rating": 4},
    )
    feedback_id = (
        feedback.json().get("feedback_id") if feedback.status_code == 201 else None
    )
    check(
        "POST /api/v1/journeys/{id}/feedback records the feedback (201)",
        feedback.status_code == 201 and bool(feedback_id),
        f"status={feedback.status_code}, body={feedback.text[:200]}",
    )

    check(
        "the feedback row is attributed to the employee the journey ended with",
        feedback.status_code == 201
        and feedback.json().get("employee_id")
        == (receiving_employee or first_employee)["employee_id"],
        f"body={feedback.text[:200]}",
    )

    attributed_to_receiver = get(
        "/api/v1/feedback"
        f"?employee_id={(receiving_employee or first_employee)['employee_id']}"
    )
    check(
        "GET /api/v1/feedback?employee_id=<last employee> contains the feedback",
        attributed_to_receiver.status_code == 200
        and any(
            row["feedback_id"] == feedback_id for row in attributed_to_receiver.json()
        ),
        f"status={attributed_to_receiver.status_code}, body={attributed_to_receiver.text[:200]}",
    )

    if receiving_employee:
        attributed_to_sender = get(
            f"/api/v1/feedback?employee_id={first_employee['employee_id']}"
        )
        check(
            "GET /api/v1/feedback?employee_id=<transferring employee> excludes it",
            attributed_to_sender.status_code == 200
            and all(
                row["feedback_id"] != feedback_id
                for row in attributed_to_sender.json()
            ),
            f"status={attributed_to_sender.status_code}, body={attributed_to_sender.text[:200]}",
        )

    unknown_feedback = get(f"/api/v1/feedback?employee_id={NONEXISTENT_ID}")
    check(
        "?employee_id={unknown} returns an empty list, not an error",
        unknown_feedback.status_code == 200 and unknown_feedback.json() == [],
        f"status={unknown_feedback.status_code}, body={unknown_feedback.text[:200]}",
    )

    by_department = get("/api/v1/analytics/feedback/by-department")
    department_rows_by_rating = (
        {row["department_id"]: row for row in by_department.json()}
        if by_department.status_code == 200
        else {}
    )
    rated_department = (receiving_employee or first_employee)["department_id"]
    check(
        "GET /api/v1/analytics/feedback/by-department returns computed averages",
        by_department.status_code == 200
        and rated_department in department_rows_by_rating
        and department_rows_by_rating[rated_department]["feedback_count"] >= 1
        and department_rows_by_rating[rated_department]["average_overall_rating"] is not None,
        f"status={by_department.status_code}, body={by_department.text[:300]}",
    )

    by_employee_ratings = get("/api/v1/analytics/feedback/by-employee")
    employee_rows_by_rating = (
        {row["employee_id"]: row for row in by_employee_ratings.json()}
        if by_employee_ratings.status_code == 200
        else {}
    )
    rated_employee = (receiving_employee or first_employee)["employee_id"]
    check(
        "GET /api/v1/analytics/feedback/by-employee returns computed averages",
        by_employee_ratings.status_code == 200
        and rated_employee in employee_rows_by_rating
        and employee_rows_by_rating[rated_employee]["average_employee_rating"] is not None,
        f"status={by_employee_ratings.status_code}, body={by_employee_ratings.text[:300]}",
    )

    # ================= Step 4: points ledger =================
    ledger = get(f"/api/v1/employees/{first_employee['employee_id']}/points/history")
    check(
        "GET /employees/{id}/points/history returns 200",
        ledger.status_code == 200,
        f"status={ledger.status_code}, body={ledger.text[:200]}",
    )

    entries = ledger.json() if ledger.status_code == 200 else []
    check(
        "ledger entries carry a structured reason_code",
        bool(entries) and all("reason_code" in entry for entry in entries),
        f"sample={entries[:1]}",
    )

    reason_codes = {entry["reason_code"] for entry in entries}
    check(
        "this journey left distinct purchase + interaction rows in the ledger",
        {"purchase", "interaction"} <= reason_codes,
        f"reason_codes={sorted(code for code in reason_codes if code)}",
    )

    if SECOND_DEPARTMENT_ID and receiving_interaction_id:
        check(
            "the transferring employee earned a transfer row",
            "transfer" in reason_codes,
            f"reason_codes={sorted(code for code in reason_codes if code)}",
        )

    receiver_ledger = get(
        f"/api/v1/employees/{rated_employee}/points/history"
    )
    check(
        "the receiving employee's ledger contains a rating row",
        receiver_ledger.status_code == 200
        and "rating"
        in {entry["reason_code"] for entry in receiver_ledger.json()},
        f"status={receiver_ledger.status_code}, body={receiver_ledger.text[:300]}",
    )

    totals = get(f"/api/v1/employees/{first_employee['employee_id']}/points")
    ledger_sum = sum(entry["points"] for entry in entries)
    check(
        "the ledger sum equals the reported total_points",
        totals.status_code == 200
        and ledger_sum == totals.json().get("total_points"),
        f"ledger_sum={ledger_sum}, total={totals.text[:120]}",
    )

    unknown_points = get(f"/api/v1/employees/{NONEXISTENT_ID}/points")
    check(
        "points for an unknown employee return 404 with the error shape",
        unknown_points.status_code == 404 and error_shape(unknown_points),
        f"status={unknown_points.status_code}, body={unknown_points.text[:200]}",
    )

    # ================= Step 5: analytics aggregation =================
    overview = get("/api/v1/analytics/overview")
    check(
        "GET /api/v1/analytics/overview returns the expected keys",
        overview.status_code == 200
        and {
            "active_employees",
            "active_calls",
            "purchases_today",
            "revenue_today",
            "points_awarded_today",
        }
        <= set(overview.json()),
        f"status={overview.status_code}, body={overview.text[:300]}",
    )

    if overview.status_code == 200:
        metrics = overview.json()
        check(
            "overview counts today's purchase and its revenue",
            metrics["purchases_today"] >= 1 and metrics["revenue_today"] >= 1234.50,
            f"metrics={metrics}",
        )
        check(
            "overview's active call count matches /api/v1/calls/active",
            metrics["active_calls"] == len(get("/api/v1/calls/active").json()),
            f"overview={metrics['active_calls']}",
        )

    leaderboard = get("/api/v1/analytics/employees/leaderboard")
    check(
        "GET /api/v1/analytics/employees/leaderboard returns 200",
        leaderboard.status_code == 200,
        f"status={leaderboard.status_code}, body={leaderboard.text[:200]}",
    )

    if leaderboard.status_code == 200:
        board = leaderboard.json()
        points_order = [row["total_points"] for row in board]
        check(
            "the leaderboard is sorted by total_points descending",
            points_order == sorted(points_order, reverse=True),
            f"order={points_order[:20]}",
        )
        check(
            "leaderboard ranks start at 1 and never decrease",
            bool(board)
            and board[0]["rank"] == 1
            and all(
                earlier["rank"] <= later["rank"]
                for earlier, later in zip(board, board[1:])
            ),
            f"ranks={[row['rank'] for row in board][:20]}",
        )

        board_row = next(
            (row for row in board if row["employee_id"] == first_employee["employee_id"]),
            None,
        )
        check(
            "the leaderboard total matches the employee's points endpoint",
            board_row is not None
            and totals.status_code == 200
            and board_row["total_points"] == totals.json()["total_points"],
            f"board_row={board_row}, total={totals.text[:120]}",
        )

    performance = get(
        f"/api/v1/analytics/employees/{first_employee['employee_id']}/performance"
    )
    check(
        "GET /api/v1/analytics/employees/{id}/performance returns 200",
        performance.status_code == 200,
        f"status={performance.status_code}, body={performance.text[:200]}",
    )

    if performance.status_code == 200:
        stats = performance.json()
        check(
            "performance numbers are internally consistent",
            stats["interaction_count"] >= 1
            and stats["journeys_touched"] >= 1
            and stats["journeys_purchased"] <= stats["journeys_touched"]
            and abs(
                stats["conversion_rate"]
                - round(stats["journeys_purchased"] / stats["journeys_touched"], 4)
            )
            <= 0.0001,
            f"stats={stats}",
        )

    unknown_performance = get(
        f"/api/v1/analytics/employees/{NONEXISTENT_ID}/performance"
    )
    check(
        "performance for an unknown employee returns 404 with the error shape",
        unknown_performance.status_code == 404 and error_shape(unknown_performance),
        f"status={unknown_performance.status_code}, body={unknown_performance.text[:200]}",
    )

    transfers = get("/api/v1/analytics/transfers")
    check(
        "GET /api/v1/analytics/transfers returns 200",
        transfers.status_code == 200,
        f"status={transfers.status_code}, body={transfers.text[:200]}",
    )

    if SECOND_DEPARTMENT_ID and transfers.status_code == 200:
        paths = transfers.json()
        expected_pair = (
            first_employee["department_id"],
            SECOND_DEPARTMENT_ID,
        )
        check(
            "the transfer this run made appears as a from/to pair",
            any(
                (row["from_department_id"], row["to_department_id"]) == expected_pair
                and row["transfer_count"] >= 1
                for row in paths
            ),
            f"paths={paths[:5]}",
        )

    if campaign_id:
        # Seed the funnel in order, so the four stages are comparable: three
        # impressions, two clicks, one journey (created above), one purchase.
        for _ in range(3):
            post(f"/api/v1/campaigns/{campaign_id}/events", json={"event_type": "impression"})
        for _ in range(2):
            post(f"/api/v1/campaigns/{campaign_id}/events", json={"event_type": "click"})

        funnel = get(f"/api/v1/analytics/campaigns/{campaign_id}/funnel")
        check(
            "GET /analytics/campaigns/{id}/funnel returns the expected keys",
            funnel.status_code == 200
            and {
                "impressions",
                "clicks",
                "landings",
                "leads",
                "journeys",
                "purchases",
            }
            <= set(funnel.json()),
            f"status={funnel.status_code}, body={funnel.text[:300]}",
        )

        if funnel.status_code == 200:
            stages = funnel.json()
            check(
                "the funnel is non-increasing for data recorded in order",
                stages["impressions"] >= stages["clicks"] >= stages["journeys"]
                >= stages["purchases"],
                f"stages={stages} (the schema does not enforce this ordering - "
                "the check only holds for seeded-in-order data)",
            )

        unknown_funnel = get(f"/api/v1/analytics/campaigns/{NONEXISTENT_ID}/funnel")
        check(
            "a funnel for an unknown campaign returns 404 with the error shape",
            unknown_funnel.status_code == 404 and error_shape(unknown_funnel),
            f"status={unknown_funnel.status_code}, body={unknown_funnel.text[:200]}",
        )

    # ================= Step 6: active calls =================
    active_calls = get("/api/v1/calls/active")
    check(
        "GET /api/v1/calls/active returns 200 and a list",
        active_calls.status_code == 200 and isinstance(active_calls.json(), list),
        f"status={active_calls.status_code}, body={active_calls.text[:200]}",
    )

    if active_calls.status_code == 200:
        check(
            "each active call carries the dashboard's fields",
            all(
                {"call_id", "state", "started_at", "transfer_in_progress"} <= set(call)
                and call["state"] in ("waiting", "ready")
                for call in active_calls.json()
            ),
            f"body={active_calls.text[:300]}",
        )

    print_summary(
        "Run with two WebRTC clients connected to see /api/v1/calls/active "
        "return a row (scripts/webrtc_test.html)."
    )


def print_summary(hint=""):
    print("-" * 60)
    total = len(results)
    passed = sum(1 for _, status, _ in results if status == PASS)
    skipped = sum(1 for _, status, _ in results if status == SKIP)
    failed = total - passed - skipped
    print(f"Total: {total}  Passed: {passed}  Skipped: {skipped}  Failed: {failed}")

    if failed:
        print("\nFailed checks:")
        for name, status, detail in results:
            if status == FAIL:
                print(f"  - {name}\n      {detail}")
        sys.exit(1)

    if skipped:
        print("\nSkipped checks:")
        for name, status, detail in results:
            if status == SKIP:
                print(f"  - {name}\n      {detail}")

    if hint:
        print(f"\nNote: {hint}")

    print("\nAll checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except requests.exceptions.ConnectionError:
        print(f"\nCould not connect to {BASE_URL}. Is the backend running? (uvicorn app.main:app --reload)")
        sys.exit(2)
