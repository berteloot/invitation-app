from flask import Flask, render_template, request, jsonify
from openai import OpenAI
import os
from dotenv import load_dotenv
from flask_cors import CORS

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Initialize OpenAI client
api_key = os.getenv('OPENAI_API_KEY')
if not api_key:
    raise ValueError("OPENAI_API_KEY environment variable is not set")

client = OpenAI(api_key=api_key)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/summarize', methods=['POST'])
def summarize():
    try:
        # Check if request has JSON data
        if not request.is_json:
            return jsonify({'error': 'Request must be JSON'}), 400

        data = request.get_json()
        text = data.get('text', '').strip()
        word_count = data.get('word_count', 0)
        custom_prompt = data.get('prompt', '').strip()

        # Validate inputs
        if not text:
            return jsonify({'error': 'Please enter text to summarize'}), 400
        
        try:
            word_count = int(word_count)
            if word_count < 1:
                raise ValueError
        except ValueError:
            return jsonify({'error': 'Please enter a valid word count (minimum 1)'}), 400

        # Default prompt if none provided
        if not custom_prompt:
            custom_prompt = f"""Summarize the following text in exactly {word_count} words. 
            Maintain the original tone and key message while being concise and clear. 
            Optimize for audio consumption with natural, listener-friendly language."""

        try:
            # Call OpenAI API
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a professional summarization assistant."},
                    {"role": "user", "content": f"{custom_prompt}\n\nText to summarize:\n{text}"}
                ],
                max_tokens=500,
                temperature=0.7
            )

            summary = response.choices[0].message.content.strip()
            actual_word_count = len(summary.split())

            return jsonify({
                'summary': summary,
                'word_count': actual_word_count
            })

        except Exception as api_error:
            print(f"OpenAI API Error: {str(api_error)}")
            return jsonify({'error': f'Error with OpenAI API: {str(api_error)}'}), 500

    except Exception as e:
        print(f"Server Error: {str(e)}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000) 