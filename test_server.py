from flask import Flask, send_from_directory
import os

app = Flask(__name__, static_url_path='', static_folder='.')

@app.route('/')
def root():
    """Serve the main page"""
    try:
        # Get absolute path to planB.html
        current_dir = os.getcwd()
        file_path = os.path.join(current_dir, 'planB.html')
        
        print(f"Full path to planB.html: {file_path}")
        print(f"File exists: {os.path.exists(file_path)}")
        
        # Return the file directly
        return send_from_directory(current_dir, 'planB.html')
    except Exception as e:
        print(f"Error serving planB.html: {str(e)}")
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Error</title>
        </head>
        <body>
            <h1>Error loading page</h1>
            <p>Could not load planB.html. Error: {str(e)}</p>
            <p>Current directory: {os.getcwd()}</p>
            <p>Files in directory: {', '.join(os.listdir('.'))}</p>
        </body>
        </html>
        """, 500, {'Content-Type': 'text/html'}

@app.route('/carrierlogos/<path:filename>')
def serve_carrier_logo(filename):
    """Serve carrier logo images"""
    return send_from_directory('carrierlogos', filename)

if __name__ == '__main__':
    app.run(debug=True, port=5002) 