from flask import Flask, request, jsonify, render_template, redirect, url_for, session, send_file
from flask_cors import CORS
from google_auth_oauthlib.flow import Flow
import yt_dlp
import os
import threading
import time
import logging

app = Flask(__name__)
CORS(app)

# Flask secret key for sessions
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your_default_secret_key')

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

progress_data = {}

# Load client secrets from environment or file
CLIENT_SECRETS_FILE = 'client_secret.json'
REDIRECT_URI = 'https://youtube-vedio-downloader-7neeraj.onrender.com/oauth2callback'

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def download_video():
    # Initiate OAuth flow for user authorization
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=['https://www.googleapis.com/auth/youtube.readonly'],
        redirect_uri=REDIRECT_URI
    )

    # Generate the authorization URL
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )

    # Save the state in session to verify in callback
    session['state'] = state

    # Redirect user to Google's OAuth consent screen
    return redirect(authorization_url)

@app.route('/oauth2callback')
def oauth2callback():
    # Ensure that state matches for security
    state = session['state']
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=['https://www.googleapis.com/auth/youtube.readonly'],
        redirect_uri=REDIRECT_URI,
        state=state
    )

    # Complete the OAuth2 authorization flow
    flow.fetch_token(authorization_response=request.url)

    # Store credentials for API requests
    credentials = flow.credentials
    session['credentials'] = credentials_to_dict(credentials)

    # Now you can use these credentials to authorize yt-dlp downloads
    return redirect(url_for("index"))

def credentials_to_dict(credentials):
    # Convert credentials object to a dictionary to store in session
    return {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }

@app.route('/start_download', methods=['POST'])
def start_download():
    # This endpoint initiates the actual video download
    data = request.json
    url = data['url']
    resolution = data['format']
    download_id = str(int(time.time()))  # Unique ID for download tracking
    progress_data[download_id] = {'status': 'Starting', 'progress': 0}

    def download():
        # Use credentials for authenticated requests with yt-dlp
        ydl_opts = {
            'format': f'best[height<={resolution[:-1]}][ext=mp4]',
            'outtmpl': f'static/downloads/output_{download_id}.%(ext)s',
            'progress_hooks': [lambda d: update_progress(download_id, d)],
            'cookiefile': 'cookies.txt',  # Optional: replace with your cookie file if needed
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            progress_data[download_id] = {'status': 'done', 'progress': 100}
        except Exception as e:
            logger.error(f"Error during download: {str(e)}")
            progress_data[download_id] = {'status': 'error', 'progress': str(e)}

    # Start the download in a new thread
    threading.Thread(target=download).start()
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
