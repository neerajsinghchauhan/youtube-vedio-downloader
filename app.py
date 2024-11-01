from flask import Flask, request, jsonify, render_template, redirect, url_for,send_file
from flask_cors import CORS
import yt_dlp
import os
import threading
import time
import logging
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
CORS(app)
# Check if CLIENT_ID and CLIENT_SECRET are set
print("Client ID:", os.getenv("CLIENT_ID"))
print("Client Secret:", os.getenv("CLIENT_SECRET"))

app.secret_key = os.getenv('FLASK_SECRET_KEY')
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
DEVICE_AUTH_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
progress_data = {}
access_token = None

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

@app.route('/')
def index():
    return render_template('index.html')

# New route to initiate device authorization
@app.route('/start_auth', methods=['POST'])
def start_auth():
    global access_token
    auth_response = requests.post(DEVICE_AUTH_URL, data={
        'client_id': CLIENT_ID,
        'scope': 'https://www.googleapis.com/auth/youtube.readonly'
    })
    auth_data = auth_response.json()

    # Display the device code and instructions
    device_code = auth_data.get('device_code')
    user_code = auth_data.get('user_code')
    verification_url = auth_data.get('verification_url')

    # Save the device code and start polling for access token
    threading.Thread(target=poll_for_token, args=(device_code,)).start()

    return jsonify({
        'device_code': user_code,
        'verification_url': verification_url,
        'device_code': device_code
        
    })

# Poll for token in a separate thread
def poll_for_token(device_code):
    global access_token
    while not access_token:
        response = requests.post(TOKEN_URL, data={
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'device_code': device_code,
            'grant_type': 'urn:ietf:params:oauth:grant-type:device_code'
        })
        result = response.json()
        if 'access_token' in result:
            access_token = result['access_token']
            print("Authorization successful!")
        elif 'error' in result and result['error'] == 'authorization_pending':
            time.sleep(5)  # Keep polling every 5 seconds

@app.route('/download', methods=['POST'])
def download_video():
    global access_token
    if not access_token:
        return jsonify({'error': 'Authorization required'}), 403

    data = request.json
    url = data['url']
    resolution = data['format']
    download_id = str(int(time.time()))
    progress_data[download_id] = {'status': 'Starting', 'progress': 0}

    def download():
        try:
            ydl_opts = {
                'format': f'best[height<={resolution[:-1]}][ext=mp4]/best[ext=mp4]',
                'outtmpl': f'static/downloads/output_{download_id}.%(ext)s',
                'progress_hooks': [lambda d: update_progress(download_id, d)],
                'cookiefile': None,  # Optional: add path to cookies if required
            }

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
