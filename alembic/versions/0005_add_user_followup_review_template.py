"""Add per-user followup review template."""
from alembic import op
import sqlalchemy as sa


revision = "0005_add_user_followup_review_template"
down_revision = "0004_add_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("followup_review_template", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "followup_review_template")
