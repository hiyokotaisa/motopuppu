# motopuppu

オートバイの燃費計算、整備記録、車両管理を行うためのWebアプリケーションです。

## 概要

日々の給油記録から燃費を自動計算したり、メンテナンスの履歴を管理することができます。ODOメーターのリセットにも対応し、正確な総走行距離を追跡します。Misskeyアカウント (MiAuth) でログインして利用します。

## 主な機能

* Misskey MiAuthによるユーザー認証
* 車両管理（メーカー、名前、年式）、複数車両対応、デフォルト車両設定
* ODOメーターリセット記録と総走行距離の自動計算
* 給油記録（燃費自動計算、費用記録含む）
* 整備記録（費用記録、カテゴリ分類、ファイル添付含む）
* ダッシュボード（平均燃費、直近記録、カレンダー、メンテナンスリマインダー）
* 記録の検索・フィルタリング
* 統計・レポート表示（グラフなど）
* 消耗品（タイヤ、オイル）交換記録
* （将来的に: カスタマイズ、データエクスポート/インポートなど）

## 技術スタック

* Python 3.x
* Flask
* SQLAlchemy
* SQLite (開発時) / PostgreSQL (推奨)
* Bootstrap 5
* FullCalendar.io
* Chart.js (予定)

## セットアップ

1.  リポジトリをクローンします:
    ```bash
    git clone [https://github.com/your-username/motopuppu.git](https://github.com/your-username/motopuppu.git)
    cd motopuppu
    ```
2.  Python 仮想環境を作成し、有効化します:
    ```bash
    python -m venv venv
    # Windows
    # venv\Scripts\activate
    # macOS/Linux
    source venv/bin/activate
    ```
3.  依存ライブラリをインストールします:
    ```bash
    pip install -r requirements.txt
    ```
4.  環境変数ファイルを作成します:
    `.env.example` をコピーして `.env` を作成し、ファイル内の指示に従って必要な値を設定してください (**`SECRET_KEY` は必ず設定してください**)。
    ```bash
    cp .env.example .env
    # nano .env # などで編集
    ```
5.  データベースを初期化します:
    ```bash
    # (初期化用のコマンドをここに記述 - 例: flask db init, flask db migrate, flask db upgrade またはカスタムコマンド)
    # 例 (シンプルな初期化):
    # flask shell
    # >>> from motopuppu import db, create_app
    # >>> app = create_app()
    # >>> with app.app_context():
    # >>>     db.create_all()
    # >>> exit()
    ```

## 実行

```bash
flask run
