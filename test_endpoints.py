"""
test_endpoints.py

Self-contained smoke test for all endpoints built so far
(Modules 1-4: Health, Customers, Campaigns, Journeys, Departments/Assignment).

This version creates ALL of its own test data through the API itself
(customers, campaigns, journeys) rather than relying on pre-seeded rows,
so it works after a TRUNCATE with no reseed.

The one exception: departments and employees have no creation endpoint
in this project (they're treated as pre-existing org data, not something
customers/API clients create). So this script needs at least one real
department ID that has an online employee. Set it below.

Run with the backend already running:
    uvicorn app.main:app --reload

Then in another terminal:
    python test_endpoints.py

Requires:
    pip install requests
"""

import sys
import uuid
import requests

BASE_URL = "http://127.0.0.1:8000"

# ---- The one piece of data this script can't create via API ----
# Must be a real department_id that has at least one is_online = true employee.
# From your schema's departments table (e.g. via DBeaver):
#   SELECT department_id, name FROM departments;
# Update this if your department IDs differ.
DEPARTMENT_WITH_ONLINE_EMPLOYEE = "11111111-1111-1111-1111-111111111111"  # Sales

# IDs that should never exist, used for negative tests
NONEXISTENT_DEPARTMENT_ID = "99999999-9999-9999-9999-999999999999"
NONEXISTENT_CUSTOMER_ID = "00000000-0000-0000-0000-000000000000"
NONEXISTENT_JOURNEY_ID = "00000000-0000-0000-0000-000000000001"

PASS = "PASS"
FAIL = "FAIL"
results = []


def check(name, condition, detail=""):
    status = PASS if condition else FAIL
    results.append((name, status, detail))
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and status == FAIL else ""))


def get(path, **kwargs):
    return requests.get(f"{BASE_URL}{path}", **kwargs)


def post(path, **kwargs):
    return requests.post(f"{BASE_URL}{path}", **kwargs)


def random_contact_number():
    return "9" + str(uuid.uuid4().int)[:9]


def random_campaign_code():
    return f"TEST-{uuid.uuid4().hex[:8]}"


