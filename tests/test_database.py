"""Real SQL Server integration proof; only the explicitly named test database.

Run from shipping_booking with ``python -m pytest tests/test_database.py -v``.
Every ordinary test creates uniquely named resources. Two administrative tests use
an outer transaction and always roll back their temporary test-only changes.
No test drops or resets a database or changes the main demonstration database.
"""
import json
import os
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pyodbc
import pytest
from dotenv import dotenv_values
from werkzeug.security import generate_password_hash


ROOT = Path(__file__).resolve().parents[1]
TEST_DB = "HarborBooking_Test"


def records(cursor):
    result = []
    while True:
        if cursor.description:
            names = [column[0] for column in cursor.description]
            result = [dict(zip(names, row)) for row in cursor.fetchall()]
        if not cursor.nextset():
            return result


def execute(conn, name, **params):
    assert re.fullmatch(r"usp_[A-Za-z0-9_]+", name)
    assert all(re.fullmatch(r"[a-z_]+", key) for key in params)
    return records(conn.cursor().execute(
        "EXEC dbo." + name + " " + ",".join("@" + key + "=?" for key in params),
        tuple(params.values()),
    ))


def one(conn, sql, *params):
    cursor = conn.cursor().execute(sql, *params)
    row = cursor.fetchone()
    return dict(zip([column[0] for column in cursor.description], row)) if row else None


def expect_business_error(function):
    with pytest.raises(pyodbc.Error) as caught:
        function()
    # A timeout, missing object, or programming error must not masquerade as a
    # successful business-rule rejection.
    assert re.search(r"\((?:5\d{4}|547|2601|2627)\)", str(caught.value)), str(caught.value)
    return str(caught.value)


class Database:
    def __init__(self, connection_string):
        self.connection_string = connection_string
        with self.app() as conn:
            assert conn.execute("SELECT DB_NAME()").fetchone()[0] == TEST_DB
            self.users = {row.username: row.user_id for row in conn.execute(
                "SELECT username,user_id FROM dbo.v_Users WHERE username IN ('admin','sales','sales2','reviewer','analyst')"
            )}
            assert len(self.users) == 5, "Test database must contain the demonstration accounts."
            self.customer = conn.execute("SELECT TOP (1) customer_id FROM dbo.v_Customers WHERE is_active=1 ORDER BY customer_id").fetchone()[0]
            self.vessel = conn.execute("SELECT TOP (1) vessel_id FROM dbo.v_Vessels WHERE is_active=1 AND nominal_teu>=100 ORDER BY vessel_id").fetchone()[0]
            self.ports = [row[0] for row in conn.execute("SELECT TOP (2) port_id FROM dbo.v_Ports WHERE is_active=1 ORDER BY port_id")]

    def app(self):
        connection = pyodbc.connect(self.connection_string, autocommit=True, timeout=10)
        connection.timeout = 20
        return connection

    def admin(self):
        server = os.getenv("HARBOR_TEST_SQL_SERVER", "localhost").replace("}", "}}")
        connection = pyodbc.connect(
            f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={{{server}}};DATABASE={{{TEST_DB}}};Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes",
            autocommit=True, timeout=10,
        )
        assert connection.execute("SELECT DB_NAME()").fetchone()[0] == TEST_DB
        connection.timeout = 20
        return connection

    def version(self, conn, entity, identity):
        view, column = {
            "booking": ("v_Bookings", "booking_id"),
            "voyage": ("v_VoyageCapacity", "voyage_id"),
            "user": ("v_Users", "user_id"),
        }[entity]
        return conn.execute(f"SELECT CONVERT(varchar(18),CONVERT(binary(8),row_version),1) FROM dbo.{view} WHERE {column}=?", identity).fetchone()[0]

    def voyage(self, teu=10, kg=40000, open_for_sale=True):
        clock = datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None, microsecond=0)
        with self.app() as conn:
            row = execute(conn, "usp_SaveVoyage", actor_id=self.users["admin"], voyage_id=None,
                voyage_no="T-" + uuid.uuid4().hex[:22], vessel_id=self.vessel,
                origin_port_id=self.ports[0], destination_port_id=self.ports[1],
                departure_at=clock + timedelta(days=30), arrival_at=clock + timedelta(days=35),
                booking_cutoff_at=clock + timedelta(days=28), saleable_teu=teu,
                saleable_gross_kg=kg, expected_version=None)[0]
            vid = row["voyage_id"]
            if open_for_sale:
                execute(conn, "usp_TransitionVoyage", actor_id=self.users["admin"], voyage_id=vid,
                    target_status="OPEN", expected_version=self.version(conn, "voyage", vid))
            return vid

    def booking(self, voyage, quantity=4, kg=12000, user="sales", items=None):
        with self.app() as conn:
            return execute(conn, "usp_SaveBookingDraft", actor_id=self.users.get(user, user), booking_id=None,
                customer_id=self.customer, voyage_id=voyage, cargo_description="自动化测试普通货物",
                remark="独立测试资源 " + uuid.uuid4().hex[:8],
                items_json=json.dumps(items if items is not None else [dict(container_type_id=1, quantity=quantity, total_gross_kg=kg)]),
                expected_version=None)[0]["booking_id"]

    def action(self, booking, action, user="sales", reason=None, expected=None, conn=None):
        if conn is None:
            with self.app() as connection:
                return self.action(booking, action, user, reason, expected, connection)
        return execute(conn, "usp_BookingAction", actor_id=self.users.get(user, user), booking_id=booking,
            action=action, reason=reason, expected_version=expected or self.version(conn, "booking", booking))

    def snapshot(self, booking):
        with self.app() as conn:
            data = one(conn, "SELECT status,total_teu,total_gross_kg,version_hex FROM dbo.v_Bookings WHERE booking_id=?", booking)
            data["history_count"] = conn.execute("SELECT COUNT(*) FROM dbo.v_BookingHistory WHERE booking_id=?", booking).fetchone()[0]
            data["audit_count"] = conn.execute("SELECT COUNT(*) FROM dbo.v_Audit WHERE entity_name='Booking' AND entity_key=?", str(booking)).fetchone()[0]
            return data


