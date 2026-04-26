# CR-FINAL-FIX: 生成首版迁移，建立索引与新增表结构。
from alembic import op
import sqlalchemy as sa

revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'superadmin',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('username', sa.String(length=50), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('display_name', sa.String(length=100)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_superadmin_username', 'superadmin', ['username'], unique=True)

    op.create_table(
        'system_config',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('jiandaoyun_api_key_encrypted', sa.Text()),
        sa.Column('jiandaoyun_base_url', sa.String(length=255), nullable=False),
        sa.Column('jiandaoyun_app_id', sa.String(length=100)),
        sa.Column('main_entry_id', sa.String(length=100)),
        sa.Column('field_mappings', sa.JSON(), nullable=True),
        sa.Column('llm_provider', sa.String(length=50), nullable=False),
        sa.Column('llm_api_key_encrypted', sa.Text()),
        sa.Column('llm_base_url', sa.String(length=255), nullable=False),
        sa.Column('agent_a_model', sa.String(length=100), nullable=False),
        sa.Column('agent_b_model', sa.String(length=100), nullable=False),
        sa.Column('nl_chat_model', sa.String(length=100), nullable=False),
        sa.Column('temperature', sa.Float(), nullable=False),
        sa.Column('max_tokens', sa.Integer(), nullable=False),
        sa.Column('agent_a_prompt', sa.Text(), nullable=False),
        sa.Column('agent_b_prompt', sa.Text(), nullable=False),
        sa.Column('nl_query_prompt', sa.Text(), nullable=False),
        sa.Column('nl_modify_prompt', sa.Text(), nullable=False),
        sa.Column('sso_shared_secret', sa.String(length=255)),
        sa.Column('sso_token_ttl_minutes', sa.Integer(), nullable=False),
        sa.Column('dingtalk_app_key', sa.String(length=255)),
        sa.Column('dingtalk_app_secret_encrypted', sa.Text()),
        sa.Column('dingtalk_agent_id', sa.String(length=100)),
        sa.Column('agent_a_max_rounds', sa.Integer(), nullable=False),
        sa.Column('agent_b_max_rounds', sa.Integer(), nullable=False),
        sa.Column('data_retention_days', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        'transcripts',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('source_id', sa.String(length=255)),
        sa.Column('title', sa.String(length=255)),
        sa.Column('raw_text', sa.Text(), nullable=False),
        sa.Column('segments', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('agent_a_result', sa.JSON(), nullable=True),
        sa.Column('agent_b_result', sa.JSON(), nullable=True),
        sa.Column('company_id', sa.String(length=255)),
        sa.Column('company_name', sa.String(length=255)),
        sa.Column('sso_user_name', sa.String(length=100)),
        sa.Column('sso_user_id', sa.String(length=255)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_transcripts_company_id', 'transcripts', ['company_id'])
    op.create_index('ix_transcripts_company_id_status', 'transcripts', ['company_id', 'status'])

    op.create_table(
        'sso_nonce_used',
        sa.Column('nonce', sa.String(length=64), primary_key=True),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        'operation_logs',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('transcript_id', sa.String(length=36), sa.ForeignKey('transcripts.id')),
        sa.Column('operation_type', sa.String(length=50), nullable=False),
        sa.Column('request_payload', sa.JSON(), nullable=True),
        sa.Column('response_payload', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('operator_name', sa.String(length=100)),
        sa.Column('operator_id', sa.String(length=255)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        'config_change_logs',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('config_section', sa.String(length=50), nullable=False),
        sa.Column('changed_fields', sa.JSON(), nullable=True),
        sa.Column('changed_by', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        'analytics_events',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('operator_name', sa.String(length=100)),
        sa.Column('operator_id', sa.String(length=255)),
        sa.Column('operator_source', sa.String(length=20)),
        sa.Column('transcript_id', sa.String(length=36)),
        sa.Column('company_id_hash', sa.String(length=64)),
        sa.Column('session_id', sa.String(length=36)),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('operation_type', sa.String(length=50)),
        sa.Column('action', sa.String(length=50)),
        sa.Column('latency_ms', sa.Integer()),
        sa.Column('model', sa.String(length=50)),
        sa.Column('prompt_version', sa.String(length=20)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_analytics_events_event_type', 'analytics_events', ['event_type'])
    op.create_index('ix_analytics_events_operator_name', 'analytics_events', ['operator_name'])
    op.create_index('ix_analytics_events_transcript_id', 'analytics_events', ['transcript_id'])
    op.create_index('ix_analytics_events_company_id_hash', 'analytics_events', ['company_id_hash'])
    op.create_index('ix_analytics_payload_gin', 'analytics_events', ['payload'], postgresql_using='gin')


def downgrade() -> None:
    op.drop_table('analytics_events')
    op.drop_table('config_change_logs')
    op.drop_table('operation_logs')
    op.drop_table('sso_nonce_used')
    op.drop_index('ix_transcripts_company_id_status', table_name='transcripts')
    op.drop_index('ix_transcripts_company_id', table_name='transcripts')
    op.drop_table('transcripts')
    op.drop_table('system_config')
    op.drop_index('ix_superadmin_username', table_name='superadmin')
    op.drop_table('superadmin')
