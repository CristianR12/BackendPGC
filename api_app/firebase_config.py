import os, json, firebase_admin
from firebase_admin import credentials

firebase_json = os.environ.get("FIREBASE_CREDENTIALS")
cred = credentials.Certificate(json.loads(firebase_json))
firebase_admin.initialize_app(cred)
