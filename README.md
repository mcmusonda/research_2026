# Automatic Classification of Research-Based News Articles

## 📌 Project Overview
This project is part of a research study titled:

**“Automatic Summarisation of Electronic Theses and Dissertations for Increased Media Engagement”**

The goal of this component (Objective 1) is to:
- **Determine the extent of mainstream media coverage of research findings**
- Automatically classify news articles as:
  - `research related`
  - `not research related`

The classification is performed using a **locally hosted Large Language Model (LLM)** via **Ollama API**.

---

## 🎯 Objectives

- Process large volumes of news articles (JSON format)
- Identify articles based on **research findings or academic studies**
- Generate structured outputs for:
  - Quantitative analysis (frequency, trends)
  - Further qualitative analysis

---

## ⚙️ Features

- Supports:
  - `.json`, `.jsonl`, `.ndjson`
- Works with **multiple media sources**
- Uses **local LLM (Ollama)** → no internet dependency
- Scalable for **large datasets (100,000+ articles)**
- Outputs results to **CSV for analysis**

---

## 🏗️ Project Structure
project-root/
│
├── data/ # Raw harvested articles (ignored in git)
│ ├── lusaka_times/
│ ├── diggers/
│ └── ...
│
├── scripts/
│ └── classify_articles_ollama.py
│
├── results/ # Output CSV files
│
├── README.md
├── .gitignore
└── requirements.txt


---

## 🔧 Requirements

- Python 3.9+
- Ollama installed and running locally
- Required Python packages:

```bash
pip install requests pandas