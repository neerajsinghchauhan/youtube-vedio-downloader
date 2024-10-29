from flask import Flask, request, redirect, session, url_for, render_template, jsonify, send_file
from flask_cors import CORS
from oauthlib.oauth2 import WebApplicationClient
import requests
import yt_dlp
import os
import threading
import time
import logging

app = Flask(__name__)
CORS(app)
# Set up secret key and OAuth2 client settings
app.secret_key = os.getenv("SECRET_KEY")  # Set this in Render environment variables

# OAuth2 setup
client_id = os.getenv("GOOGLE_CLIENT_ID")
client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
client = WebApplicationClient(client_id)

# OAuth2 flow endpoint URLs
GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"

# Routes setup here, similar to your existing `app.py`

@app.route('/login')
def login():
    authorization_url, state = client.prepare_authorization_request(
        GOOGLE_AUTH_URI,
        redirect_uri=redirect_uri,
        scope=["https://www.googleapis.com/auth/youtube"]
    )
    session["oauth_state"] = state
    return redirect(authorization_url)

@app.route('/oauth2callback')
def callback():
    # Use the authorization response to get a token
    token_url, headers, body = client.prepare_token_request(
        GOOGLE_TOKEN_URI,
        authorization_response=request.url,
        redirect_url=request.base_url,
        code=request.args.get('code')
    )
    token_response = requests.post(
        token_url,
        headers=headers,
        data=body,
        auth=(client_id, client_secret),
    )
    client.parse_request_body_response(token_response.text)

    # Now you can use this to authorize yt-dlp downloads
    return redirect(url_for("index"))

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

progress_data = {}

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
            # yt-dlp options including the cookies file
            ydl_opts = {
                'format': f'best[height<={resolution[:-1]}][ext=mp4]/best[ext=mp4]',
                'outtmpl': f'static/downloads/output_{download_id}.%(ext)s',
                'progress_hooks': [lambda d: update_progress(download_id, d)],
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
