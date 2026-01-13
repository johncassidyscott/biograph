# Deploy BioGraph to the Web

Make your BioGraph accessible from anywhere! Choose one of these options:

---

## Option 1: Railway (Recommended - Easiest)

Railway offers free hosting with minimal configuration.

### Steps:

1. **Sign up** at [railway.app](https://railway.app) (free with GitHub)

2. **Create New Project**
   - Click "New Project"
   - Select "Deploy from GitHub repo"
   - Choose your `biograph` repository

3. **Add Environment Variable**
   - In your Railway project, click "Variables"
   - Add: `DATABASE_URL` = `your_neon_postgres_url`

4. **Deploy!**
   - Railway will automatically detect the `railway.json` config
   - Wait 2-3 minutes for build and deployment
   - You'll get a public URL like: `https://biograph-production.up.railway.app`

**That's it!** Your graph is now online.

---

## Option 2: Render

Render also offers free hosting with automatic deploys from GitHub.

### Steps:

1. **Sign up** at [render.com](https://render.com) (free)

2. **New Web Service**
   - Click "New +" → "Web Service"
   - Connect your GitHub repo

3. **Configure**
   - Name: `biograph`
   - Environment: `Python 3`
   - Build Command: `pip install -r backend/requirements.txt`
   - Start Command: `cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT`

4. **Add Environment Variable**
   - Add: `DATABASE_URL` = `your_neon_postgres_url`

5. **Create Web Service**
   - Render will build and deploy
   - You'll get a URL like: `https://biograph.onrender.com`

**Note:** Free tier may sleep after inactivity (slow first load).

---

## Option 3: Fly.io

For more control and better performance.

### Steps:

1. **Install Fly CLI**
   ```bash
   curl -L https://fly.io/install.sh | sh
   ```

2. **Login**
   ```bash
   fly auth login
   ```

3. **Launch App**
   ```bash
   cd biograph
   fly launch
   ```

4. **Set Database URL**
   ```bash
   fly secrets set DATABASE_URL="your_neon_postgres_url"
   ```

5. **Deploy**
   ```bash
   fly deploy
   ```

You'll get a URL like: `https://biograph.fly.dev`

---

## Option 4: GitHub Codespaces

If you have GitHub Codespaces, you can make your dev environment public.

1. **Open in Codespaces**
   - Open your repo in GitHub Codespaces

2. **Start the server**
   ```bash
   cd backend
   export DATABASE_URL="your_neon_postgres_url"
   ./dev.sh
   ```

3. **Make Port Public**
   - In Codespaces, go to the "Ports" tab
   - Find port 8000
   - Right-click → "Port Visibility" → "Public"

4. **Share the URL**
   - Copy the forwarded address (looks like: `https://xyz-8000.app.github.dev`)

**Note:** This URL changes each session and requires Codespaces to be running.

---

## After Deployment

### Load Your Data

Once deployed, you need to populate the database:

1. **SSH into your deployment** (Railway/Render provide shell access)

2. **Run the build script**
   ```bash
   cd backend
   python3 build_graph.py
   ```

3. **Wait** ~10-20 minutes for all data to load

### Verify It Worked

Visit your deployed URL - you should see:
- Stats showing diseases, drugs, trials
- Working "Explore Entities" buttons
- Data in the relationships tab

---

## Troubleshooting

**500 Error / App won't start:**
- Check that `DATABASE_URL` environment variable is set
- Verify the DATABASE_URL is correct (copy from Neon dashboard)

**No data showing:**
- Run `build_graph.py` to populate the database
- Check logs in your hosting dashboard

**Slow to load:**
- Free tiers may have cold starts (first load takes 30-60 seconds)
- Subsequent loads should be fast

**Build fails:**
- Make sure `requirements.txt` is in the `backend/` directory
- Check Python version (3.11+ recommended)

---

## Updating Your Deployment

All platforms support auto-deploy from GitHub:

1. **Make changes** locally
2. **Commit and push** to GitHub
3. **Automatic redeploy** (takes 2-3 minutes)

---

## Cost

All options above have **free tiers** that are perfect for POC/demo:

- **Railway**: 500 hours/month free (plenty for demos)
- **Render**: Free tier (sleeps after 15 min inactivity)
- **Fly.io**: 3 free VMs
- **Codespaces**: 60 hours/month free

For production, you'd upgrade to paid plans ($5-20/month).

---

## Sharing Your Demo

Once deployed, share your URL with:
- Friends: "Check out my knowledge graph: https://your-url.com"
- Colleagues: Add to your resume/portfolio
- Investors: Live demo without laptop

The UI looks professional and the data is real! 🚀

---

Need help? Check the logs in your hosting platform's dashboard.
