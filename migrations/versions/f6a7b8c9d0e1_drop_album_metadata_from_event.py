"""drop unused album metadata columns from event (Phase 2 revert)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-26 02:40:00.000000

Media Share の API がサードパーティ向けトークン発行をサポートしていない
ことが判明したため、Phase 2 で追加した album_id / album_title /
album_cover_url / album_media_count / album_metadata_fetched_at を削除する。

album_url (String 500, Phase 1) は引き続き使用するため残す。

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_column('album_metadata_fetched_at')
        batch_op.drop_column('album_media_count')
        batch_op.drop_column('album_cover_url')
        batch_op.drop_column('album_title')
        batch_op.drop_column('album_id')


def downgrade():
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'album_id', sa.String(length=64),
            nullable=True,
            comment='連携した media-share アルバムのUUID'
        ))
        batch_op.add_column(sa.Column(
            'album_title', sa.String(length=200),
            nullable=True,
            comment='連携アルバムのタイトル (キャッシュ)'
        ))
        batch_op.add_column(sa.Column(
            'album_cover_url', sa.String(length=500),
            nullable=True,
            comment='連携アルバムのカバー画像URL (キャッシュ)'
        ))
        batch_op.add_column(sa.Column(
            'album_media_count', sa.Integer(),
            nullable=True,
            comment='連携アルバム内のメディア数 (キャッシュ)'
        ))
        batch_op.add_column(sa.Column(
            'album_metadata_fetched_at', sa.DateTime(),
            nullable=True,
            comment='キャッシュ最終取得日時 (UTC)'
        ))
