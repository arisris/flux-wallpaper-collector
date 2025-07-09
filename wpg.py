"""
WPG - Wallpaper Dataset Generator

This script provides a web interface and a command-line interface for generating
AI wallpapers based on user-provided topics and storing them in a dataset,
optionally synchronizing with a Hugging Face repository.

This version includes a safe database merging strategy and enhanced logging with progress bars.

requirements.txt:

fastapi==0.115.13
uvicorn[standard]==0.35.0
Jinja2==3.1.6
pydantic==2.11.7
pillow==11.3.0
httpx==0.27.0
google-genai==1.2.0
python-multipart==0.0.20
huggingface-hub==0.33.2
python-dotenv==1.1.1
"""
import os
import io
import math
import sqlite3
import shutil
import tempfile
from fastapi import FastAPI, Form, Request, Response, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware
from contextlib import asynccontextmanager
import httpx
import json
import random
import uuid
from huggingface_hub import HfApi
from google import genai
from google.genai import types
from typing import List, Optional
import asyncio
from jinja2 import Environment, BaseLoader, Template
import glob
from PIL import Image
from tqdm import tqdm
from tqdm.asyncio import tqdm as atqdm

# --- Configuration Constants ---
DATA_PATH = "data"
LOCAL_DATABASE_PATH = f"{DATA_PATH}/wallpapers.db"
LOCAL_WALLPAPER_PATH = f"{DATA_PATH}/wp"
ARCHIVE_BASE_NAME = f"{DATA_PATH}/wp_archive"
ARCHIVE_FORMAT = "zip"
ARCHIVE_SPLIT_SIZE_MB = 4500 # 4.5 GB
PROMPT_BATCH_SIZE = 50

# --- Environment Variables ---
IMAGE_GENERATOR_URL_TEMPLATE = os.getenv("IMAGE_GENERATOR_URL_TEMPLATE")
GOOGLE_GENAI_API_KEY = os.getenv("GOOGLE_GENAI_API_KEY")
GOOGLE_GENAI_MODEL = os.getenv("GOOGLE_GENAI_MODEL", "gemini-2.5-flash")
HF_DATASET_REPO_ID = os.getenv("HF_DATASET_REPO_ID")
HF_SECRET = os.getenv("HF_SECRET")

# --- Enhanced Logging Helper (English Version) ---
class Log:
    # ANSI escape codes for colors
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

    @staticmethod
    def info(message):
        tqdm.write(f"{Log.OKCYAN}ℹ️  INFO: {message}{Log.ENDC}")

    @staticmethod
    def success(message):
        tqdm.write(f"{Log.OKGREEN}✅ SUCCESS: {message}{Log.ENDC}")

    @staticmethod
    def warning(message):
        tqdm.write(f"{Log.WARNING}⚠️  WARNING: {message}{Log.ENDC}")

    @staticmethod
    def error(message):
        tqdm.write(f"{Log.FAIL}❌ ERROR: {message}{Log.ENDC}")
    
    @staticmethod
    def header(message):
        tqdm.write(f"\n{Log.HEADER}{Log.BOLD}🚀 {message.upper()} 🚀{Log.ENDC}")
        tqdm.write(f"{Log.HEADER}{'-' * (len(message) + 6)}{Log.ENDC}")

    @staticmethod
    def highlight(value):
        return f"{Log.BOLD}{Log.OKBLUE}{value}{Log.ENDC}"

