"""Initiales Schema: Konten, Vereine, Mitgliedschaften, Plätze, Buchungen, Sperren.

Revision ID: 0001
Revises:
Create Date: 2026-10-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ausschluss-Constraint (keine überlappenden Buchungen) braucht GiST für "court_id ="
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table('clubs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('kind', sa.Enum('club', 'facility', name='club_kind'), nullable=False),
    sa.Column('street', sa.String(length=120), nullable=False),
    sa.Column('zip_code', sa.String(length=10), nullable=False),
    sa.Column('city', sa.String(length=80), nullable=False),
    sa.Column('contact_email', sa.String(length=254), nullable=False),
    sa.Column('join_code', sa.String(length=12), nullable=False),
    sa.Column('max_active_bookings', sa.Integer(), nullable=False),
    sa.Column('max_days_ahead', sa.Integer(), nullable=False),
    sa.Column('cancel_hours', sa.Integer(), nullable=False),
    sa.Column('summer_start', sa.Date(), nullable=False),
    sa.Column('summer_end', sa.Date(), nullable=False),
    sa.Column('prime_from', sa.Integer(), nullable=True),
    sa.Column('prime_to', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('cancel_hours BETWEEN 0 AND 72', name='ck_club_cancel_hours'),
    sa.CheckConstraint('max_active_bookings BETWEEN 1 AND 20', name='ck_club_max_active'),
    sa.CheckConstraint('max_days_ahead BETWEEN 1 AND 60', name='ck_club_days_ahead'),
    sa.CheckConstraint('prime_from IS NULL OR (prime_from >= 0 AND prime_to <= 1440 AND prime_from < prime_to)', name='ck_club_prime'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('join_code')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), nullable=False),
    sa.Column('session_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_table('courts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('club_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=60), nullable=False),
    sa.Column('sport', sa.Enum('tennis', 'padel', name='sport'), nullable=False),
    sa.Column('surface', sa.String(length=60), nullable=False),
    sa.Column('is_indoor', sa.Boolean(), nullable=False),
    sa.Column('has_floodlight', sa.Boolean(), nullable=False),
    sa.Column('season', sa.Enum('all', 'summer', 'winter', name='season'), nullable=False),
    sa.Column('slot_minutes', sa.Integer(), nullable=False),
    sa.Column('price_cents', sa.Integer(), nullable=False),
    sa.Column('prime_price_cents', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.CheckConstraint('price_cents >= 0 AND (prime_price_cents IS NULL OR prime_price_cents >= 0)', name='ck_court_price'),
    sa.CheckConstraint('slot_minutes IN (30, 60, 90, 120)', name='ck_court_slot'),
    sa.ForeignKeyConstraint(['club_id'], ['clubs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_courts_club_id'), 'courts', ['club_id'], unique=False)
    op.create_table('invitations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('club_id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('role', sa.Enum('member', 'admin', name='role'), nullable=False),
    sa.Column('invited_by_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['club_id'], ['clubs.id'], ),
    sa.ForeignKeyConstraint(['invited_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_invitations_club_id'), 'invitations', ['club_id'], unique=False)
    op.create_table('memberships',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('club_id', sa.Integer(), nullable=False),
    sa.Column('role', postgresql.ENUM('member', 'admin', name='role', create_type=False),
              nullable=False),
    sa.Column('status', sa.Enum('pending', 'active', 'locked', name='membership_status'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['club_id'], ['clubs.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'club_id', name='uq_membership')
    )
    op.create_index(op.f('ix_memberships_club_id'), 'memberships', ['club_id'], unique=False)
    op.create_index(op.f('ix_memberships_user_id'), 'memberships', ['user_id'], unique=False)
    op.create_table('opening_hours',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('club_id', sa.Integer(), nullable=False),
    sa.Column('weekday', sa.Integer(), nullable=False),
    sa.Column('opens', sa.Integer(), nullable=False),
    sa.Column('closes', sa.Integer(), nullable=False),
    sa.Column('is_closed', sa.Boolean(), nullable=False),
    sa.CheckConstraint('opens >= 0 AND closes <= 1440 AND opens < closes', name='ck_hours_range'),
    sa.CheckConstraint('weekday BETWEEN 0 AND 6', name='ck_hours_weekday'),
    sa.ForeignKeyConstraint(['club_id'], ['clubs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('club_id', 'weekday', name='uq_hours_club_weekday')
    )
    op.create_index(op.f('ix_opening_hours_club_id'), 'opening_hours', ['club_id'], unique=False)
    op.create_table('blocks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('club_id', sa.Integer(), nullable=False),
    sa.Column('court_id', sa.Integer(), nullable=False),
    sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('reason', sa.String(length=120), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=False),
    sa.CheckConstraint('end_at > start_at', name='ck_block_time'),
    sa.ForeignKeyConstraint(['club_id'], ['clubs.id'], ),
    sa.ForeignKeyConstraint(['court_id'], ['courts.id'], ),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_blocks_club_id'), 'blocks', ['club_id'], unique=False)
    op.create_table('bookings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('club_id', sa.Integer(), nullable=False),
    sa.Column('court_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('price_cents', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('confirmed', 'cancelled', name='booking_status'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_by_id', sa.Integer(), nullable=True),
    postgresql.ExcludeConstraint((sa.column('court_id'), '='), (sa.text("tstzrange(start_at, end_at, '[)')"), '&&'), where=sa.text("status = 'confirmed'"), using='gist', name='ex_booking_no_overlap'),
    sa.CheckConstraint('end_at > start_at', name='ck_booking_time'),
    sa.ForeignKeyConstraint(['cancelled_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['club_id'], ['clubs.id'], ),
    sa.ForeignKeyConstraint(['court_id'], ['courts.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_bookings_club_id'), 'bookings', ['club_id'], unique=False)
    op.create_index(op.f('ix_bookings_user_id'), 'bookings', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_bookings_user_id'), table_name='bookings')
    op.drop_index(op.f('ix_bookings_club_id'), table_name='bookings')
    op.drop_table('bookings')
    op.drop_index(op.f('ix_blocks_club_id'), table_name='blocks')
    op.drop_table('blocks')
    op.drop_index(op.f('ix_opening_hours_club_id'), table_name='opening_hours')
    op.drop_table('opening_hours')
    op.drop_index(op.f('ix_memberships_user_id'), table_name='memberships')
    op.drop_index(op.f('ix_memberships_club_id'), table_name='memberships')
    op.drop_table('memberships')
    op.drop_index(op.f('ix_invitations_club_id'), table_name='invitations')
    op.drop_table('invitations')
    op.drop_index(op.f('ix_courts_club_id'), table_name='courts')
    op.drop_table('courts')
    op.drop_table('users')
    op.drop_table('clubs')
    for name in ("booking_status", "membership_status", "role", "season", "sport", "club_kind"):
        op.execute(f"DROP TYPE IF EXISTS {name}")
