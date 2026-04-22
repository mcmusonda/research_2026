import json

# Load the original JSON file
with open('data/lusaka_times/lusaka_times_full_articles3.json', 'r', encoding='utf-8') as f:
    data = json.load(f)  # Assumes JSON is an array of objects

# Define how many items per file
chunk_size = 4000  # Adjust based on your needs
total_chunks = len(data) // chunk_size + (1 if len(data) % chunk_size else 0)

# Split and save
for i in range(total_chunks):
    chunk = data[i * chunk_size : (i + 1) * chunk_size]
    with open(f'temp_data/lusaka_times/lusaka_times_plit_{i+1}.json', 'w') as f:
        json.dump(chunk, f, indent=2)  # `indent` for pretty-printing (optional)
