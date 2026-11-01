# JARVIS

Mobile-first personal dashboard: today's food, workout, timetable, month schedule, resources, reminders and an "Ask JARVIS" voice/chat box. Installable as an app (PWA). Plain HTML, CSS and JS, no build step.

## Run locally
```bash
python3 -m http.server 8000      # then open http://localhost:8000
```

## Deploy (free, pick one)
- **Vercel / Netlify:** import this GitHub repo, framework "Other", no build command, output directory = root.
- **GitHub Pages:** Settings > Pages > Deploy from branch `main`, folder `/ (root)`.

You get an HTTPS link. Open it on your phone: Android Chrome shows **Install app**; on iPhone use Share > **Add to Home Screen**.

## Connect the AI chat
Edit `config.js` and set `window.JARVIS_API` to your deployed backend URL (the Flask server, e.g. on Render). The first question that needs the backend asks for your `AURA_API_KEY`. It is stored only in your browser. Never put the key in this repo.
Food, timetable and deadline questions are answered on the page itself and work without a backend.

## Change the icon
Replace the files in `icons/` (`icon-192.png`, `icon-512.png`, `icon-maskable-512.png`, `apple-touch-icon.png`, `favicon-32.png`) and bump `C` in `sw.js` (e.g. `jarvis-v3`) so phones refresh the cache.

## Reminders
Tap **Turn on reminders** on Home. They fire while the app is open or running in the background. Alerts when the app is fully closed need a Web Push server.

## Edit your data
Menu, workouts and timetable live at the top of the `<script>` in `index.html` (`BD`, `GYM`, `TL`). Events, weights and checklists are saved in your browser. After changing the defaults, bump the storage key `jarvis_v2` so old saved data doesn't hide your edits.