INDEX_TEMPLATE = Template("""
<!DOCTYPE html>
<html lang="en">
<head>
 <meta charset="UTF-8">
 <meta name="viewport" content="width=device-width, initial-scale=1.0">
 <title>WPG - Wallpaper Generator</title>
 <script src="https://cdn.tailwindcss.com"></script>
 <script src="https://unpkg.com/htmx.org@1.9.10"></script>
 <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
 <style>
    .htmx-indicator{
        display:none;
    }
    .htmx-request .htmx-indicator{
        display:inline-block;
    }
    .htmx-request.htmx-indicator{
        display:inline-block;
    }
 </style>
</head>
<body class="bg-gray-900 text-white font-sans" x-data>

 <div class="container mx-auto p-4 md:p-8">
 <header class="text-center mb-8">
 <h1 class="text-4xl md:text-5xl font-bold text-cyan-400">WPG</h1>
 <p class="text-gray-400">AI Wallpaper Dataset Generator</p>
 </header>

 <main class="grid grid-cols-1 md:grid-cols-3 gap-8">
 <div class="md:col-span-1 bg-gray-800 p-6 rounded-lg shadow-lg">
 <h2 class="text-2xl font-semibold mb-4 border-b border-gray-700 pb-2">Generator</h2>
 <form id="generate-form" 
 hx-post="/generate" 
 hx-target="#response-message" 
 hx-swap="innerHTML"
 hx-indicator="#loading-spinner">
 <div class="mb-4">
 <label for="topic_name" class="block text-sm font-medium text-gray-300 mb-1">Topic Name</label>
 <input type="text" id="topic_name" name="topic_name" required
 class="w-full bg-gray-700 border border-gray-600 rounded-md p-2 focus:ring-cyan-500 focus:border-cyan-500 transition">
 </div>
 <div class="mb-6">
 <label for="num_images" class="block text-sm font-medium text-gray-300 mb-1">Number of Images</label>
 <input type="number" id="num_images" name="num_images" value="10" min="1" max="100" required
 class="w-full bg-gray-700 border border-gray-600 rounded-md p-2 focus:ring-cyan-500 focus:border-cyan-500 transition">
 </div>
 <button type="submit" class="w-full bg-cyan-600 hover:bg-cyan-700 text-white font-bold py-2 px-4 rounded-md transition duration-300 ease-in-out flex items-center justify-center">
 <svg id="loading-spinner" class="animate-spin -ml-1 mr-3 h-5 w-5 text-white htmx-indicator" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
 <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
 <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
 </svg>
 Generate Dataset
 </button>
 </form>
 <div id="response-message" class="mt-4 text-center text-green-400"></div>

 <div class="mt-6 pt-6 border-t border-gray-700">
     <h3 class="text-lg font-semibold mb-2">Manual Sync</h3>
     <form id="sync-form"
           hx-post="/sync-hf"
           hx-target="#sync-response-message"
           hx-swap="innerHTML"
           hx-indicator="#sync-spinner">
         <button type="submit" class="w-full bg-purple-600 hover:bg-purple-700 text-white font-bold py-2 px-4 rounded-md transition duration-300 ease-in-out flex items-center justify-center">
             <svg id="sync-spinner" class="animate-spin -ml-1 mr-3 h-5 w-5 text-white htmx-indicator" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                 <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                 <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
             </svg>
             Sync to Hugging Face
         </button>
     </form>
     <div id="sync-response-message" class="mt-4 text-center text-purple-400"></div>
 </div>
 </div>

 <div class="md:col-span-2 bg-gray-800 p-6 rounded-lg shadow-lg">
    <h2 class="text-2xl font-semibold mb-4 border-b border-gray-700 pb-2">Existing Topics</h2>
    
    <div id="topic-list-container" 
         hx-get="/api/topic" 
         hx-trigger="load, newTopicGenerated from:body" 
         hx-swap="outerHTML">
        <p class="text-gray-500">Loading topics...</p>
    </div>
    
 </div>
 </main>

 <section id="gallery-view" class="mt-8">
 </section>

 </div>
</body>
</html>
""")

TOPIC_LIST_PARTIAL = Template("""
<div id="topic-list-container">
    <div id="topic-list" class="space-y-2">
        {% for topic in topics %}
        <div class="topic-item bg-gray-700 p-3 rounded-md hover:bg-gray-600 transition cursor-pointer"
             hx-get="/api/topics/{{ topic.id }}/images"
             hx-target="#gallery-view"
             hx-swap="innerHTML">
             <p class="font-semibold">{{ topic.name }}</p>
        </div>
        {% else %}
        <p class="text-gray-500">No topics found. Generate a new dataset to get started.</p>
        {% endfor %}
    </div>

    {% if total_pages > 1 %}
    <div class="flex justify-center items-center space-x-4 mt-6 pt-4 border-t border-gray-700">
        <a hx-get="/api/topic?page={{ current_page - 1 }}"
           hx-target="#topic-list-container"
           hx-swap="outerHTML"
           class="px-4 py-2 bg-gray-600 rounded-md text-sm font-medium hover:bg-gray-500 cursor-pointer {{ 'opacity-50 !cursor-not-allowed' if current_page == 1 else '' }}">
            &laquo; Previous
        </a>
        <span class="text-sm text-gray-400">
            Page {{ current_page }} of {{ total_pages }}
        </span>
        <a hx-get="/api/topic?page={{ current_page + 1 }}"
           hx-target="#topic-list-container"
           hx-swap="outerHTML"
           class="px-4 py-2 bg-gray-600 rounded-md text-sm font-medium hover:bg-gray-500 cursor-pointer {{ 'opacity-50 !cursor-not-allowed' if current_page == total_pages else '' }}">
            Next &raquo;
        </a>
    </div>
    {% endif %}
</div>
""")

