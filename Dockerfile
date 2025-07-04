# Containerfile

# ベースイメージを選択
FROM python:3.13

# 環境変数設定
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 作業ディレクトリ作成・設定
WORKDIR /app

# 依存関係ファイルをコピーしてインストール
# (requirements.txt に psycopg2-binary が含まれていることを想定)
COPY requirements.txt .
# pipで依存関係をインストール
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードをコピー
COPY . .

# アプリケーションが使用するポートを公開 (Flaskデフォルト)
EXPOSE 5000

# コンテナ起動時にFlask開発サーバーを実行
CMD ["flask", "--app", "motopuppu", "run", "--host=0.0.0.0"]