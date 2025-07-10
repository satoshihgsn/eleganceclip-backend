import os
import subprocess
import sys
import shutil
import uuid
import json
from flask import Flask, request, send_file, jsonify
from werkzeug.utils import secure_filename
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DOWNLOAD_FOLDER = 'downloads'
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

@app.route('/')
def index():
    return "Backend server for EleganceClip is running!"

@app.route('/download', methods=['POST'])
def download_video():
    data = request.json
    video_url = data.get('url')

    if not video_url:
        return jsonify({"error": "URLが提供されていません。"}), 400

    unique_folder = os.path.join(DOWNLOAD_FOLDER, str(uuid.uuid4()))
    os.makedirs(unique_folder, exist_ok=True)
    temp_output_path_template = os.path.join(unique_folder, '%(title)s.%(ext)s')

    try:
        # --- コマンド構築 ---
        command = [
            sys.executable, "-m", "yt_dlp",
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "-o", temp_output_path_template,
            "--restrict-filenames",
            "--no-playlist",
            "--print-json",
            "--no-check-certificate",
            "--geo-bypass-country", "JP",
            "--verbose"
        ]

        # 環境変数からプロキシURLを取得し、存在すればコマンドに追加
        proxy_url = os.environ.get('PROXY_URL')
        if proxy_url:
            command.extend(['--proxy', proxy_url])

        # 最後にビデオURLを追加
        command.append(video_url)
        # --- コマンド構築ここまで ---

        # yt-dlpを実行
        process = subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8')
        
        # （以降の処理は変更なし）
        video_info_json = ""
        for line in process.stdout.splitlines():
            if line.strip().startswith('{') and line.strip().endswith('}'):
                video_info_json = line
                break
        if not video_info_json:
            raise Exception("yt-dlpから動画情報を取得できませんでした。")
        video_info = json.loads(video_info_json)
        
        downloaded_files = [os.path.join(unique_folder, f) for f in os.listdir(unique_folder)]
        if not downloaded_files:
            raise Exception("ダウンロードされたファイルが見つかりませんでした。")
        
        actual_download_path = max(downloaded_files, key=os.path.getctime)
        downloaded_filename = secure_filename(f"{video_info.get('title', 'video')}.mp4")

        response = send_file(actual_download_path,
                             mimetype="video/mp4",
                             as_attachment=True,
                             download_name=downloaded_filename)

        @response.call_on_close
        def cleanup():
            try:
                shutil.rmtree(unique_folder)
                print(f"一時フォルダ {unique_folder} を削除しました。")
            except Exception as e:
                print(f"一時フォルダの削除中にエラーが発生しました: {e}")
        return response

    except subprocess.CalledProcessError as e:
        error_message = e.stderr.strip() if e.stderr else f"yt-dlpの実行中にエラーが発生しました (コード: {e.returncode})"
        app.logger.error(f"yt-dlp error for {video_url}: {error_message}")
        return jsonify({"error": error_message}), 500
    except Exception as e:
        app.logger.error(f"サーバー内部エラーが発生しました: {e}", exc_info=True)
        return jsonify({"error": f"サーバー内部エラーが発生しました: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)