IMAGE_GALLERY_PARTIAL = Template("""
<div class="bg-gray-800 p-6 rounded-lg shadow-lg" 
     x-data="{% raw %}{ open: false, imageUrl: '' }{% endraw %}"
     x-init="console.log('Alpine component for gallery {{ topic_name }} initialized.')">
    
    <h3 class="text-3xl font-bold mb-6 text-cyan-400">{{ topic_name }}</h3>

    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {% for image in images %}
        <div class="group relative cursor-pointer" 
             @click="open = true; imageUrl = '/wp/{{ image.image }}'">
            <img src="/wp/{{ image.image }}?resize=240" alt="{{ image.prompt }}" class="w-full h-auto rounded-lg object-cover aspect-video">
            <div class="absolute bottom-0 left-0 right-0 bg-black bg-opacity-70 p-2 text-xs text-gray-300 opacity-0 group-hover:opacity-100 transition-opacity duration-300 rounded-b-lg">
                <p><strong>Prompt:</strong> {{ image.prompt }}</p>
                <p><strong>Seed:</strong> {{ image.seed }}</p>
            </div>
        </div>
        {% else %}
        <p class="text-gray-500">No images found for this topic.</p>
        {% endfor %}
    </div>

    {% if total_pages > 1 %}
    <div class="flex justify-center items-center space-x-4 mt-6 pt-4 border-t border-gray-700">
        <a hx-get="/api/topics/{{ topic_id }}/images?page={{ current_page - 1 }}"
           hx-target="#gallery-view" hx-swap="innerHTML"
           class="px-4 py-2 bg-gray-600 rounded-md text-sm font-medium hover:bg-gray-500 cursor-pointer {{ 'opacity-50 !cursor-not-allowed' if current_page == 1 else '' }}">
            &laquo; Previous
        </a>
        <span class="text-sm text-gray-400">
            Page {{ current_page }} of {{ total_pages }}
        </span>
        <a hx-get="/api/topics/{{ topic_id }}/images?page={{ current_page + 1 }}"
           hx-target="#gallery-view" hx-swap="innerHTML"
           class="px-4 py-2 bg-gray-600 rounded-md text-sm font-medium hover:bg-gray-500 cursor-pointer {{ 'opacity-50 !cursor-not-allowed' if current_page == total_pages else '' }}">
            Next &raquo;
        </a>
    </div>
    {% endif %}

    <div x-show="open" 
         class="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-80 p-4"
         style="display: none;">
        
        <div class="relative w-full max-w-4xl max-h-full">
            <button @click="open = false" class="absolute -top-8 -right-4 text-white text-4xl font-bold hover:text-gray-300">&times;</button>
            <img :src="imageUrl" alt="Full size preview" class="w-full h-auto max-h-[85vh] object-contain">
            <div class="mt-4 text-center">
                <a :href="`${imageUrl}?download=true`" download
                   class="inline-block bg-cyan-600 hover:bg-cyan-700 text-white font-bold py-2 px-6 rounded-md transition duration-300">
                   Download Image
                </a>
            </div>
        </div>
    </div>
</div>
""")