@pytest.fixture(scope="module")
def db():
    config = dotenv_values(ROOT / ".env.HarborBooking_Test.local")
    connection_string = config.get("DB_CONNECTION_STRING")
    if not connection_string:
        pytest.skip("Run setup_database.py --database HarborBooking_Test first; no test database was modified.")
    return Database(connection_string)


def test_concurrent_confirmation_cannot_oversell(db):
    """Two independent sessions compete for six remaining TEU; only one fits."""
    voyage = db.voyage(teu=10, kg=40000)
    base = db.booking(voyage)
    db.action(base, "submit")
    db.action(base, "confirm", "reviewer")
    bids = [db.booking(voyage, user=user) for user in ("sales", "sales2")]
    for bid, user in zip(bids, ("sales", "sales2")):
        db.action(bid, "submit", user)
    versions = [db.snapshot(bid)["version_hex"] for bid in bids]
    start = threading.Barrier(2)

    def confirm(index):
        with db.app() as conn:
            start.wait(timeout=10)
            try:
                db.action(bids[index], "confirm", "reviewer", expected=versions[index], conn=conn)
                return "CONFIRMED"
            except pyodbc.Error as error:
                assert re.search(r"\(5\d{4}\)", str(error)), str(error)
                return "REJECTED_BY_CAPACITY"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(confirm, (0, 1)))
    assert sorted(results) == ["CONFIRMED", "REJECTED_BY_CAPACITY"]
    assert sorted(db.snapshot(bid)["status"] for bid in bids) == ["CONFIRMED", "SUBMITTED"]
    with db.app() as conn:
        capacity = one(conn, "SELECT used_teu,used_gross_kg,remaining_teu FROM dbo.v_VoyageCapacity WHERE voyage_id=?", voyage)
    assert capacity == {"used_teu": 8, "used_gross_kg": Decimal("24000.000"), "remaining_teu": 2}


def test_weight_quota_uses_whole_line_total_and_failure_is_atomic(db):
    voyage = db.voyage(teu=100, kg=10000)
    first = db.booking(voyage, quantity=5, kg=6000)
    second = db.booking(voyage, quantity=1, kg=5000)
    for bid in (first, second):
        db.action(bid, "submit")
    db.action(first, "confirm", "reviewer")
    before = db.snapshot(second)
    expect_business_error(lambda: db.action(second, "confirm", "reviewer"))
    assert db.snapshot(second) == before
    with db.app() as conn:
        capacity = one(conn, "SELECT used_teu,used_gross_kg FROM dbo.v_VoyageCapacity WHERE voyage_id=?", voyage)
    assert capacity == {"used_teu": 5, "used_gross_kg": Decimal("6000.000")}


