# add transcript input_type for multimodal flow
from alembic import op
import sqlalchemy as sa

revision = "0002_add_transcript_input_type"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transcripts",
        sa.Column("input_type", sa.String(length=20), nullable=False, server_default=sa.text("'text'")),
    )


def downgrade() -> None:
    op.drop_column("transcripts", "input_type")