# --- Database Logic ---
def get_db():
    db = sqlite3.connect(LOCAL_DATABASE_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()

def init_db():
    with sqlite3.connect(LOCAL_DATABASE_PATH) as con:
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS topic (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS image (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_id INTEGER,
                image TEXT NOT NULL UNIQUE,
                prompt TEXT NOT NULL,
                width INTEGER,
                height INTEGER,
                seed INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                notes TEXT,
                is_favorite INTEGER DEFAULT 0,
                FOREIGN KEY (topic_id) REFERENCES topic (id)
            )
        """)
        con.commit()
    Log.info("Database initialized.")

# --- Archive and Sync Logic ---
def split_file(file_path, chunk_size):
    parts = []
    with open(file_path, 'rb') as f:
        part_num = 0
        while True:
            chunk = f.read(chunk_size)
            if not chunk: break
            part_num += 1
            part_filename = f"{file_path}.part{str(part_num).zfill(3)}"
            with open(part_filename, 'wb') as part_file:
                part_file.write(chunk)
            parts.append(part_filename)
    return parts

def join_files(parts, output_path):
    with open(output_path, 'wb') as output_f:
        for part_path in sorted(parts):
            with open(part_path, 'rb') as part_f:
                output_f.write(part_f.read())

def merge_databases(local_backup_path, server_db_path):
    Log.info("Starting database merge...")
    conn_local = sqlite3.connect(local_backup_path)
    conn_server = sqlite3.connect(server_db_path)
    cur_local = conn_local.cursor()
    cur_server = conn_server.cursor()

    cur_local.execute("SELECT name FROM topic")
    for row in cur_local.fetchall():
        cur_server.execute("INSERT OR IGNORE INTO topic (name) VALUES (?)", (row[0],))

    cur_server.execute("SELECT image FROM image")
    server_images = {row[0] for row in cur_server.fetchall()}

    cur_local.execute("SELECT * FROM image")
    local_images = cur_local.fetchall()

    new_images_count = 0
    for img_row in tqdm(local_images, desc="Merging DB Records"):
        img_filename = img_row[2]
        if img_filename not in server_images:
            cur_local.execute("SELECT name FROM topic WHERE id = ?", (img_row[1],))
            topic_name_row = cur_local.fetchone()
            if not topic_name_row: continue

            cur_server.execute("SELECT id FROM topic WHERE name = ?", (topic_name_row[0],))
            server_topic_id_row = cur_server.fetchone()
            if not server_topic_id_row: continue

            new_row_data = (server_topic_id_row[0],) + img_row[2:]
            cur_server.execute("""
                INSERT INTO image (topic_id, image, prompt, width, height, seed, created_at, updated_at, notes, is_favorite) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, new_row_data)
            new_images_count += 1

    conn_server.commit()
    conn_local.close()
    conn_server.close()
    Log.success(f"Database merge complete. {Log.highlight(new_images_count)} new entries added.")

async def sync_with_huggingface(repo_id: str):
    Log.header("Starting Synchronization With Hugging Face")
    if not HF_SECRET:
        raise ValueError("Error: HF_SECRET is not set. Cannot authenticate.")
    api = HfApi(token=HF_SECRET)
    try:
        currentUser = api.whoami()
        Log.info(f"Successfully authenticated as {Log.highlight(currentUser['name'])}.")
        if currentUser:
            api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True)
            await _sync_with_huggingface2(api, repo_id)

    except Exception as e:
        Log.error(f"Error: Could not authenticate. Check HF_SECRET.")
        return

