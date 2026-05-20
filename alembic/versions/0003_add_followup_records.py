# Add followup_records table for 简道云 followup record scraping
from alembic import op
import sqlalchemy as sa

revision = "0003_add_followup_records"
down_revision = "0002_add_transcript_input_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "followup_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("source_id", sa.String(length=255)),
        sa.Column("title", sa.String(length=255)),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("segments", sa.JSON(), nullable=True),
        sa.Column("input_type", sa.String(length=20), nullable=False, server_default=sa.text("'followup'")),
        sa.Column("status", sa.String(length=30), nullable=False, server_default=sa.text("'parsed'")),
        sa.Column("agent_a_result", sa.JSON(), nullable=True),
        sa.Column("agent_b_result", sa.JSON(), nullable=True),
        sa.Column("company_id", sa.String(length=255)),
        sa.Column("company_name", sa.String(length=255)),
        sa.Column("sso_user_name", sa.String(length=100)),
        sa.Column("sso_user_id", sa.String(length=255)),
        sa.Column("review_date", sa.String(length=50)),
        sa.Column("follow_type", sa.String(length=50)),
        sa.Column("raw_record", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_followup_records_company_id", "followup_records", ["company_id"])
    op.create_index("ix_followup_records_company_id_status", "followup_records", ["company_id", "status"])
    op.create_index("ix_followup_records_source_id", "followup_records", ["source_id"])
    op.create_index("ix_followup_records_sso_user_name", "followup_records", ["sso_user_name"])


def downgrade() -> None:
    op.drop_index("ix_followup_records_sso_user_name", table_name="followup_records")
    op.drop_index("ix_followup_records_source_id", table_name="followup_records")
    op.drop_index("ix_followup_records_company_id_status", table_name="followup_records")
    op.drop_index("ix_followup_records_company_id", table_name="followup_records")
    op.drop_table("followup_records")
