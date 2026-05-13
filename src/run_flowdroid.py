import subprocess
from pathlib import Path
from xml.dom import minidom
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]

FLOWDROID_JAR = PROJECT_ROOT / "FlowDroid-2.15.1/soot-infoflow-cmd/target/soot-infoflow-cmd-jar-with-dependencies.jar"
SOURCES_SINKS = PROJECT_ROOT / "FlowDroid-2.15.1/SourcesAndSinks.txt"

OUTPUT_DIR = PROJECT_ROOT / "data/xml_results"
ANDROID_PLATFORMS = Path.home() / "Library/Android/sdk/platforms"


def pretty_print_xml(xml_file: Path):
    """Pretty-print the XML file outputed by FlowDroid"""
    raw_xml = xml_file.read_text()
    parsed_xml = minidom.parseString(raw_xml)
    xml_file.write_text(parsed_xml.toprettyxml(indent=" "))
    print(f"Pretty-printed XML saved to: {xml_file}")


def run_flowdroid(apk_path: Path):
    """
    Run FlowDroid on the supplied .apk file and save the resulting XML file in data/xml_results
    """
    apk_name = apk_path.stem
    output_file = OUTPUT_DIR / f"{apk_name}.xml"

    # Make sure the output folder exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Ensure the XML file exists before running FlowDroid
    if not output_file.exists():
        output_file.touch()

    cmd = [
        "java",
        "-Xmx8G",
        "-jar",
        str(FLOWDROID_JAR),
        "-a",
        str(apk_path),
        "-p",
        str(ANDROID_PLATFORMS),
        "-s",
        str(SOURCES_SINKS),
        "-o",
        str(output_file),
        "-ol",
        "-on",
        "-pr",
        "PRECISE",
        "ps",
        "-aa",
        "FLOWSENSITIVE",
        "-cg",
        "SPARK",
        "-ca",
        "DEFAULT",
        "-al",
        "5"
    ]

    print("Running FlowDroid...")
    print(" ".join(cmd))

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"FlowDroid failed with exit code {e.returncode}")
        sys.exit(1)

    print(f"\n Results saved to: {output_file}")

    # Pretty-print the XML if the file exists
    if not output_file.exists():
        raise RuntimeError(f"FlowDroid did not produce output: {output_file}")
    pretty_print_xml(output_file)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 run_flowdroid.py <APK_PATH>")
        sys.exit(1)

    try:
        run_flowdroid(Path(sys.argv[1]))
    except Exception as e:
        print(f"[run_flowdroid.py] Error: {e}")