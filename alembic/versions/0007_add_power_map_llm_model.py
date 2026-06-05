"""add power map llm model

Revision ID: 0007_add_power_map_llm_model
Revises: 0006_add_power_map_bi_login
Create Date: 2026-06-04
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_add_power_map_llm_model"
down_revision = "0006_add_power_map_bi_login"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("system_config", sa.Column("power_map_llm_model", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("system_config", "power_map_llm_model")
