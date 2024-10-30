# app.py
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from flask_cors import CORS
import yt_dlp
import os
import threading
import time
import logging
from google.auth.transport.requests import Request
import requests
import json
from urllib.parse import urlparse, parse_qs

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your-default-secret-key')

# Environment variables for Google OAuth credentials
CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
SCOPE = "https://www.googleapis.com/auth/youtube.readonly"

# URLs for Google's OAuth device flow
DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# In-memory storage
credentials = None
progress_data = {}
device_codes = {}

# Initialize logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def get_video_info(url, access_token):
    try:
        video_id = None
        parsed_url = urlparse(url)
        
        if 'youtube.com' in parsed_url.netloc:
            query_params = parse_qs(parsed_url.query)
            video_id = query_params.get('v', [None])[0]
        elif 'youtu.be' in parsed_url.netloc:
            video_id = parsed_url.path[1:]
            
        if not video_id:
            raise ValueError("Invalid YouTube URL")

        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json'
        }
        
        api_url = f"https://www.googleapis.com/youtube/v3/videos?id={video_id}&part=snippet,contentDetails"
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        
        return response.json()
    except Exception as e:
        logger.error(f"Error fetching video info: {str(e)}")
        return None

@app.route('/')
def index():
    if credentials and "access_token" in credentials:
        return render_template("index.html", authorized=True)
    return redirect("/authorize")

@app.route('/authorize')
def authorize():
    try:
        params = {
            'client_id': CLIENT_ID,
            'scope': SCOPE,
        }
        response = requests.post(DEVICE_CODE_URL, data=params)
        response.raise_for_status()

        data = response.json()
        logger.debug(f"Device authorization response: {data}")

        device_codes[data['device_code']] = {
            'user_code': data['user_code'],
            'verification_url': data['verification_url'],
            'expires_in': data['expires_in'],
            'interval': data.get('interval', 5),
            'timestamp': time.time()
        }

        threading.Thread(
            target=poll_for_token, 
            args=(data['device_code'],),
            daemon=True
        ).start()
        
        return render_template(
            "device_login.html", 
            verification_url=data['verification_url'], 
            user_code=data['user_code']
        )

    except Exception as e:
        logger.error(f"Authorization error: {str(e)}")
        return jsonify({"error": "Authorization failed"}), 500

@app.route('/download', methods=['POST'])
def download_video():
    global credentials
    if not credentials or "access_token" not in credentials:
        return jsonify({"error": "Not authorized"}), 401

    try:
        data = request.json
        url = data.get("url")
        resolution = data.get("format", "360p")
        
        if not url:
            return jsonify({"error": "URL is required"}), 400

        # Generate unique download ID
        download_id = str(int(time.time()))
        progress_data[download_id] = {"status": "Starting", "progress": 0}

        # Get video info using OAuth
        video_info = get_video_info(url, credentials["access_token"])
        if not video_info:
            return jsonify({"error": "Could not fetch video information"}), 400

        def download():
            try:
                ydl_opts = {
                    "format": f"bestvideo[height<={resolution[:-1]}][ext=mp4]+bestaudio[ext=m4a]/best[height<={resolution[:-1]}][ext=mp4]/best[ext=mp4]",
                    "outtmpl": f"static/downloads/%(title)s_{download_id}.%(ext)s",
                    "progress_hooks": [lambda d: update_progress(download_id, d)],
                    "youtube_include_dash_manifest": True,
                    "quiet": False,
                    "no_warnings": False,
                    "extractaudio": False,
                    "http_headers": {
                        "Authorization": f"Bearer {credentials['access_token']}"
                    }
                }

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                
                progress_data[download_id]["status"] = "done"
                progress_data[download_id]["progress"] = 100
                
            except Exception as e:
                logger.error(f"Download error: {str(e)}")
                progress_data[download_id] = {
                    "status": "error",
                    "error": str(e),
                    "progress": 0
                }

        threading.Thread(target=download, daemon=True).start()
        return jsonify({"download_id": download_id})

    except Exception as e:
        logger.error(f"Download request error: {str(e)}")
        return jsonify({"error": str(e)}), 500

def poll_for_token(device_code):
    global credentials
    
    if device_code not in device_codes:
        logger.error("Invalid device code for polling")
        return

    device_data = device_codes[device_code]
    interval = device_data['interval']
    start_time = time.time()

    while time.time() - start_time < device_data['expires_in']:
        try:
            response = requests.post(
                TOKEN_URL,
                data={
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
                }
            )
            response.raise_for_status()
            token_data = response.json()

            if "access_token" in token_data:
                credentials = token_data
                logger.info("Device authorization successful!")
                del device_codes[device_code]
                return
            
            if token_data.get("error") == "authorization_pending":
                logger.debug("Authorization pending, continuing to poll...")
                time.sleep(interval)
                continue
                
            if token_data.get("error") in ["slow_down", "rate_limit_exceeded"]:
                interval = min(interval * 2, 15)
                logger.warning(f"Rate limit hit, increasing interval to {interval}")
                time.sleep(interval)
                continue
                
            logger.error(f"Token request failed: {token_data.get('error')}")
            break

        except Exception as e:
            logger.error(f"Polling error: {str(e)}")
            time.sleep(interval)

    if device_code in device_codes:
        del device_codes[device_code]
    logger.warning("Device authorization polling timed out")

@app.route('/progress/<download_id>')
def progress(download_id):
    return jsonify(progress_data.get(download_id, {'status': 'Not found', 'progress': 0}))

def update_progress(download_id, d):
    if d['status'] == 'downloading':
        total = d.get('total_bytes')
        downloaded = d.get('downloaded_bytes')
        if total and downloaded:
            percentage = (downloaded / total) * 100
        else:
            percentage = 0
        progress_data[download_id] = {
            'status': 'downloading',
            'progress': percentage,
            'speed': d.get('speed', 0),
            'eta': d.get('eta', 0)
        }
    elif d['status'] == 'finished':
        progress_data[download_id]['status'] = 'processing'
        progress_data[download_id]['progress'] = 95  # Processing stage

if __name__ == '__main__':
    os.makedirs('static/downloads', exist_ok=True)
    app.run(debug=True)