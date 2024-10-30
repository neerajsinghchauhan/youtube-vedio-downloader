from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from flask_cors import CORS
from google_auth_oauthlib.flow import Flow
import yt_dlp
import os
import threading
import time
import logging

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get('FLASK_SECRET_KEY')

CLIENT_SECRETS_FILE = 'client_secret.json'
REDIRECT_URI = 'https://youtube-vedio-downloader-7neeraj.onrender.com/oauth2callback'

# Store download progress data
progress_data = {}

# Initialize logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

@app.route('/')
def index():
    # Check if user is authenticated
    if 'credentials' not in session:
        return redirect(url_for('authorize'))  # Redirect to Google OAuth2 flow if not authenticated
    return render_template('index.html')  # Render download page if authenticated

@app.route('/authorize')
def authorize():
    # Initiate OAuth2 flow
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=['https://www.googleapis.com/auth/youtube'],
        redirect_uri=REDIRECT_URI
    )
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )
    session['state'] = state
    return redirect(authorization_url)

@app.route('/oauth2callback')
def oauth2callback():
    # Complete OAuth2 flow
    state = session.get('state')
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=['https://www.googleapis.com/auth/youtube'],
        state=state,
        redirect_uri=url_for("oauth2callback", _external=True)
    )
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials
    session['credentials'] = credentials_to_dict(credentials)
    return redirect(url_for("index"))  # Redirect to home page after successful login

def credentials_to_dict(credentials):
    return {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }

@app.route('/download', methods=['POST'])
def download_video():
    if "credentials" not in session:
        return redirect(url_for("authorize"))

    data = request.json
    url = data["url"]
    resolution = data["format"]

    # Generate unique download ID
    download_id = str(int(time.time()))
    progress_data[download_id] = {"status": "Starting", "progress": 0}

    def download():
        try:
            # Use OAuth2 token in yt-dlp options
            ydl_opts = {
                "format": f"best[height<={resolution[:-1]}][ext=mp4]/best[ext=mp4]",
                "outtmpl": f"static/downloads/output_{download_id}.%(ext)s",
                "progress_hooks": [lambda d: update_progress(download_id, d)],
                "cookiesfrombrowser": ("chrome", "User Data", "Profile 1") # Include if required
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            progress_data[download_id] = {'status': 'done', 'progress': 100}
        except Exception as e:
            progress_data[download_id] = {'status': 'error', 'progress': str(e)}

    threading.Thread(target=download).start()
    return jsonify({"download_id": download_id})

@app.route('/progress/<download_id>')
def progress(download_id):
    return jsonify(progress_data.get(download_id, {'status': 'Not found', 'progress': 0}))

def update_progress(download_id, d):
    if d['status'] == 'downloading':
        progress_data[download_id] = {'status': 'downloading', 'progress': d.get('percentage', 0)}
    elif d['status'] == 'finished':
        progress_data[download_id] = {'status': 'done', 'progress': 100}

if __name__ == '__main__':
    os.makedirs('static/downloads', exist_ok=True)
    app.run(debug=True)
