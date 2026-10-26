"""Spieldauer wählbar (60/90/120), Preise pro Stunde, Leihartikel.

- courts.slot_minutes wird zu courts.durations (Liste wählbarer Dauern)
- courts.price_cents / prime_price_cents gelten jetzt pro Stunde und heißen so
- bookings bekommt court_price_cents (Platzanteil am Gesamtpreis)
- neue Tabellen rental_items und booking_items

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SPORT = postgresql.ENUM("tennis", "padel", name="sport", create_type=False)


def upgrade() -> None:
    # Spieldauern: bisherige feste Slotlänge wird die einzige wählbare Dauer
    op.add_column("courts", sa.Column("durations", postgresql.ARRAY(sa.Integer()),
                                      nullable=True))
    op.execute("UPDATE courts SET durations = CASE WHEN slot_minutes IN (60, 90, 120) "
               "THEN ARRAY[slot_minutes] ELSE ARRAY[60, 90] END")
    op.alter_column("courts", "durations", nullable=False)
    op.drop_constraint("ck_court_slot", "courts", type_="check")
    op.drop_column("courts", "slot_minutes")
    op.create_check_constraint(
        "ck_court_durations", "courts",
        "durations <@ ARRAY[60, 90, 120] AND cardinality(durations) >= 1")

    # Preise pro Stunde
    op.drop_constraint("ck_court_price", "courts", type_="check")
    op.alter_column("courts", "price_cents", new_column_name="hourly_price_cents")
    op.alter_column("courts", "prime_price_cents", new_column_name="prime_hourly_price_cents")
    op.create_check_constraint(
        "ck_court_price", "courts",
        "hourly_price_cents >= 0 AND "
        "(prime_hourly_price_cents IS NULL OR prime_hourly_price_cents >= 0)")

    op.add_column("bookings", sa.Column("court_price_cents", sa.Integer(), nullable=True))
    op.execute("UPDATE bookings SET court_price_cents = price_cents")
    op.alter_column("bookings", "court_price_cents", nullable=False)

    op.create_table(
        "rental_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("club_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("sport", SPORT, nullable=True),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("max_per_booking", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.CheckConstraint("max_per_booking BETWEEN 1 AND 10", name="ck_rental_max"),
        sa.CheckConstraint("price_cents >= 0", name="ck_rental_price"),
        sa.ForeignKeyConstraint(["club_id"], ["clubs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_rental_items_club_id"), "rental_items", ["club_id"])
    op.create_table(
        "booking_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("rental_item_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity BETWEEN 1 AND 10", name="ck_item_quantity"),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rental_item_id"], ["rental_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_booking_items_booking_id"), "booking_items", ["booking_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_booking_items_booking_id"), table_name="booking_items")
    op.drop_table("booking_items")
    op.drop_index(op.f("ix_rental_items_club_id"), table_name="rental_items")
    op.drop_table("rental_items")
    op.drop_column("bookings", "court_price_cents")
    op.drop_constraint("ck_court_price", "courts", type_="check")
    op.alter_column("courts", "hourly_price_cents", new_column_name="price_cents")
    op.alter_column("courts", "prime_hourly_price_cents", new_column_name="prime_price_cents")
    op.create_check_constraint(
        "ck_court_price", "courts",
        "price_cents >= 0 AND (prime_price_cents IS NULL OR prime_price_cents >= 0)")
    op.add_column("courts", sa.Column("slot_minutes", sa.Integer(), nullable=True))
    op.execute("UPDATE courts SET slot_minutes = durations[1]")
    op.alter_column("courts", "slot_minutes", nullable=False)
    op.drop_constraint("ck_court_durations", "courts", type_="check")
    op.drop_column("courts", "durations")
    op.create_check_constraint("ck_court_slot", "courts", "slot_minutes IN (30, 60, 90, 120)")
