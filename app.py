from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS
import yt_dlp
import os
import threading
import time
import logging

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

progress_data = {}

# Get the cookies content from the environment variable
COOKIES_CONTENT = os.getenv('COOKIES_CONTENT')

# Path where cookies file will be saved temporarily
COOKIES_FILE_PATH = 'cookies.txt'

def create_cookies_file():
    """Creates cookies.txt file from environment variable content."""
    if COOKIES_CONTENT:
        with open(COOKIES_FILE_PATH, 'w') as f:
            f.write(COOKIES_CONTENT)
    else:
        raise Exception("Cookies content not found in environment variables")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def download_video():
    data = request.json
    url = data['url']
    resolution = data['format']
    download_id = str(int(time.time()))  # Unique ID for download tracking
    progress_data[download_id] = {'status': 'Starting', 'progress': 0}

    def download():
        try:
            # Create cookies.txt file from environment variable content
            create_cookies_file()

            # yt-dlp options including the cookies file
            ydl_opts = {
                'format': f'best[height<={resolution[:-1]}][ext=mp4]/best[ext=mp4]',
                'outtmpl': f'static/downloads/output_{download_id}.%(ext)s',
                'progress_hooks': [lambda d: update_progress(download_id, d)],
                'cookiefile': COOKIES_FILE_PATH  # Use the generated cookies.txt
            }

            # Start downloading the video
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            progress_data[download_id] = {'status': 'done', 'progress': 100}

        except Exception as e:
            logger.error(f"Error during download: {str(e)}")
            progress_data[download_id] = {'status': 'error', 'progress': str(e)}

    threading.Thread(target=download).start()  # Start the download in a new thread
    return jsonify({"download_id": download_id})

@app.route('/progress/<download_id>')
def progress(download_id):
    return jsonify(progress_data.get(download_id, {'status': 'Not found', 'progress': 0}))

@app.route('/get_video/<download_id>')
def get_video(download_id):
    file_path = f'static/downloads/output_{download_id}.mp4'
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    return "File not found", 404

def update_progress(download_id, d):
    if d['status'] == 'downloading':
        progress_data[download_id] = {'status': 'downloading', 'progress': d.get('percentage', 0)}
    elif d['status'] == 'finished':
        progress_data[download_id] = {'status': 'done', 'progress': 100}

if __name__ == '__main__':
    os.makedirs('static/downloads', exist_ok=True)
    app.run(debug=True)