async def _sync_with_huggingface2(api: HfApi, repo_id: str):
    chunk_size = ARCHIVE_SPLIT_SIZE_MB * 1024 * 1024
    archive_full_path = f"{ARCHIVE_BASE_NAME}.{ARCHIVE_FORMAT}"
    local_db_backup_path = f"{LOCAL_DATABASE_PATH}.backup"

    Log.info(f"Creating local database backup to {Log.highlight(os.path.basename(local_db_backup_path))}")
    if os.path.exists(LOCAL_DATABASE_PATH):
        shutil.copy2(LOCAL_DATABASE_PATH, local_db_backup_path)
    else:
        local_db_backup_path = None

    with tempfile.TemporaryDirectory() as temp_dir:
        Log.header("Step 1: PULL - Pulling Data From Repository")
        try:
            with tqdm(total=1, desc="Downloading from HF") as pbar:
                api.snapshot_download(
                    repo_id=repo_id,
                    local_dir=temp_dir,
                    repo_type="dataset",
                )
                pbar.update(1)
            Log.success("Data from the repository was successfully downloaded.")
        except Exception as e:
            if "404" in str(e) or "Repo not found" in str(e):
                Log.warning("Remote repository is empty or not found. Will proceed to PUSH local state.")
            else:
                Log.error(f"Failed to download from Hugging Face: {e}")
                if local_db_backup_path and os.path.exists(local_db_backup_path):
                    os.remove(local_db_backup_path)
                return

        Log.header("Step 2: MERGE & EXTRACT - Merging and Extracting Data")
        
        remote_db_in_temp = os.path.join(temp_dir, os.path.basename(LOCAL_DATABASE_PATH))
        if os.path.exists(remote_db_in_temp):
            Log.info("Remote database found. Setting it as the base for merging.")
            shutil.copy2(remote_db_in_temp, LOCAL_DATABASE_PATH)
        
        if local_db_backup_path and os.path.exists(local_db_backup_path):
            merge_databases(local_db_backup_path, LOCAL_DATABASE_PATH)
            os.remove(local_db_backup_path)

        archive_parts_in_temp = sorted(glob.glob(f"{temp_dir}/{os.path.basename(ARCHIVE_BASE_NAME)}.part*"))
        if archive_parts_in_temp:
            Log.info(f"Found {Log.highlight(len(archive_parts_in_temp))} remote archive parts. Joining...")
            temp_archive_full_path = os.path.join(temp_dir, f"{os.path.basename(ARCHIVE_BASE_NAME)}.{ARCHIVE_FORMAT}")
            join_files(archive_parts_in_temp, temp_archive_full_path)
            
            Log.info(f"Merging remote images by extracting archive to {Log.highlight(LOCAL_WALLPAPER_PATH)}...")
            shutil.unpack_archive(temp_archive_full_path, LOCAL_WALLPAPER_PATH, format=ARCHIVE_FORMAT)
            
            Log.success("Extraction of remote archive complete.")
        else:
            Log.info("No remote image archives found to extract.")

    Log.header("Step 3: PUSH - Pushing Data To Repository")
    if os.path.exists(LOCAL_WALLPAPER_PATH) and os.listdir(LOCAL_WALLPAPER_PATH):
        Log.info(f"Creating archive from the merged {Log.highlight('wp')} folder...")
        shutil.make_archive(ARCHIVE_BASE_NAME, ARCHIVE_FORMAT, LOCAL_WALLPAPER_PATH)
        
        Log.info("Splitting archive if necessary...")
        parts_to_upload = split_file(archive_full_path, chunk_size)
        Log.info(f"Archive split into {Log.highlight(len(parts_to_upload))} parts.")
    else:
        parts_to_upload = []

    repo_files = api.list_repo_files(repo_id=repo_id, repo_type="dataset")
    old_parts = [f for f in repo_files if f.startswith(os.path.basename(ARCHIVE_BASE_NAME))]
    if old_parts:
        Log.info(f"Deleting {Log.highlight(len(old_parts))} old archives from the repository...")
        api.delete_files(repo_id=repo_id, delete_patterns=old_parts, repo_type="dataset", commit_message="Sync: Delete old archives")

    with tqdm(total=len(parts_to_upload) + 1, desc="Uploading to HF") as pbar:
        for i, part_path in enumerate(parts_to_upload):
            part_filename = os.path.basename(part_path)
            pbar.set_description(f"Uploading part {i+1}/{len(parts_to_upload)}")
            api.upload_file(path_or_fileobj=part_path, path_in_repo=part_filename, repo_id=repo_id, repo_type="dataset")
            pbar.update(1)
        
        pbar.set_description("Uploading database")
        api.upload_file(path_or_fileobj=LOCAL_DATABASE_PATH, path_in_repo="wallpapers.db", repo_id=repo_id, repo_type="dataset", commit_message="Sync: Upload database")
        pbar.update(1)

    if os.path.exists(archive_full_path):
        os.remove(archive_full_path)
    for part in parts_to_upload:
        if os.path.exists(part):
            os.remove(part)
    
    Log.success("PUSH synchronization successful.")
    Log.header("Synchronization Complete")

