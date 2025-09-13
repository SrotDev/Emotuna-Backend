import sys
from pipeline_utils import clean_sft_jsonl

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python clean_sft_jsonl.py <path_to_sft_dataset.jsonl>")
        sys.exit(1)
    jsonl_path = sys.argv[1]
    clean_sft_jsonl(jsonl_path)
    print(f"Cleaned: {jsonl_path}")