# BioGraph PWA (Progressive Web App) Setup

BioGraph is now installable as a Progressive Web App! Users can add it to their home screen on any device (iOS, Android, desktop) for an app-like experience.

## What's Included

- ✅ **manifest.json** - App metadata and configuration
- ✅ **service-worker.js** - Offline caching and PWA functionality
- ✅ **icon.svg** - Scalable app icon (works on all modern browsers)
- ✅ **Updated index.html** - Manifest link and service worker registration

## How It Works

1. **Installability**: When users visit BioGraph on their phone/tablet, they'll see an "Add to Home Screen" prompt
2. **Offline Support**: The service worker caches essential resources for offline viewing
3. **App Experience**: Launches fullscreen without browser chrome (standalone mode)
4. **Cross-Platform**: Works on iOS, Android, Windows, Mac, Linux

## Testing the PWA

### Local Testing
1. Run the app locally or deploy to Render
2. Open in Chrome/Edge and look for the install icon in the address bar
3. On mobile Safari (iOS), tap Share → Add to Home Screen

### Production Testing
1. Deploy to Render (PWA requires HTTPS, which Render provides automatically)
2. Visit your Render URL on a mobile device
3. Look for the "Add to Home Screen" prompt

## Optional: Generate PNG Icons

The app currently uses SVG icons which work great on modern browsers. If you need traditional PNG icons for broader compatibility:

### Option 1: Use the Python Script (Recommended)
```bash
cd backend/app/static

# Install dependencies
pip install pillow cairosvg

# Generate PNG icons
python generate_icons.py
```

This will create:
- `icon-192.png` (192x192) - Android, Chrome
- `icon-512.png` (512x512) - Android splash screen, PWA install

### Option 2: Online Converter
1. Go to https://cloudconvert.com/svg-to-png
2. Upload `icon.svg`
3. Convert to 192x192 and save as `icon-192.png`
4. Convert to 512x512 and save as `icon-512.png`
5. Place both files in `backend/app/static/`

### Option 3: Use Existing SVG
The app is already configured to use SVG icons as fallback. Modern browsers support this perfectly!

## Customization

### Change App Colors
Edit `manifest.json`:
```json
{
  "theme_color": "#6366f1",      // Browser UI color
  "background_color": "#0f172a"  // Splash screen background
}
```

### Change App Name
Edit `manifest.json`:
```json
{
  "name": "Your Custom Name",
  "short_name": "ShortName"
}
```

### Update Caching Strategy
Edit `service-worker.js` to customize what gets cached offline.

## Browser Support

- ✅ Chrome/Edge (Android, Windows, Mac, Linux)
- ✅ Safari (iOS 11.3+, macOS 10.14+)
- ✅ Firefox (Android, Desktop)
- ✅ Samsung Internet
- ✅ Opera

## Deployment Notes

When you deploy to Render:
1. All PWA files are automatically included
2. HTTPS is enabled by default (required for PWA)
3. Service worker will register automatically
4. Users can install immediately

## Verifying PWA Installation

### Chrome DevTools
1. Open DevTools (F12)
2. Go to Application tab
3. Click "Manifest" to verify manifest.json
4. Click "Service Workers" to verify registration
5. Use Lighthouse to audit PWA score

### Testing Install Flow
1. Desktop Chrome: Look for install icon (⊕) in address bar
2. Mobile Chrome: Banner appears automatically
3. iOS Safari: Share → Add to Home Screen

## Troubleshooting

**Service worker not registering?**
- Check browser console for errors
- Ensure you're on HTTPS (Render provides this)
- Clear cache and hard reload (Ctrl+Shift+R)

**Icon not showing?**
- PNGs take priority over SVG if both exist
- Generate PNG icons using the script above
- Check browser console for 404 errors

**Install prompt not showing?**
- Some browsers require user engagement first
- Try clicking around the app, then reload
- iOS requires Share → Add to Home Screen manually

## What Users Will See

After installation:
- **App Icon**: On home screen/app drawer
- **Splash Screen**: Custom branded loading screen
- **Fullscreen**: No browser UI, feels native
- **Offline**: Basic functionality works offline
- **Fast**: Cached resources load instantly

## Future Enhancements

Consider adding:
- Push notifications for new data
- Background sync for offline edits
- App shortcuts (quick actions from home screen)
- Share target (share data TO BioGraph from other apps)

---

**Your BioGraph PWA is ready!** Deploy to Render and users can install it on any device. 🚀