async def generate_prompts(topic_name: str, num_prompts: int) -> List[str]:
    """
    Generates a specified number of prompts using a stateful conversational approach with the AI.
    The function instructs the AI to deliver prompts in batches and waits for a "next" command
    to proceed, ensuring large requests are handled gracefully.
    """
    Log.header(f"Starting Chat Session to Create {num_prompts} Prompts")
    Log.info(f"Topic: {Log.highlight(topic_name)}, Batch Size: {Log.highlight(PROMPT_BATCH_SIZE)}")

    if not GOOGLE_GENAI_API_KEY:
        Log.error("GOOGLE_GENAI_API_KEY is not set.")
        return []
    generation_config = types.GenerateContentConfig(
        temperature=1.2,
        response_mime_type="application/json",
        response_schema=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "items": types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(type=types.Type.STRING),
                ),
            },
        ),
    )
    try:
        client = genai.Client(api_key=GOOGLE_GENAI_API_KEY)
        chat_session = client.aio.chats.create(model=GOOGLE_GENAI_MODEL, config=generation_config)
    except Exception as e:
        Log.error(f"Failed to initialize Generative AI model: {e}")
        return []

    initial_prompt = """
You are an expert prompt engineer. Your task is to generate a total of {num_prompts} highly creative and detailed image prompts for the topic: '{topic_name}'.
Include keywords like "4k", "high resolution", "photorealistic", "cinematic lighting", "epic scale".

The rules for our interaction are as follows:
1. You MUST provide the prompts in batches. Each batch must contain exactly {PROMPT_BATCH_SIZE} prompts.
2. After providing a batch, you MUST stop and wait for me to say "next".
3. When I say "next", you will provide the next batch of {PROMPT_BATCH_SIZE} new prompts, ensuring there are no duplicates from previous batches.
4. Continue this process until you have delivered the total of {num_prompts} prompts.
5. After the final batch is delivered (meaning the total has reached or exceeded {num_prompts}), the next time I say "next", you MUST respond ONLY with a JSON object containing an empty list: {{"items": []}}. This is the signal for me that the task is complete.

Now, provide the first batch of {PROMPT_BATCH_SIZE} prompts.
""".format(
        num_prompts=num_prompts,
        topic_name=topic_name,
        PROMPT_BATCH_SIZE=PROMPT_BATCH_SIZE
    )

    all_prompts = []
    
    try:
        with atqdm(total=num_prompts, desc="Generating Prompts") as pbar:
            response = await chat_session.send_message(initial_prompt)

            while len(all_prompts) < num_prompts:
                try:
                    prompts_data = json.loads(response.text)
                    current_batch = prompts_data.get("items", [])
                except json.JSONDecodeError:
                    Log.error(f"Failed to parse JSON from AI response: {response.text}")
                    break # Exit loop on parsing error

                if not current_batch:
                    if len(all_prompts) < num_prompts:
                        Log.warning("AI finished early. The number of prompts might be less than requested.")
                    pbar.update(num_prompts - pbar.n) # Fill the progress bar
                    break

                # Calculate how many prompts to take from this batch
                remaining_needed = num_prompts - len(all_prompts)
                to_add = current_batch[:remaining_needed]

                all_prompts.extend(to_add)
                pbar.update(len(to_add))

                # If we still need more prompts, request the next batch
                if len(all_prompts) < num_prompts:
                    response = await chat_session.send_message("next")
                else:
                    # We have enough, so we break the loop
                    break
    
    except Exception as e:
        Log.error(f"An unexpected error occurred during the chat session: {e}")
    finally:
        Log.success(f"Chat Session Finished. A total of {len(all_prompts)} prompts were successfully created.")
        return all_prompts[:num_prompts]

async def generate_wallpaper(prompt: str, width: int, height: int) -> Optional[tuple[str, int]]:
    seed = random.randint(0, 1_000_000_000)
    if not IMAGE_GENERATOR_URL_TEMPLATE:
        Log.error("IMAGE_GENERATOR_URL_TEMPLATE is not set.")
        return None
    
    encoded_prompt = httpx.URL(prompt).path
    api_url = IMAGE_GENERATOR_URL_TEMPLATE.format_map({
        "prompt": encoded_prompt,
        "width": width,
        "height": height,
        "seed": seed
    })
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.get(api_url)
            response.raise_for_status()
            
            image_bytes = response.content
            filename = f"{LOCAL_WALLPAPER_PATH}/{uuid.uuid4()}.png"
            os.makedirs(LOCAL_WALLPAPER_PATH, exist_ok=True)
            with open(filename, "wb") as f:
                f.write(image_bytes)
            return filename, seed
    except Exception as e:
        Log.error(f"Failed to generate wallpaper for prompt '{prompt[:50]}...': {e}")
        return None

# --- CLI Generation Logic ---
async def run_cli_generate(args):
    """Handles the image generation process from the command line."""
    Log.header(f"Generating {args.num} images for topic: {args.topic_name}")
    
    prompts = await generate_prompts(args.topic_name, args.num)
    if not prompts:
        Log.error("Failed to generate prompts. Process stopped.")
        return

    db = sqlite3.connect(LOCAL_DATABASE_PATH)
    cur = db.cursor()
    cur.execute("INSERT OR IGNORE INTO topic (name) VALUES (?)", (args.topic_name,))
    db.commit()
    cur.execute("SELECT id FROM topic WHERE name = ?", (args.topic_name,))
    topic_id = cur.fetchone()[0]

    generated_count = 0
    with tqdm(total=len(prompts), desc="Generating Wallpapers") as pbar:
        for prompt in prompts:
            pbar.set_description(f"Generating: {prompt[:45]}...")
            try:
                result = await generate_wallpaper(prompt, 1280, 768)
                if result:
                    image_filename, seed = result
                    image_filename_base = os.path.basename(image_filename)
                    cur.execute(
                        "INSERT OR IGNORE INTO image (topic_id, image, prompt, width, height, seed) VALUES (?, ?, ?, ?, ?, ?)",
                        (topic_id, image_filename_base, prompt, 1280, 768, seed)
                    )
                    generated_count += 1
            except Exception as e:
                tqdm.write(f"{Log.FAIL}An error occurred while processing prompt: {prompt[:40]}... Error: {e}{Log.ENDC}")
            pbar.update(1)

    db.commit()
    db.close()

    Log.success(f"Process finished. {Log.highlight(generated_count)}/{Log.highlight(len(prompts))} images successfully created.")
    Log.info(f"Run {Log.highlight('python wpg.py sync')} to upload changes.")


