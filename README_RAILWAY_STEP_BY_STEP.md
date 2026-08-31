# Pössl Cloud Backend V2.0

Step 1: create a PRIVATE GitHub repo, e.g. `possl-camper-backend`.

From this folder:

git init
git add .
git commit -m "Initial Pössl cloud backend"
git branch -M main
git remote add origin YOUR_GITHUB_REPO_URL
git push -u origin main

Do NOT upload `.env`.

Step 2: create a Railway project and deploy from that private GitHub repo.

Step 3: add Railway Variables using `.env.example` as a checklist.

Step 4: create a Railway Volume mounted at `/data`.

Step 5: generate a public Railway domain.

Test:
https://YOUR-DOMAIN/health

Expected:
ok = true
mqtt_connected = true

Step 6: change the mobile app backend URL from the LAN address to the Railway HTTPS URL and rebuild the standalone APK.
