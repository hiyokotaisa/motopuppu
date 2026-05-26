"""add album metadata cache columns to event

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-26 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
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

    # Phase 1 で保存された album_url から UUID を抽出して album_id に backfill
    # PostgreSQL の substring(... from '/album/(...)') を使う
    op.execute(
        """
        UPDATE events
        SET album_id = substring(album_url from '/album/([0-9a-fA-F-]{36})')
        WHERE album_url IS NOT NULL
          AND album_id IS NULL
        """
    )


def downgrade():
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_column('album_metadata_fetched_at')
        batch_op.drop_column('album_media_count')
        batch_op.drop_column('album_cover_url')
        batch_op.drop_column('album_title')
        batch_op.drop_column('album_id')
