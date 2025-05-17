# B2B Persona Generator

A Flask-based web application that generates detailed B2B buyer personas using OpenAI's GPT model.

## Features

- Generate detailed B2B buyer personas based on role, industry, and company size
- Modern, responsive UI built with Vue.js and Tailwind CSS
- Copy generated personas to clipboard
- Error handling and loading states

## Setup

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file in the root directory with your OpenAI API key:
```
OPENAI_API_KEY=your_api_key_here
SECRET_KEY=your_secret_key_here
```

4. Run the application:
```bash
python app.py
```

The application will be available at `http://localhost:5004`

## Usage

1. Enter the role/title of the persona you want to generate
2. Optionally specify the industry and company size
3. Click "Generate Persona"
4. Review the generated persona
5. Use the "Copy to Clipboard" button to copy the persona

## Requirements

- Python 3.9+
- OpenAI API key
- Modern web browser with JavaScript enabled 