def test_cancel_confirmed_order_releases_capacity_and_keeps_history(db):
    voyage = db.voyage()
    bid = db.booking(voyage)
    db.action(bid, "submit")
    db.action(bid, "confirm", "reviewer")
    db.action(bid, "cancel", reason="客户改变计划")
    with db.app() as conn:
        assert conn.execute("SELECT used_teu FROM dbo.v_VoyageCapacity WHERE voyage_id=?", voyage).fetchone()[0] == 0
        transitions = [tuple(row) for row in conn.execute("SELECT from_status,to_status FROM dbo.v_BookingHistory WHERE booking_id=? ORDER BY history_id", bid)]
    assert transitions == [(None, "DRAFT"), ("DRAFT", "SUBMITTED"), ("SUBMITTED", "CONFIRMED"), ("CONFIRMED", "CANCELLED")]


def test_stale_version_cannot_overwrite_draft_or_status(db):
    voyage = db.voyage()
    bid = db.booking(voyage)
    stale = db.snapshot(bid)["version_hex"]
    with db.app() as conn:
        arguments = dict(actor_id=db.users["sales"], booking_id=bid, customer_id=db.customer,
            voyage_id=voyage, cargo_description="第一次有效修改", remark=None,
            items_json='[{"container_type_id":1,"quantity":3,"total_gross_kg":3500}]', expected_version=stale)
        execute(conn, "usp_SaveBookingDraft", **arguments)
        before = db.snapshot(bid)
        arguments["cargo_description"] = "不应覆盖的旧页面修改"
        expect_business_error(lambda: execute(conn, "usp_SaveBookingDraft", **arguments))
    assert db.snapshot(bid) == before
    expect_business_error(lambda: db.action(bid, "submit", expected=stale))
    assert db.snapshot(bid) == before


@pytest.mark.parametrize("actor,action", [("admin", "submit"), ("sales2", "submit"), ("reviewer", "cancel"), ("analyst", "cancel")])
def test_roles_and_ownership_are_enforced_inside_sql(db, actor, action):
    bid = db.booking(db.voyage())
    before = db.snapshot(bid)
    expect_business_error(lambda: db.action(bid, action, actor, reason="越权测试"))
    assert db.snapshot(bid) == before


def test_reviewer_cannot_confirm_own_order_even_with_both_roles(db):
    with db.app() as conn:
        uid = execute(conn, "usp_SaveUser", actor_id=db.users["admin"], user_id=None,
            username="selfcheck_" + uuid.uuid4().hex[:16], display_name="自审保护测试",
            password_hash=generate_password_hash("Temporary-Test@2026"), is_active=True,
            roles_json='["SALES","REVIEWER"]', expected_version=None)[0]["user_id"]
    bid = db.booking(db.voyage(), user=uid)
    db.action(bid, "submit", uid)
    before = db.snapshot(bid)
    expect_business_error(lambda: db.action(bid, "confirm", uid))
    assert db.snapshot(bid) == before


def test_submitted_items_cannot_be_changed_even_by_direct_dml(db):
    bid = db.booking(db.voyage())
    db.action(bid, "submit")
    before = db.snapshot(bid)
    with db.admin() as conn:
        expect_business_error(lambda: conn.execute("UPDATE dbo.BookingItem SET quantity=quantity+1 WHERE booking_id=?", bid))
    assert db.snapshot(bid) == before


@pytest.mark.parametrize("statement", [
    "UPDATE dbo.Booking SET remark=N'forbidden' WHERE 1=0",
    "DELETE FROM dbo.BookingItem WHERE 1=0",
    "SELECT password_hash FROM dbo.AppUser WHERE 1=0",
])
def test_runtime_login_has_no_base_table_access(db, statement):
    with db.app() as conn:
        with pytest.raises(pyodbc.Error) as caught:
            conn.execute(statement)
        assert "(229)" in str(caught.value), str(caught.value)


