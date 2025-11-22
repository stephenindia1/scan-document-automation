import time
import os
import re
import shutil
import pandas as pd
import pytesseract
from PIL import Image
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from datetime import datetime
import psycopg2
from psycopg2 import sql

# ==========================================
# CONFIGURATION
# ==========================================

# Get the directory where this script is currently located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 1. Folder Paths - Now joined with the script's location
WATCH_FOLDER = os.path.join(BASE_DIR, "input_receipts")
PROCESSED_FOLDER = os.path.join(BASE_DIR, "processed_receipts")
CSV_FILE_PATH = os.path.join(BASE_DIR, "receipt_database.csv")

# 2. Tesseract Path (UPDATE THIS if on Windows)
# Example Windows path: r'C:\Program Files\Tesseract-OCR\tesseract.exe'
# On Mac/Linux, usually distinct configuration isn't needed if in PATH.
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# 3. Database Configuration (Optional - set USE_DB = True to enable)
USE_DB = True
DB_CONFIG = {
    "dbname": "receipts_db",
    "user": "postgres",
    "password": "Exodus7$",
    "host": "localhost",
    "port": "5432"
}


# ==========================================
# CORE PROCESSING LOGIC
# ==========================================

def extract_text_from_image(image_path):
    """
    Uses Tesseract OCR to convert image to raw text.
    """
    try:
        image = Image.open(image_path)
        # Convert to grayscale for better accuracy
        image = image.convert('L')
        text = pytesseract.image_to_string(image)
        return text
    except Exception as e:
        print(f"Error during OCR: {e}")
        return None


def parse_receipt_data(text, filename):
    """
    Parses the raw text to extract structured data.
    Tailored for the 'Health is Wealth' receipt format but generalized for similar layouts.
    """
    lines = text.split('\n')
    cleaned_lines = [line.strip() for line in lines if line.strip()]

    data = {
        "filename": filename,
        "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "store_name": cleaned_lines[0] if cleaned_lines else "Unknown",
        "gstin": None,
        "invoice_amount": 0.0,
        "items": []
    }

    # Regex Patterns
    gstin_pattern = r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}"
    amount_pattern = r"(\d+\.\d{2})"

    # 1. Extract Metadata
    for line in cleaned_lines:
        # Find GSTIN
        if "GSTIN" in line:
            match = re.search(gstin_pattern, line)
            if match:
                data["gstin"] = match.group(0)

        # Find Total Invoice Amount
        if "Invoice Amount" in line or "Total" in line:
            amounts = re.findall(amount_pattern, line)
            if amounts:
                data["invoice_amount"] = float(amounts[-1])

    # 2. Extract Line Items
    # Strategy: Look for lines that end with a number (Amount) and have a number before it (Quantity)
    # Pattern: [Item Name] [Quantity] [Amount]
    item_pattern = r"(.+?)\s+(\d+)\s+(\d+\.\d{2})$"

    start_parsing = False

    for line in cleaned_lines:
        # Start looking for items after the header
        if "Amount" in line and "Quant" in line:
            start_parsing = True
            continue

        # Stop looking when we hit the tax section
        if "Taxable" in line or "Total" in line or "Invoice" in line:
            start_parsing = False

        if start_parsing:
            match = re.search(item_pattern, line)
            if match:
                item_name = match.group(1).strip()
                quantity = int(match.group(2))
                amount = float(match.group(3))

                data["items"].append({
                    "item_name": item_name,
                    "quantity": quantity,
                    "amount": amount
                })

    return data


# ==========================================
# STORAGE HANDLERS
# ==========================================

def save_to_csv(data):
    """
    Flattens the data and appends it to a CSV file.
    """
    rows = []
    if not data['items']:
        # If no items found, still save the metadata
        rows.append({
            "Filename": data['filename'],
            "Date": data['processed_at'],
            "Store": data['store_name'],
            "GSTIN": data['gstin'],
            "Total": data['invoice_amount'],
            "Item": "N/A",
            "Qty": 0,
            "Price": 0.0
        })
    else:
        for item in data['items']:
            rows.append({
                "Filename": data['filename'],
                "Date": data['processed_at'],
                "Store": data['store_name'],
                "GSTIN": data['gstin'],
                "Total": data['invoice_amount'],
                "Item": item['item_name'],
                "Qty": item['quantity'],
                "Price": item['amount']
            })

    df = pd.DataFrame(rows)

    # Append to CSV (header only if file doesn't exist)
    header = not os.path.exists(CSV_FILE_PATH)
    df.to_csv(CSV_FILE_PATH, mode='a', header=header, index=False)
    print(f"Data saved to {CSV_FILE_PATH}")


def save_to_postgres(data):
    """
    Saves data to PostgreSQL.
    Requires a table 'receipts' and 'receipt_items'.
    """
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()

        # Insert Receipt Header
        # UPDATED: Returns 'receipt_id' specifically as requested
        insert_header = """
                        INSERT INTO receipts (store_name, gstin, invoice_total, processed_at, filename)
                        VALUES (%s, %s, %s, %s, %s) RETURNING receipt_id; \
                        """
        cur.execute(insert_header, (
            data['store_name'],
            data['gstin'],
            data['invoice_amount'],
            data['processed_at'],
            data['filename']
        ))
        receipt_id = cur.fetchone()[0]

        # Insert Items
        insert_item = """
                      INSERT INTO receipt_items (receipt_id, item_name, quantity, amount)
                      VALUES (%s, %s, %s, %s); \
                      """
        for item in data['items']:
            cur.execute(insert_item, (
                receipt_id,
                item['item_name'],
                item['quantity'],
                item['amount']
            ))

        conn.commit()
        cur.close()
        conn.close()
        print(f"Data saved to PostgreSQL (Receipt ID: {receipt_id})")

    except Exception as e:
        print(f"Database Error: {e}")


# ==========================================
# WATCHDOG EVENT HANDLER
# ==========================================

class ReceiptHandler(FileSystemEventHandler):
    def on_created(self, event):
        # Ignore directories
        if event.is_directory:
            return

        # Only process image files
        if not event.src_path.lower().endswith(('.png', '.jpg', '.jpeg', '.tiff')):
            return

        print(f"\nNew file detected: {event.src_path}")

        # Wait a moment to ensure file copy is complete
        time.sleep(1)

        # 1. OCR
        raw_text = extract_text_from_image(event.src_path)

        if raw_text:
            # 2. Parse
            filename = os.path.basename(event.src_path)
            structured_data = parse_receipt_data(raw_text, filename)

            # 3. Save
            save_to_csv(structured_data)
            if USE_DB:
                save_to_postgres(structured_data)

            # 4. Move to Processed Folder
            try:
                shutil.move(event.src_path, os.path.join(PROCESSED_FOLDER, filename))
                print(f"Moved {filename} to {PROCESSED_FOLDER}")
            except Exception as e:
                print(f"Error moving file: {e}")


# ==========================================
# MAIN EXECUTION
# ==========================================

if __name__ == "__main__":
    # Ensure directories exist
    os.makedirs(WATCH_FOLDER, exist_ok=True)
    os.makedirs(PROCESSED_FOLDER, exist_ok=True)

    event_handler = ReceiptHandler()
    observer = Observer()
    observer.schedule(event_handler, WATCH_FOLDER, recursive=False)

    print(f"Monitoring '{WATCH_FOLDER}' for new receipts...")
    print("Press Ctrl+C to stop.")

    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()

    observer.join()