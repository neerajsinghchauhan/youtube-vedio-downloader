from flask import Flask, request, jsonify, redirect, url_for, session, render_template, send_file
from flask_cors import CORS
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
import yt_dlp
import os
import threading
import time
import logging

app = Flask(__name__)
CORS(app, supports_credentials=True)

app.secret_key = os.environ.get('FLASK_SECRET_KEY')  # Set in environment variables
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize progress tracking dictionary
progress_data = {}

# Setup OAuth 2.0 client
client_secrets_file = "client_secret.json"  # Ensure this path is correct in your deployment
redirect_uri = "https://youtube-vedio-downloader-7neeraj.onrender.com/oauth2callback"
scopes = ['https://www.googleapis.com/auth/youtube.readonly']

# Endpoint to handle OAuth flow
@app.route('/authorize')
def authorize():
    flow = Flow.from_client_secrets_file(client_secrets_file, scopes=scopes)
    flow.redirect_uri = redirect_uri
    authorization_url, state = flow.authorization_url(access_type='offline', include_granted_scopes='true')
    session['state'] = state
    return redirect(authorization_url)

@app.route('/oauth2callback')
def oauth2callback():
    state = session['state']
    flow = Flow.from_client_secrets_file(client_secrets_file, scopes=scopes, state=state)
    flow.redirect_uri = redirect_uri
    authorization_response = request.url
    flow.fetch_token(authorization_response=authorization_response)

    # Save credentials to the session
    credentials = flow.credentials
    session['credentials'] = credentials_to_dict(credentials)
    
    return redirect(url_for("index"))

def credentials_to_dict(credentials):
    return {'token': credentials.token, 'refresh_token': credentials.refresh_token, 'token_uri': credentials.token_uri,
            'client_id': credentials.client_id, 'client_secret': credentials.client_secret}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def download_video():
    if 'credentials' not in session:
        return redirect(url_for('authorize'))

    # Retrieve the credentials from the session
    credentials_info = session['credentials']
    credentials = Credentials(**credentials_info)

    data = request.json
    url = data['url']
    resolution = data['format']
    download_id = str(int(time.time()))
    progress_data[download_id] = {'status': 'Starting', 'progress': 0}

    def download():
        # Define yt-dlp options with headers
        ydl_opts = {
            'format': f'best[height<={resolution[:-1]}][ext=mp4]/best[ext=mp4]',
            'outtmpl': f'static/downloads/output_{download_id}.%(ext)s',
            'progress_hooks': [lambda d: update_progress(download_id, d)],
            'http_headers': {'Authorization': f'Bearer {credentials.token}'},  # Pass OAuth token here
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            progress_data[download_id] = {'status': 'done', 'progress': 100}

        except Exception as e:
            logger.error(f"Error during download: {str(e)}")
            progress_data[download_id] = {'status': 'error', 'progress': str(e)}

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
