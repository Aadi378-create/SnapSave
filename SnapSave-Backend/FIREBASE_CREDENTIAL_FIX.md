# Firebase INVALID_APP_CREDENTIAL Error - Complete Fix Guide

## What Was Wrong
Your code was trying to use Firebase Admin SDK to verify authentication tokens, but the service account credentials file was either:
- ❌ Expired or invalid
- ❌ Deleted/regenerated in Firebase Console
- ❌ For a different Firebase project
- ❌ Lacking necessary permissions

## Changes Made (Applied)
✅ Added fallback logic if Firebase credentials fail to initialize
✅ Improved error logging to show exactly what's failing
✅ Code now uses Google public certificate verification as backup

## Complete Fix Steps

### Step 1: Regenerate Firebase Service Account Key (REQUIRED)
1. Open [Firebase Console](https://console.firebase.google.com)
2. Select your project: **snapsave-501c7**
3. Go to **Project Settings** (gear icon) → **Service Accounts** tab
4. Click **Generate New Private Key** button
5. Save the downloaded JSON file

### Step 2: Replace Your Credentials File
```bash
# Copy the new credentials file to your project
cp ~/Downloads/snapsave-501c7-xxxxx.json ./admin/firebase-service-account.json
```

### Step 3: Update .env (if path is different)
If your Firebase credentials file is in a different location, update `.env`:
```env
FIREBASE_CREDENTIALS=path/to/your/firebase-service-account.json
```

### Step 4: Restart Server
```bash
# Kill current server (Ctrl+C in terminal)
# Then restart:
python -m uvicorn api.server:app --host 127.0.0.1 --port 8000 --reload
```

### Step 5: Test Authentication
```bash
# Get a test token
curl http://localhost:8000/api/auth/test-token

# Use it to call a protected endpoint
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8000/api/auth/me
```

## What to Look For in Terminal

### ✅ Success Indicators:
```
✓ Firebase Admin SDK initialized with Service Account.
✓ Token verified using Firebase Admin SDK
```

### ⚠️ Warning (Fallback in Use):
```
⚠️  Firebase Admin SDK token verification failed: INVALID_APP_CREDENTIAL
    Falling back to manual verification...
✓ Token verified using manual Google certificate verification
```

This warning means Firebase credentials are invalid, but your app still works because it falls back to manual verification.

## If You See This Error

**The error:**
```json
{
  "error": {
    "code": 400,
    "message": "INVALID_APP_CREDENTIAL"
  }
}
```

**Causes:**
1. Service account was deleted in Firebase → Regenerate (Step 1-2 above)
2. Credentials file is corrupted → Replace with new one
3. Firebase project doesn't exist or was deleted → Check Firebase Console
4. Environment variable path is wrong → Verify `.env` file

## Permanent Fix
To avoid this in the future:
1. Treat `firebase-service-account.json` as sensitive (add to `.gitignore`)
2. Store credentials in environment variables: `FIREBASE_CREDENTIALS=/absolute/path/to/creds.json`
3. Set up proper service account permissions in Firebase Console
4. Regenerate keys every 90 days for security

## Need Help?
If the error persists after regenerating credentials:
1. Check that `.env` has correct path to credentials file
2. Verify `snapsave-501c7` is the correct Firebase project ID
3. Ensure the service account has "Editor" role in Firebase Console
4. Look at terminal output for detailed error messages
