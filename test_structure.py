import os
import shutil

# Define paths exactly as the main script does
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, "input_receipts")
PROCESSED_DIR = os.path.join(BASE_DIR, "processed_receipts")

print(f"--- TESTING FOLDER STRUCTURE ---")
print(f"Root Directory: {BASE_DIR}\n")

# 1. Create Directories
all_good = True
for folder in [INPUT_DIR, PROCESSED_DIR]:
    try:
        os.makedirs(folder, exist_ok=True)
        print(f"✅ Verified/Created folder:\n   {folder}")
    except Exception as e:
        print(f"❌ Failed to create folder {folder}: {e}")
        all_good = False

# 2. Test Write Permissions (Create a dummy file)
test_filename = "structure_test_file.tmp"
source_test_file = os.path.join(INPUT_DIR, test_filename)

if all_good:
    try:
        with open(source_test_file, 'w') as f:
            f.write("This is a test file to verify permissions.")
        print(f"\n✅ Write permission confirmed (created dummy file in input_receipts).")
    except Exception as e:
        print(f"\n❌ Write failed in input_receipts: {e}")
        all_good = False

# 3. Test Move Permissions (Simulate processing move)
dest_test_file = os.path.join(PROCESSED_DIR, test_filename)

if all_good and os.path.exists(source_test_file):
    try:
        # Clean up destination if it exists from a previous failed run
        if os.path.exists(dest_test_file):
            os.remove(dest_test_file)

        shutil.move(source_test_file, dest_test_file)
        print(f"✅ Move permission confirmed (Input -> Processed).")

        # Cleanup: Remove the test file from processed folder
        os.remove(dest_test_file)
        print(f"✅ Cleanup successful (Test file deleted).")

    except Exception as e:
        print(f"❌ Move failed: {e}")
        all_good = False

print("\n------------------------------")
if all_good:
    print("SUCCESS: Folder structure is ready.")
    print("You can now run 'receipt_automator.py'.")
else:
    print("FAILURE: Please check directory permissions.")