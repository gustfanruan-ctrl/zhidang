from alembic import op
import sqlalchemy as sa

revision = '0006_add_power_map_bi_login'
down_revision = '0005_add_user_followup_review_template'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('system_config', sa.Column('power_map_login_mobile', sa.String(length=100)))
    op.add_column('system_config', sa.Column('power_map_login_password_encrypted', sa.Text()))


def downgrade() -> None:
    op.drop_column('system_config', 'power_map_login_password_encrypted')
    op.drop_column('system_config', 'power_map_login_mobile')
