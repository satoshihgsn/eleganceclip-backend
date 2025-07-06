import os
import subprocess
import sys
import shutil # ファイル操作のためのモジュール

from flask import Flask, request, send_file, jsonify, abort
from werkzeug.utils import secure_filename # ファイル名を安全にするためのユーティリティ

from flask_cors import CORS # この行を追加

app = Flask(__name__)
CORS(app) # この行を追加: これがCORSを有効にする魔法の杖です

# ダウンロード一時保存用ディレクトリ
# Renderのようなクラウド環境では、ファイルシステムへの書き込みは一時的です。
# ダウンロード後すぐに削除することが重要です。
DOWNLOAD_FOLDER = 'downloads'
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

@app.route('/')
def index():
    # Renderにデプロイした際、このURLにアクセスするとこのメッセージが表示されます。
    # フロントエンドは別でデプロイするため、このルートはシンプルでOKです。
    return "Backend server for EleganceClip is running!"

@app.route('/download', methods=['POST'])
def download_video():
    data = request.json
    video_url = data.get('url')

    if not video_url:
        return jsonify({"error": "URLが提供されていません。"}), 400

    # yt-dlpの出力パスを一時的なダウンロードフォルダに設定
    # yt-dlpが安全なファイル名を生成するように --restrict-filenames を使用
    # %(title)s.%(ext)s でタイトルと拡張子を自動取得
    # temp_output_path_template = os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s')

    # 一意のフォルダ名を生成して、同時ダウンロードでのファイル名衝突を避ける
    import uuid
    unique_folder = os.path.join(DOWNLOAD_FOLDER, str(uuid.uuid4()))
    os.makedirs(unique_folder, exist_ok=True)
    temp_output_path_template = os.path.join(unique_folder, '%(title)s.%(ext)s')


    try:
        # yt-dlpコマンドを構築
        # -f: MP4形式を優先 (bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best)
        # -o: 出力パス
        # --restrict-filenames: ファイル名に使用できない文字を制限
        # --no-playlist: プレイリストをダウンロードしない
        # --print-json: 動画情報をJSON形式で取得（ファイル名決定のため）

        # app.py の download_video 関数内
        command = [
            sys.executable,
            "-m",
            "yt_dlp",
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "-o", temp_output_path_template,
            "--restrict-filenames",
            "--no-playlist",
            "--print-json",
            "--no-check-certificate",  # 追加
            "--geo-bypass-country", "JP", # 追加: 日本からアクセスしているように見せかける
            video_url
        ]


        # サブプロセスとしてyt-dlpを実行し、標準出力をキャプチャ
        # check=True: コマンドがエラーコードを返したらCalledProcessErrorを発生させる
        process = subprocess.run(command, check=True, capture_output=True, text=True)

        # yt-dlpの標準出力からJSON形式の動画情報をパースしてファイル名を取得
        # JSON出力の最後の行に動画情報があることが多い
        video_info_json = ""
        for line in process.stdout.splitlines():
            if line.strip().startswith('{') and line.strip().endswith('}'):
                video_info_json = line
                break

        if not video_info_json:
            raise Exception("yt-dlpから動画情報を取得できませんでした。出力:\n" + process.stdout + "\n" + process.stderr)

        import json
        video_info = json.loads(video_info_json)

        # yt-dlpが実際に保存したファイルパスを見つける
        actual_download_path = None
        # yt-dlpのログから 'Destination:' で始まる行を探すのが最も確実
        for line in process.stdout.splitlines() + process.stderr.splitlines():
            if "Destination:" in line:
                # 例: "[download] Destination: /tmp/downloads/video_title.mp4"
                actual_download_path = line.split("Destination:")[1].strip()
                # 完全にパスが指定されていない場合（相対パスなど）の調整
                if not os.path.isabs(actual_download_path):
                    # yt-dlpは通常、実行されたディレクトリのサブディレクトリに保存するので、
                    # temp_output_path_templateのベースディレクトリを考慮
                    actual_download_path = os.path.join(unique_folder, os.path.basename(actual_download_path))
                break

        if not actual_download_path or not os.path.exists(actual_download_path):
            # ログから見つからない場合のフォールバック：ディレクトリ内のファイルを探索
            downloaded_files = [os.path.join(unique_folder, f) for f in os.listdir(unique_folder) if os.path.isfile(os.path.join(unique_folder, f))]
            if downloaded_files:
                # 最新のファイルを選択（複数のファイルがダウンロードされる可能性は低いが念のため）
                actual_download_path = max(downloaded_files, key=os.path.getctime)
            else:
                raise Exception("ダウンロードされたファイルが見つかりませんでした。")

        # ダウンロードされるファイル名を設定（クライアントに提示する名前）
        # yt-dlpが提供する安全なタイトルを使用し、.mp4を付与
        # secure_filename でさらに安全性を確保
        downloaded_filename = secure_filename(f"{video_info.get('title', 'video')}.mp4")

        # ファイルをクライアントに送信
        response = send_file(actual_download_path,
                             mimetype="video/mp4",
                             as_attachment=True,
                             download_name=downloaded_filename) # クライアントに提示するファイル名

        # ファイル送信後にクリーンアップ (一時フォルダごと削除)
        @response.call_on_close
        def cleanup():
            try:
                if os.path.exists(unique_folder):
                    shutil.rmtree(unique_folder) # フォルダごと削除
                    print(f"一時フォルダ {unique_folder} を削除しました。")
            except Exception as e:
                print(f"一時フォルダの削除中にエラーが発生しました: {e}")

        return response

    except subprocess.CalledProcessError as e:
        # yt-dlpのエラーメッセージをクライアントに返す
        error_message = e.stderr.strip() if e.stderr else f"yt-dlpの実行中にエラーが発生しました (コード: {e.returncode})"
        app.logger.error(f"yt-dlp error for {video_url}: {error_message}")
        return jsonify({"error": error_message}), 500
    except FileNotFoundError:
        return jsonify({"error": "サーバーでyt-dlpが見つかりません。設定を確認してください。"}), 500
    except Exception as e:
        app.logger.error(f"サーバー内部エラーが発生しました: {e}", exc_info=True)
        return jsonify({"error": f"サーバー内部エラーが発生しました: {str(e)}"}), 500

if __name__ == '__main__':
    # ローカルでのテスト用設定
    # debug=True: 開発中にコードを変更すると自動で再起動
    # host='0.0.0.0': 外部からのアクセスを許可（ローカルネットワーク内）
    # port=5000: ポート番号
    app.run(debug=True, host='0.0.0.0', port=5000)