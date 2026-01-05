import os 
from docx import Document
from datetime import datetime
import json

folderpath='State-wise AI initiatives'

files = [f for f in os.listdir(folderpath) if f.lower().endswith('.docx')]
def infer_state_name(filename):
    name = filename.replace(".docx", "")
    name = name.replace("AI INITIATIVES IN", "")
    name = name.replace("_", " ")
    return name.strip().title()

def extract_tables(docx_path):
    doc = Document(docx_path)
    initiatives = []
