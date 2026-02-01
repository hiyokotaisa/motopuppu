---
trigger: always_on
---

## 基本方針
- 特に指示がない限り、日本語で回答する。  
- 以下のドキュメントも**日本語で作成する**：  
  - 実装計画 (Implementation Plan)  
  - 修正内容の確認 (Walkthrough)  
  - タスクリスト (Task List)
- テストについては、手動での実行とし自動実行は行わない
- テスト環境はPodman-Composeを前提とする

### **1.  プロジェクト概要**

* **名称**: もとぷっぷー
* **目的**: オートバイ所有者向けの車両情報、燃費、整備記録、リマインダー、メモ管理、実績、**そして活動・セッティング記録**Webアプリ。公道走行車両に加え、レーサーやモトクロッサーといった競技用車両の管理にも対応。
* **認証**: Misskey MiAuth

### **2.  主要技術スタック**

* **バックエンド**: Python, Flask, SQLAlchemy, PostgreSQL (本番: Render)
* **フロントエンド**: Jinja2, Bootstrap 5, JavaScript, **HTMX**
* **フォーム処理**: Flask-WTF (バリデーション、CSRF対策)
* **DBマイグレーション**: Flask-Migrate (Alembic)
* **デプロイ**: Render (Gunicorn)
* **開発環境**: Podman (Mac/Fedora), Python venv
* **その他**: python-dotenv, requests, python-dateutil, zoneinfo (Python 3.9+), **Cloudflare (CDN)**

### **3.  アーキテクチャ・構成**

* 標準的なFlask構成（アプリケーションファクトリ使用）。
* 機能ごとにBlueprintを使用 (auth, main, vehicle, fuel, maintenance, notes, achievements, **activity** など)。
* `models.py` にDBモデル定義 (`User`, `Motorcycle`, `FuelEntry`, `MaintenanceEntry`, `OdoResetLog`, `GeneralNote`, `AchievementDefinition`, `UserAchievement`, **`SettingSheet`, `ActivityLog`, `SessionLog`** など)。
* `forms.py` にFlask-WTFフォームクラス定義。
* `motopuppu/views/` 以下に各Blueprintのルート定義。
* `templates/`, `static/` ディレクトリ。
* **グローバルな車両リストの読み込み**: `@before_request` ハンドラで、ログインユーザーの車両リストを `g.user_motorcycles` に格納し、ナビゲーションバーのドロップダウンメニューで使用。
