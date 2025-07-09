# Flux Wallpaper Collector (WPG)

WPG is a powerful tool for generating and managing AI-powered wallpaper datasets. It combines a user-friendly web interface with a flexible command-line tool, allowing you to create vast collections of wallpapers on any topic and seamlessly synchronize them with a Hugging Face Dataset repository.

This application is built with efficiency and user experience in mind, using FastAPI for the backend, along with HTMX and TailwindCSS for a responsive frontend without complex JavaScript.

-----

## ✨ Key Features

  * **Intuitive Web UI**: A modern interface to generate new datasets, browse image galleries by topic, and preview images in a lightbox.
  * **Intelligent Prompt Generation**: Leverages Google's Gemini AI to generate creative, detailed, and varied image prompts from a single topic name.
  * **Flexible Image Generation**: Integrates with any image generation API that can be called via a URL. The default configuration uses Pollinations.ai out-of-the-box.
  * **Hugging Face Integration**: Automatically synchronizes your local dataset (images and metadata) to a Hugging Face Dataset repository using a safe pull-merge-push strategy to prevent data loss.
  * **Powerful CLI**: A command-line interface for scripting and automating dataset generation and synchronization.
  * **Local-First Storage**: All data is stored locally in a SQLite database and an image folder, giving you full ownership and control.
  * **Efficient Serving**: Includes Gzip compression for a fast web UI and on-the-fly WebP conversion for optimized image delivery.

-----

## 🖼️ Web UI Preview

*The main dashboard where you can generate a new dataset and see a list of existing topics.*

*A clean, paginated image gallery for each topic.*

*A lightbox-style image preview with a direct download link.*

-----

## 🚀 Installation & Setup

### Prerequisites

  * Python 3.9+
  * A Google Generative AI API Key.
  * A Hugging Face account and an access token (if using the sync feature).

### Step-by-Step Guide

1.  **Clone the Repository**

    ```bash
    git clone https://github.com/arisris/flux-wallpaper-collector.git
    cd flux-wallpaper-collector
    ```

2.  **Create and Activate a Virtual Environment** (Recommended)

    ```bash
    # Windows
    python -m venv venv
    .\venv\Scripts\activate

    # macOS / Linux
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment Variables**
    Create a file named `.env` in the project's root directory. Copy the content below into it and fill in your secret keys. The script uses `python-dotenv` to load these variables automatically.

    **`.env` file**:

    ```env
    # Get your API Key from Google AI Studio (https://aistudio.google.com/app/apikey)
    GOOGLE_GENAI_API_KEY="YOUR_GOOGLE_API_KEY_HERE"

    # The Gemini model to use for prompt generation
    GOOGLE_GENAI_MODEL="gemini-2.5-flash-lite-preview-06-17"

    # (Optional) Your Hugging Face Dataset Repo ID (e.g., username/repo-name)
    HF_DATASET_REPO_ID="YOUR_HF_DATASET_REPO_ID_HERE"

    # (Optional) Your Hugging Face access token with write permissions (https://huggingface.co/settings/tokens)
    HF_SECRET="YOUR_HF_SECRET_TOKEN_HERE"

    # Image generator API URL Template.
    IMAGE_GENERATOR_URL_TEMPLATE="https://image.pollinations.ai/prompt/{prompt}?width={width}&height={height}&seed={seed}&nologo=true"
    ```

    **Important**: To keep your keys secure, add the `.env` file to your `.gitignore`:

    ```gitignore
    .env
    ```

-----

## 🎮 How to Use

### 1\. Web Interface

Run the FastAPI server using Uvicorn:

```bash
uvicorn wpg:app --host 0.0.0.0 --port 8000 --reload
```

Open your browser and navigate to `http://127.0.0.1:8000`.

  * **Generate Images**: Fill in the topic and number of images in the form and click "Generate Dataset". The topic list will refresh automatically upon completion.
  * **View Gallery**: Click any topic in the list to view its associated images.
  * **Sync**: Click the "Sync to Hugging Face" button to initiate the synchronization process.

### 2\. Command-Line (CLI)

You can also run the script directly from your terminal.

  * **Generate New Images**:

    ```bash
    # Generate 20 images for the topic "Cyberpunk Cityscape"
    dotenv run python wpg.py "Cyberpunk Cityscape" --num 20
    ```

  * **Start Synchronization**:
    Ensure the `HF_DATASET_REPO_ID` and `HF_SECRET` variables are set in your `.env` file.

    ```bash
    python wpg.py sync
    ```

-----

## 📝 License

This project is licensed under the MIT License. See the `LICENSE` file for more details.
