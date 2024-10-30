from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from flask_cors import CORS
from google_auth_oauthlib.flow import Flow
import yt_dlp
import os
import threading
import time
import logging
from google.auth.transport.requests import Request

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get('FLASK_SECRET_KEY')

# Environment variables for Google OAuth credentials
CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
SCOPE = "https://www.googleapis.com/auth/youtube.readonly"

# URLs for Google’s OAuth device flow
DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# In-memory storage of access token and refresh token
credentials = None
# Store download progress data
progress_data = {}

# Initialize logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

@app.route('/')
def index():
    # Check if credentials are already present and valid
    if credentials and "access_token" in credentials:
        return render_template("index.html", message="You are already signed in!")
    return redirect("/authorize")

@app.route('/authorize')
def authorize():
    # Request a device code for user authentication
    response = request.post(
        DEVICE_CODE_URL,
        data={
            "client_id": CLIENT_ID,
            "scope": SCOPE,
        }
    )
    result = response.json()
    
    # Extract the necessary information for the user
    user_code = result.get("user_code")
    device_code = result.get("device_code")
    verification_url = result.get("verification_url")
    
    # Start polling for the access token
    threading.Thread(target=poll_for_token, args=(device_code,)).start()
    
    # Show instructions to the user
    return render_template("device_login.html", verification_url=verification_url, user_code=user_code)

# Polling function to request access token after user authorizes
def poll_for_token(device_code):
    global credentials
    while True:
        response = request.post(
            TOKEN_URL,
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            }
        )
        token_response = response.json()

        if "access_token" in token_response:
            credentials = token_response  # Store the access and refresh token
            print("Authorization successful!")
            break
        elif token_response.get("error") == "authorization_pending":
            time.sleep(5)  # Polling interval
        else:
            print("Authorization failed:", token_response)
            break


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
    global credentials
    if not credentials or "access_token" not in credentials:
        return redirect("/authorize")

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
                "youtube_include_dash_manifest": False,
                "external_downloader_args": ["--access-token", credentials["access_token"]]
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
