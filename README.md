# もとぷっぷー

オートバイの燃費計算、整備記録、車両管理を行うためのWebアプリケーションです。

## 概要

日々の給油記録から燃費を自動計算したり、メンテナンスの履歴を管理することができます。ODOメーターのリセットにも対応し、正確な総走行距離を追跡します。Misskeyアカウント (MiAuth) でログインして利用します。

## 主な機能

* Misskey MiAuthによるユーザー認証
* 車両管理（メーカー、名前、年式）、複数車両対応、デフォルト車両設定
* ODOメーターリセット記録と総走行距離の自動計算
* 給油記録（燃費自動計算、費用記録、満タンチェック含む）
* 整備記録（費用記録、カテゴリ分類）
* ダッシュボード
    * メンテナンス通知（時期接近、超過）
    * 統計サマリー（デフォルト車両の総走行距離・平均燃費、累計費用）
    * 直近の給油/整備記録（車両別フィルター付き）
    * カレンダー表示（記録表示、詳細ポップオーバー、月/週/リスト表示切替）
* メンテナンスリマインダー（サイクル設定、ダッシュボード通知、整備記録との自動連携）
* 記録の検索・フィルタリング（日付、車両、カテゴリ、キーワードによる基本的なフィルタリング）
* SNS共有機能（給油/整備記録をMisskeyへ共有）
* 車両登録台数制限（1ユーザーあたり100台）
* Favicon設定
* ファイル添付 (整備記録、計画中)
* 詳細な統計・レポート表示（グラフなど）(計画中)
* 消耗品（タイヤ、オイル）交換記録 (計画中)
* （将来的に: カスタマイズ、データエクスポート/インポートなど）

## 技術スタック

* Python 3.x
* Flask
* SQLAlchemy
* Flask-Migrate (データベースマイグレーション)
* SQLite (開発時) / PostgreSQL (推奨)
* Gunicorn (WSGIサーバー)
* Bootstrap 5
* FullCalendar.io
* requests
* python-dotenv
* python-dateutil

## セットアップ

1.  リポジトリをクローンします:
    ```bash
    git clone [https://github.com/hiyokotaisa/motopuppu.git](https://github.com/hiyokotaisa/motopuppu.git)
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
    `.env.example` (もし存在すれば) をコピーして `.env` を作成し、ファイル内の指示に従って必要な値を設定してください (**`SECRET_KEY` は必ず設定・変更してください**)。最低限必要な設定は `SECRET_KEY` と `DATABASE_URI` (SQLiteの場合は通常自動設定されます) です。Misskey連携を使用する場合は、`MISSKEY_INSTANCE_URL` も設定します。
    ```bash
    # cp .env.example .env # .env.example があれば
    # nano .env # または他のエディタで .env を作成・編集
    ```
    必要な環境変数（一部）:
    * `SECRET_KEY`: Flaskのセッション等で使用する秘密鍵。**必ずランダムな文字列に変更してください。**
    * `DATABASE_URI`: (任意) デフォルトは `instance/app.db` の SQLite。PostgreSQL などに変更する場合に設定。
    * `MISSKEY_INSTANCE_URL`: (任意) MiAuthで使用するMisskeyインスタンスのURL（デフォルト: `https://misskey.io`）。

5.  データベースを初期化します:
    このアプリケーションは Flask-Migrate を使用してデータベーススキーマを管理します。

    a.  **（初回のみ）マイグレーション環境を初期化:**
        プロジェクトに `migrations` フォルダがまだない場合は、以下のコマンドを実行します。
        ```bash
        flask db init
        ```

    b.  **（モデル変更時）マイグレーションスクリプトを作成:**
        `models.py` を変更した場合は、以下のコマンドで変更を検出し、マイグレーションスクリプトを生成します。
        ```bash
        flask db migrate -m "変更内容の短い説明"
        ```

    c.  **データベースにスキーマを適用:**
        データベースにテーブルを作成したり、スキーマの変更を適用するには、以下のコマンドを実行します。**アプリケーションを初めてセットアップする場合や、`migrate` を実行した後には、必ずこのコマンドを実行してください。**
        ```bash
        flask db upgrade
        ```
        これにより、データベースの構造が最新の状態になります。

    **(注意)** 以前の `flask init-db` コマンドは管理者作成ロジックが削除されたため、データベースのセットアップには上記 `flask db upgrade` を使用することを推奨します。

## 実行 (ローカル開発)

```bash
flask run