# --- FastAPI App ---
@asynccontextmanager
async def lifespan(app):
    os.makedirs(DATA_PATH, exist_ok=True)
    os.makedirs(LOCAL_WALLPAPER_PATH, exist_ok=True)
    init_db()
    Log.success("Application is ready. Manual synchronization is available.")
    yield
    Log.info("Application shutting down.")

app = FastAPI(title="WPG", description="Wallpaper Dataset Generator", lifespan=lifespan)

app.add_middleware(GZipMiddleware)

templates = Jinja2Templates(env=Environment(loader=BaseLoader()))

@app.get("/wp/{image}")
async def serve_image(request: Request, image: str):
    img_path = os.path.join(LOCAL_WALLPAPER_PATH, image)
    if not os.path.exists(img_path):
        return Response(status_code=404)
        
    img = Image.open(img_path)
    
    # Handle resizing request
    resize = request.query_params.get("resize")
    if resize and resize.isdigit():
        resize_val = int(resize)
        img.thumbnail((resize_val, resize_val), Image.Resampling.LANCZOS)
        
    img_bytes = io.BytesIO()
    is_download = request.query_params.get("download", False)
    if is_download:
        img.save(img_bytes, format="PNG")
        img_bytes.seek(0)
        return Response(content=img_bytes.read(), media_type="image/png", headers={"Content-Disposition": f"attachment; filename={image}"})
    
    accept_header = request.headers.get("accept", "")
    
    # Check if the client's browser accepts the WebP format
    if "image/webp" in accept_header:
        # Serve compressed WebP for modern browsers
        # The 'quality' parameter (1-100) adjusts compression. 80 is a good balance.
        img.save(img_bytes, format="WEBP", quality=80)
        media_type = "image/webp"
    else:
        # Fallback to PNG for older clients
        img.save(img_bytes, format="PNG")
        media_type = "image/png"
        
    img_bytes.seek(0)
    
    # Return the image with appropriate content type and cache headers
    return Response(
        content=img_bytes.read(), 
        media_type=media_type, 
        headers={"Cache-Control": "max-age=3600"} # Cache for 1 hour
    )

@app.get("/api/topic", response_class=HTMLResponse)
async def api_get_topics(request: Request, db: sqlite3.Connection = Depends(get_db), page: int = 1):
    ITEMS_PER_PAGE = 20
    
    # Pastikan halaman tidak kurang dari 1
    page = max(1, page)
    offset = (page - 1) * ITEMS_PER_PAGE

    # Dapatkan jumlah total topik
    total_topics_query = db.execute("SELECT COUNT(*) FROM topic").fetchone()
    total_topics = total_topics_query[0] if total_topics_query else 0
    total_pages = math.ceil(total_topics / ITEMS_PER_PAGE) if total_topics > 0 else 1
    
    # Ambil topik untuk halaman saat ini
    topics_query = "SELECT * FROM topic ORDER BY name LIMIT ? OFFSET ?"
    topics = db.execute(topics_query, (ITEMS_PER_PAGE, offset)).fetchall()

    return TOPIC_LIST_PARTIAL.render(
        request=request,
        topics=topics,
        current_page=page,
        total_pages=total_pages
    )

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, db: sqlite3.Connection = Depends(get_db)):
    return INDEX_TEMPLATE.render(request=request)

