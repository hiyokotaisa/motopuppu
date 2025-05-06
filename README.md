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

* Python 3.x (3.11以降推奨)
* Flask
* SQLAlchemy
* Flask-Migrate (データベースマイグレーション)
* PostgreSQL (本番・開発推奨) / SQLite (簡易開発用)
* Podman & Podman Compose (コンテナ開発環境推奨)
* Gunicorn (WSGIサーバー)
* Bootstrap 5
* FullCalendar.io
* requests
* python-dotenv
* python-dateutil

## 開発環境セットアップ

開発環境の構築方法は、コンテナを使用する**Podman (推奨)** と、ホストOSに直接構築する**Python仮想環境**の2通りがあります。

### Podman を利用したセットアップ (推奨)

より一貫性があり、環境分離された開発を行うために、Podman と `podman-compose` を利用したコンテナベースのセットアップを推奨します。
以下の手順で、FlaskアプリケーションとPostgreSQLデータベースのコンテナ環境を構築できます。

**1. 事前準備:**

* **Git のインストール:** お使いのシステムに Git をインストールしてください。
* **Podman / Podman Compose のインストール:**
    * **Fedora:**
        ```bash
        sudo dnf install podman podman-compose
        ```
    * **Apple Silicon Mac:**
        * Homebrew (推奨): `brew install podman podman-compose`
        * または、[Podman Desktop](https://podman.io/downloads) をインストール。
    * **その他の Linux / Windows (WSL2):** 各ディストリビューションの手順に従って `podman` と `podman-compose` をインストールしてください。(WSL2ではネットワーク関連で問題が発生する場合があります。その場合は Docker Desktop の利用も検討してください。)
* **Podman Machine (macOS のみ):**
    macOS の場合は、Podman Machine (Linux VM) を初期化・起動する必要があります。
    ```bash
    podman machine init # 初回のみ
    podman machine start
    ```
    (Podman Desktop を使用している場合は GUI から操作できます。)

**2. プロジェクトファイルの準備:**

* **リポジトリのクローン:**
    ```bash
    git clone https://github.com/hiyokotaisa/motopuppu.git
    cd motopuppu
    ```
* **設定ファイルの配置:** プロジェクトルートに以下のファイルが存在することを確認（またはリポジトリ内のサンプルから作成）してください。
    * `Dockerfile`: アプリケーションコンテナをビルドするためのファイル。（リポジトリ内のファイルを使用）
    * `compose.yml`: `db` (PostgreSQL) と `web` (Flaskアプリ) サービスを定義するファイル。（リポジトリ内のファイルを使用）
        * **注意 (Linux/Fedora):** ネイティブ Linux (特に SELinux 有効環境) で使用する場合、`compose.yml` 内の `web` サービスの `volumes` で `.` (カレントディレクトリ) をマウントする行を `- .:/app:Z` のように `:Z` フラグ付きに修正してください。macOS では `:Z` は不要です。
    * `.env`: 環境変数を定義するファイル。リポジトリに `env.example` があればそれをコピーして `.env` を作成し、最低限以下の変数を設定してください。**このファイルは `.gitignore` に追加し、リポジトリに含めないでください。**
        * `POSTGRES_PASSWORD`: PostgreSQLデータベースのパスワード（**必ず安全な値を設定**）。
        * `SECRET_KEY`: Flaskのセッション等で使用する秘密鍵（**必ずランダムな値を設定**。例: `python -c "import secrets; print(secrets.token_hex(16))"`）。
        * `MISSKEY_INSTANCE_URL`: (任意) デフォルトは `https://misskey.io`。
        * `LOCAL_DEV_USER_ID`: (後述) ローカルログインで使用するユーザーID。

**3. コンテナの起動と初期設定:**

* **コンテナのビルドとバックグラウンド起動:**
    プロジェクトルートで以下のコマンドを実行します。
    ```bash
    podman-compose up --build -d
    ```
    コンテナイメージのビルドとコンテナの起動が行われます。`db` コンテナの `healthcheck` が通るまで少し待ちます (`podman ps` で `(healthy)` 表示を確認)。

* **データベーススキーマの作成 (マイグレーション適用):**
    `web` コンテナ内で `flask db upgrade` を実行し、DBスキーマを最新にします。
    ```bash
    podman exec -it motopuppu_web_dev flask --app motopuppu db upgrade
    ```
    (`motopuppu_web_dev` は `compose.yml` で指定したコンテナ名、または `podman ps` で確認した実際のコンテナ名/ID)

* **ローカル開発用ユーザーの作成:**
    ローカルログイン機能で使用するユーザーを作成します。`web` コンテナ内で `flask shell` を起動します。
    ```bash
    podman exec -it motopuppu_web_dev flask --app motopuppu shell
    ```
    シェル内で以下を実行し、**表示されたユーザーIDをメモ**します。
    ```python
    from motopuppu.models import User
    from motopuppu import db
    u = User(misskey_user_id='local_podman_user', misskey_username='開発ユーザー') # ID/名は適宜変更可
    db.session.add(u)
    db.session.commit()
    print(f"ユーザーが作成されました。ID: {u.id}")
    exit()
    ```

* **`.env` ファイルの更新:**
    プロジェクトルートの `.env` ファイルを開き、`LOCAL_DEV_USER_ID=` に手順3でメモしたユーザーIDを設定して保存します。

* **Web コンテナの再起動:**
    `.env` の変更を反映させるために `web` サービスを再起動します。
    ```bash
    podman-compose restart web
    ```

* **アプリケーションへのアクセス:**
    Webブラウザで `http://localhost:5000` を開きます。「開発用ログイン」ボタンからログインできることを確認してください。

**4. 環境の停止:**

開発を終了する際は、以下のコマンドでコンテナを停止・削除します（データベースのデータは名前付きボリューム `pg_data` に永続化されているため消えません）。
```bash
podman-compose down
```

### (オプション) 仮想マシン(libvirt)上で実行し、ホストからアクセスする場合

1.  上記の手順で、libvirt 上の Fedora 仮想マシン内に Podman 環境を構築します。
2.  仮想マシン内で `ip addr show` コマンドを実行し、仮想マシンのIPアドレスを確認します。
3.  仮想マシン内でファイアウォールを設定し、ポート5000へのアクセスを許可します。
    ```bash
    # 仮想マシン内で実行
    sudo firewall-cmd --add-port=5000/tcp --permanent
    sudo firewall-cmd --reload
    ```
4.  ホストマシンのブラウザから `http://<仮想マシンのIPアドレス>:5000` でアクセスします。

### Python 仮想環境を利用したセットアップ (コンテナを利用しない場合)

**注意:** この方法はホストOSに直接ライブラリやデータベースをセットアップするため、環境が汚れやすい、あるいは他のプロジェクトとの依存関係の衝突が起こる可能性があります。Podmanの利用を推奨します。データベースは別途 PostgreSQL サーバーを起動するか、SQLite を利用します。

1.  **リポジトリをクローンします:**
    ```bash
    git clone [https://github.com/hiyokotaisa/motopuppu.git](https://github.com/hiyokotaisa/motopuppu.git)
    cd motopuppu
    ```
2.  **Python 仮想環境を作成し、有効化します:**
    ```bash
    python3 -m venv venv # Python 3 を明示
    # Windows
    # venv\Scripts\activate
    # macOS/Linux
    source venv/bin/activate
    ```
3.  **依存ライブラリをインストールします:**
    ```bash
    pip install -r requirements.txt
    # PostgreSQL を使う場合は psycopg2-binary も必要 (requirements.txtに含まれていればOK)
    # pip install psycopg2-binary
    ```
4.  **環境変数ファイルを作成します:**
    `.env.example` (もし存在すれば) をコピーして `.env` を作成するか、新規に `.env` を作成します。
    ```bash
    # cp .env.example .env # .env.example があれば
    # nano .env # または他のエディタで .env を作成・編集
    ```
    ファイル内の指示に従って必要な値を設定してください。
    * **`SECRET_KEY`**: **必須。** Flaskのセッション等で使用する秘密鍵。`python -c "import secrets; print(secrets.token_hex(16))"` などで生成し、**必ずランダムな文字列に変更してください。**
    * **`DATABASE_URI`**: PostgreSQL などの外部データベースを使用する場合に設定します (例: `postgresql://user:pass@host:port/dbname`)。設定しない場合は、デフォルトでプロジェクトルート下の `instance/app.db` という SQLite データベースが使用されます。
    * **`MISSKEY_INSTANCE_URL`**: (任意) MiAuthで使用するMisskeyインスタンスのURL（デフォルト: `https://misskey.io`）。
    * **`LOCAL_DEV_USER_ID`**: (任意) ローカルログインで使用するユーザーID（DB初期化後にユーザーを作成して設定）。

5.  **データベースを初期化します:**
    Flask-Migrate を使用してデータベーススキーマを管理します。
    * **（初回 or `migrations` フォルダがない場合）マイグレーション環境を初期化:**
        ```bash
        flask db init
        ```
    * **データベースにスキーマを適用 (必須):**
        アプリケーションを初めてセットアップする場合や、Gitから最新のコードを取得した場合は、以下のコマンドでデータベースの構造を最新の状態にします。
        ```bash
        flask db upgrade
        ```
    * **（モデル変更時）マイグレーションスクリプトを作成:**
        開発中に `models.py` を変更した場合は、以下のコマンドで変更を検出し、マイグレーションスクリプトを生成してから `flask db upgrade` を実行します。
        ```bash
        flask db migrate -m "変更内容の短い説明"
        flask db upgrade
        ```

## 実行 (Python 仮想環境でのローカル開発)

上記「Python 仮想環境を利用したセットアップ」を行った後、以下のコマンドで開発サーバーを起動します。

```bash
flask run
```
ブラウザで http://127.0.0.1:5000 (または表示されたアドレス) を開きます。