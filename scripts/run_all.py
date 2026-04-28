from pathlib import Path
import subprocess


XML_DIR = Path("data/xml_results")

for xml_file in XML_DIR.glob("*.xml"):
    name = xml_file.stem  # e.g. LocationLeak1
    print(f"\n=== Running {name} ===")

    subprocess.run([
        "python3",
        "src/graph/graph_builder.py",
        name
    ])