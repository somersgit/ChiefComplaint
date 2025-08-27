# Deployment Guide for Patient-Resident-Attending Chatbot

This guide will help you deploy your chatbot to make it available online through GitHub and Render.

## Prerequisites

1. **GitHub Account**: You'll need a GitHub account to host your code
2. **Render Account**: Sign up at [render.com](https://render.com) for free hosting
3. **Environment Variables**: You'll need to configure API keys and other sensitive data

## Step 1: Prepare Your Code for GitHub

### 1.1 Initialize Git Repository (if not already done)
```bash
cd /Users/omersadat/Documents/patient_resident_attending_chatbot
git init
git add .
git commit -m "Initial commit: Patient-Resident-Attending Chatbot"
```

### 1.2 Create GitHub Repository
1. Go to [github.com](https://github.com) and sign in
2. Click the "+" icon in the top right corner
3. Select "New repository"
4. Name it: `patient-resident-attending-chatbot`
5. Make it public (so Render can access it)
6. Don't initialize with README (you already have one)
7. Click "Create repository"

### 1.3 Push Your Code to GitHub
```bash
git remote add origin https://github.com/YOUR_USERNAME/patient-resident-attending-chatbot.git
git branch -M main
git push -u origin main
```

## Step 2: Deploy to Render

### 2.1 Sign Up for Render
1. Go to [render.com](https://render.com)
2. Sign up with your GitHub account (recommended)

### 2.2 Create New Web Service
1. Click "New +" button
2. Select "Web Service"
3. Connect your GitHub repository
4. Select the `patient-resident-attending-chatbot` repository

### 2.3 Configure the Service
- **Name**: `patient-resident-attending-chatbot` (or any name you prefer)
- **Environment**: `Python 3`
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `gunicorn app.app:app`
- **Plan**: Free (for testing)

### 2.4 Set Environment Variables
Click on "Environment" tab and add these variables:

```
OPENAI_API_KEY=your_openai_api_key_here
CHROMA_DIR=.chroma_db
CASE_HISTORY_PDF=./data/case_history.pdf
CASE_EXAM_PDF=./data/case_exam.pdf
ASSIGNED_DIAGNOSIS=Pneumonia
```

**Important**: Replace `your_openai_api_key_here` with your actual OpenAI API key.

### 2.5 Deploy
1. Click "Create Web Service"
2. Render will automatically build and deploy your application
3. Wait for the build to complete (usually 2-5 minutes)

## Step 3: Access Your Deployed Chatbot

Once deployment is successful:
1. Render will provide you with a URL like: `https://your-app-name.onrender.com`
2. Click on the URL to access your chatbot
3. Share this URL with others to let them use your chatbot

## Step 4: Update GitHub with Deployment Info

### 4.1 Update README.md
Add deployment information to your README:

```markdown
## Live Demo

Try the chatbot online: [https://your-app-name.onrender.com](https://your-app-name.onrender.com)

## Deployment

This application is deployed on Render. See [DEPLOYMENT.md](DEPLOYMENT.md) for details.
```

### 4.2 Push Changes
```bash
git add .
git commit -m "Add deployment information"
git push
```

## Troubleshooting

### Common Issues:

1. **Build Failures**: Check the build logs in Render dashboard
2. **Environment Variables**: Ensure all required environment variables are set
3. **Port Issues**: The app is configured to use the PORT environment variable from Render
4. **Dependencies**: All required packages are in requirements.txt

### Debugging:
- Check Render logs in the dashboard
- Verify environment variables are set correctly
- Ensure your PDF files are committed to GitHub

## Alternative Deployment Options

### Heroku
- Use the `Procfile` and `runtime.txt` files
- Deploy using Heroku CLI or GitHub integration

### Railway
- Similar to Render, supports Python applications
- Good free tier for testing

### Vercel
- Primarily for frontend, but can work with Flask
- Requires additional configuration

## Security Notes

1. **API Keys**: Never commit API keys to GitHub
2. **Environment Variables**: Use Render's environment variable system
3. **PDF Files**: Your case PDFs will be publicly accessible if the repo is public
4. **Rate Limiting**: Consider adding rate limiting for production use

## Next Steps

1. **Custom Domain**: Add a custom domain in Render settings
2. **Monitoring**: Set up logging and monitoring
3. **Scaling**: Upgrade to paid plans for better performance
4. **CI/CD**: Set up automatic deployments on code changes

## Support

- **Render Documentation**: [docs.render.com](https://docs.render.com)
- **GitHub Help**: [help.github.com](https://help.github.com)
- **Flask Deployment**: [flask.palletsprojects.com/en/2.3.x/deploying/](https://flask.palletsprojects.com/en/2.3.x/deploying/)

Your chatbot should now be accessible online through a shareable link! 🚀