@app.post("/generate", response_class=JSONResponse)
async def generate_images_api(response: Response, topic_name: str = Form(...), num_images: int = Form(...), db: sqlite3.Connection = Depends(get_db)):
    if not topic_name:
        return JSONResponse(content={"error": "Topic name cannot be empty."}, status_code=400)
    prompts = await generate_prompts(topic_name, num_images)
    
    if not prompts:
        return JSONResponse(content={"error": "Failed to generate prompts."}, status_code=500)

    cur = db.cursor()
    cur.execute("INSERT OR IGNORE INTO topic (name) VALUES (?)", (topic_name,))
    db.commit()
    cur.execute("SELECT id FROM topic WHERE name = ?", (topic_name,))
    topic_id = cur.fetchone()['id']

    generated_count = 0
    for index, prompt in enumerate(prompts):
        try:
            result = await generate_wallpaper(prompt, 1280, 768)
            if result:
                image_filename, seed = result
                image_filename_base = os.path.basename(image_filename)
                cur.execute(
                    "INSERT OR IGNORE INTO image (topic_id, image, prompt, width, height, seed) VALUES (?, ?, ?, ?, ?, ?)",
                    (topic_id, image_filename_base, prompt, 1280, 768, seed)
                )
                generated_count += 1
        except Exception as e:
            Log.error(f"An error occurred while generating wallpaper: {index}")
    db.commit()

    if generated_count > 0:
        response.headers["HX-Trigger"] = "newTopicGenerated"
        return JSONResponse(content={"message": f"Generated {generated_count}/{len(prompts)} images for '{topic_name}'. Sync manually."})
    else:
        return JSONResponse(content={"error": "Failed to generate any images."}, status_code=500)

@app.post("/sync-hf", response_class=JSONResponse)
async def sync_hf_api():
    if not HF_DATASET_REPO_ID:
        return JSONResponse(content={"error": "HF_DATASET_REPO_ID is not set."}, status_code=400)
    try:
        await sync_with_huggingface(HF_DATASET_REPO_ID)
        return JSONResponse(content={"message": "Synchronization with Hugging Face was successful."})
    except Exception as e:
        Log.error(f"Error during manual sync: {e}")
        return JSONResponse(content={"error": f"Synchronization failed: {e}"}, status_code=500)

@app.get("/api/topics/{topic_id}/images", response_class=HTMLResponse)
async def api_get_images_for_topic(request: Request, topic_id: int, db: sqlite3.Connection = Depends(get_db), page: int = 1):
    IMAGES_PER_PAGE = 12 # Jumlah gambar yang wajar per halaman galeri

    page = max(1, page)
    offset = (page - 1) * IMAGES_PER_PAGE

    # Dapatkan info topik
    topic = db.execute("SELECT name FROM topic WHERE id = ?", (topic_id,)).fetchone()
    if not topic:
        return HTMLResponse(content='<div class="p-4 text-red-400">Topic not found.</div>', status_code=404)
    topic_name = topic['name']

    # Hitung jumlah total gambar untuk topik ini
    total_images_query = db.execute("SELECT COUNT(*) FROM image WHERE topic_id = ?", (topic_id,)).fetchone()
    total_images = total_images_query[0] if total_images_query else 0
    total_pages = math.ceil(total_images / IMAGES_PER_PAGE) if total_images > 0 else 1

    # Ambil gambar untuk halaman saat ini
    images_query = "SELECT * FROM image WHERE topic_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?"
    images = db.execute(images_query, (topic_id, IMAGES_PER_PAGE, offset)).fetchall()

    return IMAGE_GALLERY_PARTIAL.render(
        request=request,
        images=images,
        topic_name=topic_name,
        topic_id=topic_id, # Teruskan topic_id untuk link paginasi
        current_page=page,
        total_pages=total_pages
    )

def main():
    import argparse
    parser = argparse.ArgumentParser(description="WPG - Wallpaper Dataset Generator")
    parser.add_argument('topic_name', nargs='?', default=None, help='Topic name or \"sync\" command.')
    parser.add_argument('--num', type=int, default=10, help='Number of wallpapers to generate.')
    args = parser.parse_args()

    os.makedirs(DATA_PATH, exist_ok=True)
    os.makedirs(LOCAL_WALLPAPER_PATH, exist_ok=True)
    init_db()

    if args.topic_name == 'sync':
        if not HF_DATASET_REPO_ID:
            Log.error("HF_DATASET_REPO_ID is not set. Cannot run synchronization.")
            return
        asyncio.run(sync_with_huggingface(HF_DATASET_REPO_ID))
    elif args.topic_name:
        Log.info(f"Running CLI mode for topic: {Log.highlight(args.topic_name)}")
        asyncio.run(run_cli_generate(args))
    else:
        import uvicorn
        Log.info("Starting Web UI at http://0.0.0.0:8000")
        uvicorn.run_web_server("wpg:app", host="0.0.0.0", port=8000, reload=True)

if __name__ == "__main__":
    main()
