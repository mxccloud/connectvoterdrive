# ConnectVote - Voter Information Bot

A Flask web application that automates voter information retrieval from the South African Electoral Commission (IEC) website. The application features a multi-step form for capturing comprehensive voter data and integrates with 2Captcha service to solve reCAPTCHA challenges.

## 🌟 Features

- **Automated Voter Verification**: Retrieves real voter information from IEC website
- **Multi-step Data Capture**: Comprehensive 9-step form for voter profiling
- **reCAPTCHA Automation**: Automatically solves CAPTCHAs using 2Captcha service
- **Responsive Design**: Mobile-friendly web interface
- **Rate Limiting**: Prevents API abuse with request limits
- **Headless Browser**: Uses Selenium with Chrome in headless mode
- **Data Export**: Saves voter information as JSON files

## 🚀 Quick Deployment

### Option 1: Railway (Recommended - Easiest)

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template/your-template-id)

1. Fork this repository
2. Go to [Railway](https://railway.app)
3. Click "New Project" → "Deploy from GitHub repo"
4. Select your forked repository
5. Add environment variables (see below)
6. Deploy!

### Option 2: Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

1. Fork this repository
2. Go to [Render](https://render.com)
3. Create a new "Web Service"
4. Connect your GitHub repository
5. Use these settings:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python 9bot.py`
6. Add environment variables

### Option 3: Heroku

```bash
# Create Heroku app
heroku create your-app-name

# Add buildpacks
heroku buildpacks:add heroku/python
heroku buildpacks:add heroku/chromedriver
heroku buildpacks:add heroku/google-chrome

# Set environment variables
heroku config:set TWO_CAPTCHA_API_KEY=your_api_key_here

# Deploy
git push heroku main