def main():
    print(f"\nRunning endpoint tests against {BASE_URL}\n" + "-" * 60)

    # ================= Module 1: Health =================
    r = get("/health")
    check("GET /health returns 200", r.status_code == 200, f"status={r.status_code}, body={r.text}")
    if r.status_code == 200:
        check(
            "GET /health reports database connected",
            r.json().get("database") == "connected",
            f"body={r.json()}",
        )

    # ================= Module 3: Customers =================
    # Create the customer this whole test run will use downstream.
    contact_number = random_contact_number()
    r = post(
        "/api/v1/customers",
        json={
            "contact_number": contact_number,
            "age_group": "26-35",
            "occupation": "Tester",
            "location_type": "Urban",
            "budget_range": "10000-20000",
            "interested_category": "Testing",
            "purchase_intent": "medium",
            "previous_customer": False,
        },
    )
    check(
        "POST /api/v1/customers creates a new customer (201)",
        r.status_code == 201,
        f"status={r.status_code}, body={r.text}",
    )
    customer_id = r.json().get("customer_id") if r.status_code == 201 else None
    check("Response includes a customer_id", bool(customer_id), f"body={r.text}")

    if not customer_id:
        print("\nCannot continue without a customer_id. Stopping early.")
        print_summary()
        sys.exit(1)

    # Duplicate contact number -> expect 409
    r_dup = post("/api/v1/customers", json={"contact_number": contact_number, "previous_customer": False})
    check(
        "POST /api/v1/customers with duplicate contact_number returns 409",
        r_dup.status_code == 409,
        f"status={r_dup.status_code}, body={r_dup.text}",
    )

    # GET the customer just created
    r = get(f"/api/v1/customers/{customer_id}")
    check(
        "GET /api/v1/customers/{id} returns the created customer",
        r.status_code == 200 and r.json().get("customer_id") == customer_id,
        f"status={r.status_code}, body={r.text}",
    )

    # GET a nonexistent customer -> expect 404
    r = get(f"/api/v1/customers/{NONEXISTENT_CUSTOMER_ID}")
    check(
        "GET /api/v1/customers/{unknown id} returns 404",
        r.status_code == 404,
        f"status={r.status_code}, body={r.text}",
    )

    # ================= Module 3: Campaigns =================
    campaign_code = random_campaign_code()
    r = post(
        "/api/v1/campaigns",
        json={
            "campaign_code": campaign_code,
            "name": "Automated Test Campaign",
            "department_id": DEPARTMENT_WITH_ONLINE_EMPLOYEE,
            "campaign_team": "QA Team",
        },
    )
    check(
        "POST /api/v1/campaigns creates a new campaign (201)",
        r.status_code == 201,
        f"status={r.status_code}, body={r.text}",
    )
    campaign_id = r.json().get("campaign_id") if r.status_code == 201 else None
    check("Response includes a campaign_id", bool(campaign_id), f"body={r.text}")

    # Duplicate campaign_code -> expect 409
    if campaign_id:
        r_dup = post(
            "/api/v1/campaigns",
            json={"campaign_code": campaign_code, "name": "Duplicate Attempt", "campaign_team": "QA Team"},
        )
        check(
            "POST /api/v1/campaigns with duplicate campaign_code returns 409",
            r_dup.status_code == 409,
            f"status={r_dup.status_code}, body={r_dup.text}",
        )

    r = get("/api/v1/campaigns")
    check(
        "GET /api/v1/campaigns returns a list (200)",
        r.status_code == 200 and isinstance(r.json(), list),
        f"status={r.status_code}, body={r.text}",
    )
    if r.status_code == 200 and campaign_id:
        ids = [c.get("campaign_id") for c in r.json()]
        check("GET /api/v1/campaigns list includes the newly created campaign", campaign_id in ids)

    if campaign_id:
        r = get(f"/api/v1/campaigns/{campaign_id}")
        check(
            "GET /api/v1/campaigns/{id} returns the created campaign",
            r.status_code == 200 and r.json().get("campaign_id") == campaign_id,
            f"status={r.status_code}, body={r.text}",
        )

        # Ad events on the campaign we just created
        r = post(f"/api/v1/campaigns/{campaign_id}/events", json={"customer_id": customer_id, "event_type": "click"})
        check(
            "POST /api/v1/campaigns/{id}/events records a click (201)",
            r.status_code == 201,
            f"status={r.status_code}, body={r.text}",
        )
        if r.status_code == 201:
            check(
                "Ad event response has server-attached campaign_id",
                r.json().get("campaign_id") == campaign_id,
                f"body={r.json()}",
            )

        # Invalid event_type -> expect 400
        r = post(f"/api/v1/campaigns/{campaign_id}/events", json={"customer_id": customer_id, "event_type": "bogus"})
        check(
            "POST /api/v1/campaigns/{id}/events with invalid event_type returns 400",
            r.status_code == 400,
            f"status={r.status_code}, body={r.text}",
        )

    # Event on a nonexistent campaign -> expect 404
    r = post(f"/api/v1/campaigns/{NONEXISTENT_DEPARTMENT_ID}/events", json={"event_type": "click"})
    check(
        "POST /api/v1/campaigns/{unknown id}/events returns 404",
        r.status_code == 404,
        f"status={r.status_code}, body={r.text}",
    )

    # ================= Module 4: Journeys =================
    r = post("/api/v1/journeys", json={"customer_id": customer_id, "campaign_id": campaign_id})
    check(
        "POST /api/v1/journeys starts a new journey (201)",
        r.status_code == 201,
        f"status={r.status_code}, body={r.text}",
    )
    journey_id = None
    if r.status_code == 201:
        body = r.json()
        journey_id = body.get("journey_id")
        check("Response includes journey_id", bool(journey_id), f"body={body}")
        check("New journey status is 'active'", body.get("status") == "active", f"body={body}")

    # Journey with a nonexistent customer -> expect 404
    r = post("/api/v1/journeys", json={"customer_id": NONEXISTENT_CUSTOMER_ID})
    check(
        "POST /api/v1/journeys with unknown customer_id returns 404",
        r.status_code == 404,
        f"status={r.status_code}, body={r.text}",
    )

    if journey_id:
        r = get(f"/api/v1/journeys/{journey_id}")
        check(
            "GET /api/v1/journeys/{id} returns the created journey (200)",
            r.status_code == 200,
            f"status={r.status_code}, body={r.text}",
        )
        if r.status_code == 200:
            check(
                "Journey response includes an empty interactions list",
                r.json().get("interactions") == [],
                f"body={r.json()}",
            )

    # GET a nonexistent journey -> expect 404
    r = get(f"/api/v1/journeys/{NONEXISTENT_JOURNEY_ID}")
    check(
        "GET /api/v1/journeys/{unknown id} returns 404",
        r.status_code == 404,
        f"status={r.status_code}, body={r.text}",
    )

    # ================= Module 4: Department / Employee Assignment =================
    r = get(f"/api/v1/departments/{DEPARTMENT_WITH_ONLINE_EMPLOYEE}/available-employees")
    check(
        "GET /available-employees returns an online employee (200)",
        r.status_code == 200,
        f"status={r.status_code}, body={r.text}",
    )
    if r.status_code == 200:
        check(
            "Available employee belongs to the requested department",
            r.json().get("department_id") == DEPARTMENT_WITH_ONLINE_EMPLOYEE,
            f"body={r.json()}",
        )

    # Department with no employees at all -> expect 409 EMPLOYEE_NOT_AVAILABLE
    r = get(f"/api/v1/departments/{NONEXISTENT_DEPARTMENT_ID}/available-employees")
    check(
        "GET /available-employees for unknown/empty department returns 409",
        r.status_code == 409,
        f"status={r.status_code}, body={r.text}",
    )

    # ================= Module 5: Interactions & Transfers =================
    # ================= Module 5: Interactions & Transfers =================
    # Query available employee again for the real department
    r_avail = get(f"/api/v1/departments/{DEPARTMENT_WITH_ONLINE_EMPLOYEE}/available-employees")
    if journey_id and r_avail.status_code == 200:
        available_employee_id = r_avail.json().get("employee_id")
        department_id = r_avail.json().get("department_id")

        if available_employee_id and department_id:
            # 1. Start Interaction
            r_int = post(
                f"/api/v1/journeys/{journey_id}/interactions",
                json={"employee_id": available_employee_id, "department_id": department_id},
            )
            check(
                "POST /api/v1/journeys/{id}/interactions creates an interaction (201)",
                r_int.status_code == 201,
                f"status={r_int.status_code}, body={r_int.text}",
            )
            interaction_id = None
            if r_int.status_code == 201:
                body_int = r_int.json()
                interaction_id = body_int.get("interaction_id")
                check("Response includes interaction_id", bool(interaction_id), f"body={body_int}")
                check("Interaction order is 1", body_int.get("interaction_order") == 1, f"body={body_int}")
                check("Server set started_at", bool(body_int.get("started_at")), f"body={body_int}")

            # 2. Transfer Interaction
            if interaction_id:
                r_trans = post(
                    f"/api/v1/interactions/{interaction_id}/transfer",
                    json={"department_id": department_id},
                )
                check(
                    "POST /api/v1/interactions/{id}/transfer processes the transfer (200)",
                    r_trans.status_code == 200,
                    f"status={r_trans.status_code}, body={r_trans.text}",
                )
                new_interaction_id = None
                if r_trans.status_code == 200:
                    body_trans = r_trans.json()
                    check("Transfer response indicates success", body_trans.get("transferred") is True, f"body={body_trans}")
                    new_interaction_id = body_trans.get("new_interaction_id")
                    check("Transfer response includes new_interaction_id", bool(new_interaction_id), f"body={body_trans}")

                # 3. End new Interaction
                if new_interaction_id:
                    r_end = post(f"/api/v1/interactions/{new_interaction_id}/end")
                    check(
                        "POST /api/v1/interactions/{id}/end closes the interaction (200)",
                        r_end.status_code == 200,
                        f"status={r_end.status_code}, body={r_end.text}",
                    )
                    if r_end.status_code == 200:
                        body_end = r_end.json()
                        check("End response includes calculated ended_at", bool(body_end.get("ended_at")), f"body={body_end}")
                        check("End response includes duration_seconds", body_end.get("duration_seconds") is not None, f"body={body_end}")

            # 4. Check Journey includes all interactions in order
            r_j = get(f"/api/v1/journeys/{journey_id}")
            if r_j.status_code == 200:
                interactions_list = r_j.json().get("interactions", [])
                check(
                    "GET /api/v1/journeys/{id} returns both interactions",
                    len(interactions_list) == 2,
                    f"Found {len(interactions_list)} interactions",
                )
                if len(interactions_list) == 2:
                    check("First interaction is order 1", interactions_list[0].get("interaction_order") == 1)
                    check("Second interaction is order 2", interactions_list[1].get("interaction_order") == 2)

    print_summary()


def print_summary():
    print("-" * 60)
    total = len(results)
    passed = sum(1 for _, status, _ in results if status == PASS)
    failed = total - passed
    print(f"Total: {total}  Passed: {passed}  Failed: {failed}")

    if failed:
        print("\nFailed checks:")
        for name, status, detail in results:
            if status == FAIL:
                print(f"  - {name}\n      {detail}")
        sys.exit(1)
    else:
        print("\nAll checks passed.")
        sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except requests.exceptions.ConnectionError:
        print(f"\nCould not connect to {BASE_URL}. Is the backend running? (uvicorn app.main:app --reload)")
        sys.exit(2)