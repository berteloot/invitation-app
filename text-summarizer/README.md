# Text Summarizer

A modern web application that generates concise summaries of text content, optimized for audio consumption.

## Features

- Clean, modern user interface
- Customizable word count for summaries
- Optional custom prompts for summarization
- Real-time feedback and error handling
- Responsive design for all devices

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

3. Create a `.env` file in the project root:
```
OPENAI_API_KEY=your_api_key_here
```

4. Run the application:
```bash
python app.py
```

5. Open your browser and navigate to `http://localhost:5000`

## Usage

1. Enter the text you want to summarize
2. Specify the desired word count
3. Optionally provide custom instructions for the summarization
4. Click "Generate Summary"
5. View your generated summary with the actual word count

## Technologies Used

- Flask (Backend)
- OpenAI GPT-3.5 (Summarization)
- Tailwind CSS (Styling)
- Font Awesome (Icons) 