def test_published_voyage_cannot_be_edited_and_departure_requires_no_pending(db):
    voyage = db.voyage()
    with db.app() as conn:
        original = one(conn, "SELECT * FROM dbo.v_VoyageCapacity WHERE voyage_id=?", voyage)
        args = {key: original[key] for key in ("voyage_no", "vessel_id", "origin_port_id", "destination_port_id", "departure_at", "arrival_at", "booking_cutoff_at", "saleable_teu", "saleable_gross_kg")}
        args.update(actor_id=db.users["admin"], voyage_id=voyage, expected_version=original["version_hex"])
        args["saleable_teu"] = 9
        expect_business_error(lambda: execute(conn, "usp_SaveVoyage", **args))
    bid = db.booking(voyage)
    db.action(bid, "submit")
    with db.app() as conn:
        execute(conn, "usp_TransitionVoyage", actor_id=db.users["admin"], voyage_id=voyage,
            target_status="CLOSED", expected_version=db.version(conn, "voyage", voyage))
        expect_business_error(lambda: execute(conn, "usp_TransitionVoyage", actor_id=db.users["admin"], voyage_id=voyage,
            target_status="DEPARTED", expected_version=db.version(conn, "voyage", voyage)))
    db.action(bid, "cancel", reason="离港前清理待审单")
    with db.app() as conn:
        execute(conn, "usp_TransitionVoyage", actor_id=db.users["admin"], voyage_id=voyage,
            target_status="DEPARTED", expected_version=db.version(conn, "voyage", voyage))
        assert conn.execute("SELECT status FROM dbo.v_VoyageCapacity WHERE voyage_id=?", voyage).fetchone()[0] == "DEPARTED"


def test_empty_draft_can_be_saved_but_cannot_submit(db):
    bid = db.booking(db.voyage(), items=[])
    before = db.snapshot(bid)
    expect_business_error(lambda: db.action(bid, "submit"))
    assert db.snapshot(bid) == before


def test_failure_after_status_write_rolls_back_status_history_and_audit(db):
    """Inject an audit failure in an outer transaction; trigger is rolled back."""
    bid = db.booking(db.voyage())
    db.action(bid, "submit")
    before = db.snapshot(bid)
    trigger = "test_AuditFailure_" + uuid.uuid4().hex
    with db.admin() as conn:
        conn.execute("BEGIN TRANSACTION")
        try:
            conn.execute(f"""CREATE TRIGGER dbo.[{trigger}] ON dbo.AuditLog AFTER INSERT AS
BEGIN
 SET NOCOUNT ON;
 IF EXISTS(SELECT 1 FROM inserted WHERE entity_name='Booking' AND entity_key=N'{bid}')
  THROW 55001,N'测试注入：审计写入失败，必须回滚整个订舱确认',1;
END""")
            message = expect_business_error(lambda: db.action(bid, "confirm", "reviewer", conn=conn))
            assert "55001" in message
        finally:
            conn.execute("IF @@TRANCOUNT>0 ROLLBACK TRANSACTION")
        assert conn.execute("SELECT OBJECT_ID(?)", "dbo." + trigger).fetchone()[0] is None
    assert db.snapshot(bid) == before


def test_last_active_admin_cannot_be_disabled_or_demoted(db):
    """Temporary isolation is rolled back, including every existing admin flag."""
    with db.admin() as conn:
        originals = [tuple(row) for row in conn.execute("SELECT user_id,is_active,CONVERT(varchar(18),CONVERT(binary(8),row_version),1) FROM dbo.AppUser ORDER BY user_id")]
        for roles, active in [('[]', True), ('["ANALYST"]', True), ('["ADMIN"]', False)]:
            conn.execute("BEGIN TRANSACTION")
            try:
                username = "lastadmin_" + uuid.uuid4().hex[:16]
                user = execute(conn, "usp_SaveUser", actor_id=db.users["admin"], user_id=None,
                    username=username, display_name="最后管理员保护测试",
                    password_hash=generate_password_hash("Temporary-Test@2026"), is_active=True,
                    roles_json='["ADMIN"]', expected_version=None)[0]
                uid = user["user_id"]
                # Only this uncommitted test transaction sees other admins as
                # inactive. The procedure's rollback or finally restores them.
                conn.execute("""UPDATE u SET is_active=0 FROM dbo.AppUser u
                    WHERE u.user_id<>? AND EXISTS(SELECT 1 FROM dbo.UserRole ur JOIN dbo.[Role] r ON r.role_id=ur.role_id WHERE ur.user_id=u.user_id AND r.role_code='ADMIN')""", uid)
                expect_business_error(lambda: execute(conn, "usp_SaveUser", actor_id=uid, user_id=uid,
                    username=username, display_name="最后管理员保护测试",
                    password_hash=None, is_active=active, roles_json=roles,
                    expected_version=db.version(conn, "user", uid)))
            finally:
                conn.execute("IF @@TRANCOUNT>0 ROLLBACK TRANSACTION")
        restored = [tuple(row) for row in conn.execute("SELECT user_id,is_active,CONVERT(varchar(18),CONVERT(binary(8),row_version),1) FROM dbo.AppUser ORDER BY user_id")]
    assert restored == originals
